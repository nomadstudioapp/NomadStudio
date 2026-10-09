"""Help a brand-new user get ComfyUI and LM Studio, which Nomad Studio needs
but does not include.

Until now the wizard assumed both existed somewhere and were merely switched
off. Someone starting from zero was told "start ComfyUI" with no way forward.
This module covers the three cases:

- **installed but not running** — find it on disk and start it;
- **not installed** — download the official ComfyUI portable build and unpack
  it (LM Studio is an installer with its own window: we send the user to its
  download page);
- **no suitable GPU** — say so before they download 2 GB for nothing.

Nothing here runs from another computer's browser: the routes that start or
install anything are marked local_only.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import uuid
from pathlib import Path
from typing import Any

import logging

logger = logging.getLogger(__name__)

COMFY_RELEASES_API = "https://api.github.com/repos/comfyanonymous/ComfyUI/releases/latest"
LMSTUDIO_DOWNLOAD_PAGE = "https://lmstudio.ai/download"
# Stable redirect to the current Windows installer.
LMSTUDIO_INSTALLER_URL = "https://lmstudio.ai/download/latest/win32/x64"
# Windows ships bsdtar, which reads (and writes) 7z — no extra dependency for
# the 7z the ComfyUI portable build is published as.
WINDOWS_TAR = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "tar.exe"
SEVEN_ZIP = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "7-Zip" / "7z.exe"
MIN_FREE_BYTES = 8 * 2**30  # ~2 GB archive + ~5 GB unpacked, with room to spare
# Microsoft's Visual C++ runtime, which PyTorch inside ComfyUI loads. A fresh
# Windows does not have it, and the portable ComfyUI then closes as soon as it
# starts ("Error loading c10.dll") — found installing on a clean Windows 11 VM.
# Official permalink to the current x64 installer.
VCREDIST_URL = "https://aka.ms/vs/17/release/vc_redist.x64.exe"
_VC_RUNTIME_DLLS = ("vcruntime140.dll", "vcruntime140_1.dll", "msvcp140.dll")
VCREDIST_WAIT_SECONDS = 600
LMSTUDIO_INSTALLER_WAIT_SECONDS = 1800


# ── This machine ────────────────────────────────────────────────────────────

_gpus: list[str] | None = None


def gpu_names() -> list[str]:
    """Graphics cards in this computer, read without ComfyUI's help so the
    wizard can warn before a 2 GB download. Empty list when unknown."""
    global _gpus
    if _gpus is not None:
        return _gpus
    _gpus = []
    if sys.platform.startswith("win"):
        try:
            out = subprocess.run(  # noqa: S603,S607 — fixed command
                ["powershell", "-NoProfile", "-Command",
                 "Get-CimInstance Win32_VideoController | Select-Object -ExpandProperty Name"],
                capture_output=True, text=True, timeout=20, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            _gpus = [line.strip() for line in out.stdout.splitlines() if line.strip()]
        except Exception:  # noqa: BLE001 — never block the wizard
            logger.debug("could not read the GPU list", exc_info=True)
    return _gpus


def gpu_vendor() -> str:
    """"nvidia" | "amd" | "intel" | "" — which portable build to offer."""
    names = " ".join(gpu_names()).lower()
    for vendor, needles in (("nvidia", ("nvidia", "geforce", "quadro", "rtx", "gtx")),
                            ("amd", ("amd", "radeon")),
                            ("intel", ("intel", "arc"))):
        if any(n in names for n in needles):
            return vendor
    return ""


def vc_runtime_installed() -> bool:
    """Whether the Visual C++ runtime PyTorch needs is on this machine: the
    DLLs themselves, which is what ComfyUI fails to load without it."""
    if not sys.platform.startswith("win"):
        return True
    system32 = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
    return all((system32 / dll).is_file() for dll in _VC_RUNTIME_DLLS)


# ── Finding what is already installed ───────────────────────────────────────


def _comfy_candidates() -> list[Path]:
    home = Path.home()
    roots = [home, home / "Documents", home / "Desktop", home / "Downloads"]
    roots += [Path(f"{letter}:\\") for letter in "CDEFG" if Path(f"{letter}:\\").exists()]
    names = ("ComfyUI_windows_portable", "ComfyUI", "comfyui")
    return [root / name for root in roots for name in names]


def _comfy_in(root: Path) -> dict[str, Any] | None:
    """A portable ComfyUI directly inside *root* (where we just unpacked it)."""
    for path in [root, *(p for p in root.iterdir() if p.is_dir())] if root.is_dir() else []:
        for bat in ("run_nvidia_gpu.bat", "run_cpu.bat", "run_amd_gpu.bat", "run_intel_gpu.bat"):
            if (path / bat).is_file():
                return {"kind": "portable", "path": str(path), "launcher": str(path / bat)}
    return None


# Preference order when more than one is installed. The portable build is the
# one Nomad Studio works best with: it is the one ComfyUI publishes for this,
# its models folder is a plain directory we can point at, and it takes
# --listen for a server on the network. The desktop app manages its own
# install and is harder to steer, and a git clone we can find but not start.
_COMFY_PREFERENCE = ("portable", "desktop", "source")
_COMFY_LAUNCHERS = ("run_nvidia_gpu.bat", "run_cpu.bat", "run_amd_gpu.bat", "run_intel_gpu.bat")


def find_comfyui_all() -> list[dict[str, Any]]:
    """Every ComfyUI installation on this machine, best first."""
    found: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add(item: dict[str, Any]) -> None:
        if item["path"].lower() not in seen:
            seen.add(item["path"].lower())
            found.append(item)

    for path in _comfy_candidates():
        try:
            if not path.is_dir():
                continue
        except OSError:
            continue
        launcher = next((path / bat for bat in _COMFY_LAUNCHERS if (path / bat).is_file()), None)
        if launcher is not None:
            add({"kind": "portable", "path": str(path), "launcher": str(launcher)})
        elif (path / "main.py").is_file():  # a git clone: we can point at it, not start it
            add({"kind": "source", "path": str(path), "launcher": ""})
    programs = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "Programs"
    try:
        for folder in programs.glob("*comfy*"):
            exe = next((p for p in folder.glob("*.exe") if "comfy" in p.name.lower()), None)
            if exe:
                add({"kind": "desktop", "path": str(folder), "launcher": str(exe)})
    except OSError:
        pass
    found.sort(key=lambda item: _COMFY_PREFERENCE.index(item["kind"]))
    return found


def find_comfyui() -> dict[str, Any] | None:
    """The ComfyUI this machine should use: portable before desktop."""
    return (find_comfyui_all() or [None])[0]


def comfy_models_dir(info: dict[str, Any] | None) -> str:
    """The models folder of a portable ComfyUI, so the wizard can fill it in
    instead of asking a new user for a path they have never seen."""
    if info and info.get("kind") == "portable":
        models = Path(info["path"]) / "ComfyUI" / "models"
        if models.is_dir():
            return str(models)
    return ""


def find_lmstudio() -> dict[str, Any] | None:
    """LM Studio on this machine, plus its `lms` command line tool when it is
    there (it can start the server without the window)."""
    local = Path(os.environ.get("LOCALAPPDATA", str(Path.home())))
    exe = None
    for candidate in (local / "Programs" / "lm-studio" / "LM Studio.exe",
                      local / "Programs" / "LM Studio" / "LM Studio.exe",
                      Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "LM Studio" / "LM Studio.exe"):
        if candidate.is_file():
            exe = candidate
            break
    if exe is None:
        try:
            for folder in (local / "Programs").glob("*lm*studio*"):
                found = next((p for p in folder.glob("*.exe") if "lm studio" in p.name.lower()), None)
                if found:
                    exe = found
                    break
        except OSError:
            pass
    cli = Path.home() / ".lmstudio" / "bin" / ("lms.exe" if sys.platform.startswith("win") else "lms")
    if exe is None and not cli.is_file():
        return None
    return {"kind": "app", "path": str(exe or cli), "launcher": str(exe or ""), "cli": str(cli) if cli.is_file() else ""}


def state() -> dict[str, Any]:
    """What the wizard needs to decide what to offer."""
    vendor = gpu_vendor()
    comfy = find_comfyui()
    return {
        "gpus": gpu_names(),
        "gpuVendor": vendor,
        "canInstallComfy": sys.platform.startswith("win") and _extractor() is not None,
        "vcRuntime": vc_runtime_installed(),
        "comfy": comfy,
        "comfyModelsDir": comfy_models_dir(comfy),
        "comfyAll": find_comfyui_all(),
        "comfyCanListen": can_listen(),
        "lmstudio": find_lmstudio(),
        "lmstudioUrl": LMSTUDIO_DOWNLOAD_PAGE,
        "suggestedDir": str(Path.home()),
    }


# ── Starting them ───────────────────────────────────────────────────────────


def _spawn(args: list[str], cwd: str | None = None) -> subprocess.Popen:
    return subprocess.Popen(  # noqa: S603 — paths we found ourselves, local app
        args, cwd=cwd, close_fds=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if args[0].endswith(".exe") else 0,
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def can_listen(info: dict[str, Any] | None = None) -> bool:
    """Whether we can start this install ourselves with --listen. The portable
    build ships its own Python, so we can; the desktop app has that as a
    setting of its own and its .bat does not forward arguments."""
    info = info or find_comfyui()
    if not info or info.get("kind") != "portable":
        return False
    root = Path(info["path"])
    return (root / "python_embeded" / "python.exe").is_file() and (root / "ComfyUI" / "main.py").is_file()


def start_comfyui(listen: bool = False) -> dict[str, Any]:
    """Start ComfyUI. With *listen*, start it so other computers on the
    network can reach it (--listen 0.0.0.0) — Windows asks about the firewall
    the first time."""
    info = find_comfyui()
    if not info or not info.get("launcher"):
        return {"ok": False, "error": "No ComfyUI installation was found on this computer"}
    # Its console would open and close again at once, leaving the wizard
    # waiting for nothing: ask for the runtime first.
    if info.get("kind") == "portable" and not vc_runtime_installed():
        return {"ok": False, "needsVcRuntime": True,
                "error": "ComfyUI needs the Microsoft Visual C++ runtime, which this computer does not have yet"}
    nvidia_bat = Path(info["launcher"]).name.lower() == "run_nvidia_gpu.bat"
    if can_listen(info) and (listen or nvidia_bat):
        # Its own Python directly rather than run_nvidia_gpu.bat (which runs
        # exactly this): the .bat opens ComfyUI's page in the browser, which
        # jumped in front of the wizard on a first install. Other .bat files
        # may add flags of their own, so they still run as they are. cmd /k
        # keeps the console open if ComfyUI stops, like the .bat's "pause",
        # so its error stays readable; minimized, like Nomad Studio's own
        # console, so it does not cover the wizard.
        root = Path(info["path"])
        args = ["cmd.exe", "/c", "start", "", "/min", "cmd.exe", "/k", str(root / "python_embeded" / "python.exe"),
                "-s", str(root / "ComfyUI" / "main.py"), "--windows-standalone-build", "--disable-auto-launch"]
        if listen:
            args += ["--listen", "0.0.0.0"]
        _spawn(args, cwd=info["path"])
        return {"ok": True, "started": info["path"], "listening": listen}
    launcher = info["launcher"]
    if launcher.lower().endswith(".bat"):
        _spawn(["cmd.exe", "/c", "start", "", launcher], cwd=info["path"])
    else:
        _spawn([launcher], cwd=info["path"])
    # Asked for the network but this install cannot be told from here.
    return {"ok": True, "started": launcher, "listening": False, "listenUnavailable": bool(listen)}


def start_lmstudio() -> dict[str, Any]:
    info = find_lmstudio()
    if not info:
        return {"ok": False, "error": "No LM Studio installation was found on this computer"}
    # `lms server start` brings the API up without opening the window.
    if info.get("cli"):
        try:
            subprocess.run([info["cli"], "server", "start"], capture_output=True, timeout=30,  # noqa: S603
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            return {"ok": True, "started": info["cli"]}
        except Exception:  # noqa: BLE001 — fall back to opening the app
            logger.debug("lms server start failed", exc_info=True)
    if info.get("launcher"):
        _spawn([info["launcher"]])
        return {"ok": True, "started": info["launcher"], "needsServerToggle": True}
    return {"ok": False, "error": "LM Studio is installed but could not be started"}


# ── Installing ComfyUI portable ─────────────────────────────────────────────


def _extractor() -> list[str] | None:
    if WINDOWS_TAR.is_file():
        return [str(WINDOWS_TAR), "-xf"]
    if SEVEN_ZIP.is_file():
        return [str(SEVEN_ZIP), "x", "-y"]
    return None


def pick_asset(assets: list[dict[str, Any]], vendor: str) -> dict[str, Any] | None:
    """The portable build for this machine's graphics card."""
    wanted = {"nvidia": "nvidia", "amd": "amd", "intel": "intel"}.get(vendor, "nvidia")
    named = [a for a in assets if a.get("name", "").endswith(".7z") and "windows_portable" in a.get("name", "")]
    exact = [a for a in named if wanted in a["name"] and "cu126" not in a["name"]]
    return (exact or [a for a in named if wanted in a["name"]] or named or [None])[0]


_job: dict[str, Any] | None = None
_job_lock = threading.Lock()


def get_job() -> dict[str, Any] | None:
    with _job_lock:
        return dict(_job) if _job else None


def _set(**fields: Any) -> None:
    with _job_lock:
        if _job is not None:
            _job.update(fields)


def _download_installer(url: str, target_dir: Path, fallback_name: str) -> Path:
    """Download a Windows installer into *target_dir*, reporting progress to
    the current job. Its name comes from the URL the redirects end at."""
    target_dir.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": "NomadStudio"})
    with urllib.request.urlopen(request, timeout=60) as response:
        name = os.path.basename(response.url.split("?", 1)[0]) or fallback_name
        if not name.lower().endswith(".exe"):
            raise ValueError("That download is not a Windows installer")
        total = int(response.headers.get("Content-Length") or 0)
        _set(total=total, asset=name)
        installer = target_dir / name
        partial = installer.with_suffix(".part")
        with partial.open("wb") as out:
            done = 0
            while True:
                chunk = response.read(1 << 20)
                if not chunk:
                    break
                out.write(chunk)
                done += len(chunk)
                _set(done=done)
        os.replace(partial, installer)
    return installer


def _new_job(app: str) -> None:
    global _job
    with _job_lock:
        if _job and _job.get("state") == "running":
            raise ValueError("Something else is already being installed")
        _job = {"id": uuid.uuid4().hex[:12], "app": app, "state": "running", "phase": "download",
                "done": 0, "total": 0, "error": "", "result": None}


def start_install_vcredist() -> dict[str, Any]:
    """Download Microsoft's Visual C++ runtime installer and run it. It needs
    administrator rights, so Windows shows its permission prompt; we wait
    until the runtime's DLLs are there (or the user said no)."""
    if not sys.platform.startswith("win"):
        raise ValueError("The Visual C++ runtime is only needed on Windows")
    _new_job("vcredist")

    def work() -> None:
        try:
            installer = _download_installer(VCREDIST_URL, Path(tempfile.gettempdir()) / "NomadStudio",
                                            "vc_redist.x64.exe")
            _set(phase="installer")
            try:
                # ShellExecute, not Popen: only it raises the elevation prompt
                # an installer that requires administrator rights needs.
                os.startfile(str(installer), "open", "/install /passive /norestart")  # noqa: S606
            except OSError as exc:
                if getattr(exc, "winerror", None) == 1223:  # ERROR_CANCELLED: "No" in the prompt
                    raise ValueError("Windows did not get permission to install the Visual C++ runtime") from exc
                raise
            deadline = time.monotonic() + VCREDIST_WAIT_SECONDS
            while not vc_runtime_installed():
                if time.monotonic() > deadline:
                    raise ValueError("The Visual C++ runtime installer did not finish")
                time.sleep(2)
            _set(state="done", phase="ready", result={"installer": str(installer)})
            logger.info("Visual C++ runtime installed")
        except Exception as exc:  # noqa: BLE001 — shown in the wizard
            logger.exception("installing the Visual C++ runtime failed")
            _set(state="error", error=str(exc))

    threading.Thread(target=work, daemon=True, name="install-vcredist").start()
    return get_job() or {}


def start_install_lmstudio(target_dir: Path) -> dict[str, Any]:
    """Download LM Studio's own installer and open it. It installs itself with
    its own window, so this gets the file and hands over — unlike ComfyUI,
    which is a portable folder we can unpack."""
    if not sys.platform.startswith("win"):
        raise ValueError("Installing LM Studio from here is only available on Windows for now")
    _new_job("lmstudio")

    def work() -> None:
        try:
            installer = _download_installer(LMSTUDIO_INSTALLER_URL, target_dir, "LM-Studio-Setup.exe")
            _set(phase="installer")
            # Wait for the user to finish it: LM Studio.exe is among the first
            # files it copies, and starting it before the installer was done
            # crashed it ("Cannot find module ...\index.js", clean Windows VM).
            try:
                _spawn([str(installer)]).wait(timeout=LMSTUDIO_INSTALLER_WAIT_SECONDS)
            except subprocess.TimeoutExpired:
                logger.info("LM Studio installer still open after %ss; carrying on", LMSTUDIO_INSTALLER_WAIT_SECONDS)
            _set(state="done", phase="ready", result={"installer": str(installer), "needsUserToFinish": True})
            logger.info("LM Studio installer downloaded to %s and started", installer)
        except Exception as exc:  # noqa: BLE001 — shown in the wizard
            logger.exception("downloading LM Studio failed")
            _set(state="error", error=str(exc))

    threading.Thread(target=work, daemon=True, name="install-lmstudio").start()
    return get_job() or {}


def start_install_comfyui(target_dir: Path) -> dict[str, Any]:
    """Download the official portable build and unpack it into *target_dir*.
    Runs in the background; follow it with get_job()."""
    global _job
    if not sys.platform.startswith("win"):
        raise ValueError("Installing ComfyUI from here is only available on Windows for now")
    extractor = _extractor()
    if extractor is None:
        raise ValueError("No program to unpack the download was found")
    with _job_lock:
        if _job and _job.get("state") == "running":
            raise ValueError("Something else is already being installed")
        _job = {"id": uuid.uuid4().hex[:12], "app": "comfy", "state": "running", "phase": "asset", "done": 0,
                "total": 0, "error": "", "result": None}

    def work() -> None:
        try:
            request = urllib.request.Request(COMFY_RELEASES_API, headers={"Accept": "application/vnd.github+json",
                                                                          "User-Agent": "NomadStudio"})
            with urllib.request.urlopen(request, timeout=30) as response:
                release = json.loads(response.read().decode("utf-8"))
            asset = pick_asset(release.get("assets") or [], gpu_vendor())
            if asset is None:
                raise ValueError("That ComfyUI release has no Windows portable build")
            size = int(asset.get("size") or 0)
            target_dir.mkdir(parents=True, exist_ok=True)
            free = shutil.disk_usage(target_dir).free
            if free < max(MIN_FREE_BYTES, size * 4):
                raise ValueError(f"Not enough free space: {free // 2**30} GB available, about "
                                 f"{max(MIN_FREE_BYTES, size * 4) // 2**30} GB needed")

            archive = target_dir / asset["name"]
            partial = archive.with_suffix(archive.suffix + ".part")
            _set(phase="download", total=size, version=release.get("tag_name"), asset=asset["name"])
            with urllib.request.urlopen(asset["browser_download_url"], timeout=60) as response, partial.open("wb") as out:
                done = 0
                while True:
                    chunk = response.read(1 << 20)
                    if not chunk:
                        break
                    out.write(chunk)
                    done += len(chunk)
                    _set(done=done)
            os.replace(partial, archive)

            _set(phase="extract", done=0, total=0)
            result = subprocess.run([*extractor, str(archive)], cwd=str(target_dir),  # noqa: S603
                                    capture_output=True, text=True,
                                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            if result.returncode != 0:
                raise ValueError("The download could not be unpacked: " + (result.stderr or "")[:200])
            archive.unlink(missing_ok=True)

            installed = _comfy_in(target_dir) or find_comfyui() or {}
            if not installed.get("launcher"):
                raise ValueError("Unpacked, but no ComfyUI launcher was found in " + str(target_dir))
            _set(state="done", phase="ready", result=installed)
            logger.info("ComfyUI portable installed at %s", installed.get("path"))
        except Exception as exc:  # noqa: BLE001 — shown in the wizard
            logger.exception("installing ComfyUI failed")
            _set(state="error", error=str(exc))

    threading.Thread(target=work, daemon=True, name="install-comfyui").start()
    return get_job() or {}
