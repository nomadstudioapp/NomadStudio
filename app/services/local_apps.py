"""Help a brand-new user get ComfyUI and LM Studio, which Nomad Studio needs
but does not include.

Until now the wizard assumed both existed somewhere and were merely switched
off. Someone starting from zero was told "start ComfyUI" with no way forward.
This module covers the three cases:

- **installed but not running** — find it on disk and start it;
- **not installed** — download the official ComfyUI portable build and unpack
  it (LM Studio is an installer with its own window: we send the user to its
  download page). On Linux, where ComfyUI publishes no portable build, we
  assemble the same layout ourselves (see "Installing ComfyUI on Linux");
- **no suitable GPU** — say so before they download 2 GB for nothing.

Nothing here runs from another computer's browser: the routes that start or
install anything are marked local_only.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any

import logging

from app.services.http_client import download_url

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

# Linux: ComfyUI publishes no portable build there, so the wizard assembles one
# with the Windows layout — ComfyUI/ (the release source), python_embeded/ (a
# python-build-standalone CPython, the same family Nomad Studio ships) and a
# launcher, run_nomad.sh. No git, no python3-venv and no sudo needed, which a
# fresh Ubuntu does not have (found on an Ubuntu 26.04 tower, 2026-10-12).
COMFY_LINUX_DIR = "ComfyUI_linux_portable"
LINUX_LAUNCHER = "run_nomad.sh"
LINUX_PYTHON_URL = ("https://github.com/astral-sh/python-build-standalone/releases/download/20250409/"
                    "cpython-3.13.3%2B20250409-x86_64-unknown-linux-gnu-install_only.tar.gz")
LINUX_PYTHON_SHA256 = "1314ad7809df183542d5110fda25847ae69ea46c53e3b290fa9c400c91e3a722"
TORCH_INDEX = {
    "cuda": "https://download.pytorch.org/whl/cu128",
    "rocm": "https://download.pytorch.org/whl/rocm6.4",
    "cpu": "https://download.pytorch.org/whl/cpu",
}
# Room needed for ComfyUI + its Python + PyTorch, per PyTorch build.
LINUX_FREE_BYTES = {"cuda": 14 * 2**30, "rocm": 24 * 2**30, "cpu": 6 * 2**30}


# ── This machine ────────────────────────────────────────────────────────────

_gpus: list[str] | None = None


def _powershell(script: str, timeout: float) -> subprocess.CompletedProcess:
    """Run a PowerShell command and read what it prints as UTF-8.

    PowerShell writes in the console code page (850 on a Spanish Windows),
    and the launcher sets PYTHONUTF8=1, so Python read it as UTF-8: one
    accented letter ("Vídeo de Microsoft Hyper-V", a user called "Begoña")
    made the whole output None. Seen recording the Spanish install: the
    wizard said there was no NVIDIA card on an RTX 4060 Ti."""
    return subprocess.run(  # noqa: S603,S607 — our own fixed commands
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command",
         "[Console]::OutputEncoding = [Text.Encoding]::UTF8; " + script],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def gpu_names() -> list[str]:
    """Graphics cards in this computer, read without ComfyUI's help so the
    wizard can warn before a 2 GB download. Empty list when unknown."""
    global _gpus
    if _gpus is not None:
        return _gpus
    names: list[str] = []
    if sys.platform.startswith("win"):
        try:
            out = _powershell("Get-CimInstance Win32_VideoController | Select-Object -ExpandProperty Name", 45)
            names = [line.strip() for line in (out.stdout or "").splitlines() if line.strip()]
        except Exception:  # noqa: BLE001 — never block the wizard
            logger.debug("could not read the GPU list", exc_info=True)
    elif sys.platform.startswith("linux"):
        names = _linux_gpu_names()
    # Kept only when it worked, so a slow or failed first try is not
    # remembered as "no graphics card" for the whole session.
    if names:
        _gpus = names
    return names


_PCI_VENDORS = {"0x10de": "NVIDIA", "0x1002": "AMD Radeon", "0x8086": "Intel"}


WSL_NVIDIA_SMI = Path("/usr/lib/wsl/lib/nvidia-smi")


def _linux_gpu_names() -> list[str]:
    """Display controllers from lspci (names), or from sysfs (vendor only)
    where pciutils is missing. Under WSL2 the NVIDIA card is not a PCI device
    of the Linux side at all: Windows' driver exposes it through
    /usr/lib/wsl/lib (libcuda, nvidia-smi), so ask nvidia-smi there."""
    names: list[str] = []
    if WSL_NVIDIA_SMI.exists():
        try:
            out = subprocess.run([str(WSL_NVIDIA_SMI), "--query-gpu=name", "--format=csv,noheader"],  # noqa: S603
                                 capture_output=True, text=True, timeout=15).stdout
            names = [line.strip() for line in out.splitlines() if line.strip()]
        except Exception:  # noqa: BLE001 — lspci below
            names = []
        if names:
            return names
    try:
        out = subprocess.run(["lspci", "-mm"], capture_output=True, text=True, timeout=10).stdout  # noqa: S603,S607
        for line in out.splitlines():
            if re.search(r'"(VGA compatible controller|3D controller|Display controller)"', line):
                parts = shlex.split(line)
                if len(parts) >= 4:
                    names.append(f"{parts[2]} {parts[3]}")
    except Exception:  # noqa: BLE001 — sysfs below
        pass
    if not names:
        try:
            for dev in Path("/sys/bus/pci/devices").iterdir():
                if (dev / "class").read_text().startswith("0x03"):
                    vendor = (dev / "vendor").read_text().strip()
                    names.append(_PCI_VENDORS.get(vendor, vendor) + " graphics")
        except OSError:
            pass
    return names


def gpu_vendor() -> str:
    """"nvidia" | "amd" | "intel" | "" — which portable build to offer."""
    names = " ".join(gpu_names()).lower()
    for vendor, needles in (("nvidia", ("nvidia", "geforce", "quadro", "rtx", "gtx")),
                            ("amd", ("amd", "radeon")),
                            ("intel", ("intel", "arc"))):
        if any(n in names for n in needles):
            return vendor
    return ""


def _amd_gfx_versions() -> list[int]:
    """ROCm's gfx target of each AMD GPU (e.g. 110000 = gfx1100), from the
    amdgpu kernel driver. Empty when the driver exposes none."""
    found = []
    try:
        for props in Path("/sys/class/kfd/kfd/topology/nodes").glob("*/properties"):
            m = re.search(r"^gfx_target_version (\d+)", props.read_text(), re.M)
            if m and int(m.group(1)):
                found.append(int(m.group(1)))
    except OSError:
        pass
    return found


def linux_torch_backend() -> str:
    """Which PyTorch to install with ComfyUI on Linux: "cuda" (NVIDIA with its
    driver), "rocm" (AMD from RDNA 2 on, gfx1030+, what current ROCm runs) or
    "cpu" — slow, but it works, and the wizard says so first."""
    vendor = gpu_vendor()
    if vendor == "nvidia" and (Path("/proc/driver/nvidia/version").exists() or shutil.which("nvidia-smi")
                               or WSL_NVIDIA_SMI.exists()):
        return "cuda"
    if vendor == "amd" and any(v >= 100300 for v in _amd_gfx_versions()):
        return "rocm"
    return "cpu"


def vc_runtime_installed() -> bool:
    """Whether the Visual C++ runtime PyTorch needs is on this machine: the
    DLLs themselves, which is what ComfyUI fails to load without it."""
    if not sys.platform.startswith("win"):
        return True
    system32 = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
    return all((system32 / dll).is_file() for dll in _VC_RUNTIME_DLLS)


# ── Finding what is already installed ───────────────────────────────────────


def _installed_path_file() -> Path:
    from app import paths
    return paths.DATA_DIR / "local-apps.json"


def _remember_install(path: str, app: str = "comfy") -> None:
    """Where the wizard installed ComfyUI (or LM Studio on Linux), so it is
    found again even in a folder the search below does not look in (the user
    may choose any)."""
    try:
        f = _installed_path_file()
        data = json.loads(f.read_text(encoding="utf-8")) if f.is_file() else {}
        data[app] = path
        f.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except (OSError, ValueError):
        logger.debug("could not remember the %s install path", app, exc_info=True)


def _remembered_installs(app: str = "comfy") -> list[Path]:
    try:
        data = json.loads(_installed_path_file().read_text(encoding="utf-8"))
        return [Path(data[app])] if data.get(app) else []
    except (OSError, ValueError, KeyError, TypeError):
        return []


def _comfy_candidates() -> list[Path]:
    home = Path.home()
    roots = [home, home / "Documents", home / "Desktop", home / "Downloads"]
    roots += [Path(f"{letter}:\\") for letter in "CDEFG" if Path(f"{letter}:\\").exists()]
    names = ("ComfyUI_windows_portable", COMFY_LINUX_DIR, "ComfyUI", "comfyui")
    return _remembered_installs() + [root / name for root in roots for name in names]


def _comfy_in(root: Path) -> dict[str, Any] | None:
    """A portable ComfyUI directly inside *root* (where we just unpacked it)."""
    for path in [root, *(p for p in root.iterdir() if p.is_dir())] if root.is_dir() else []:
        for bat in _COMFY_LAUNCHERS:
            if (path / bat).is_file():
                return {"kind": "portable", "path": str(path), "launcher": str(path / bat)}
    return None


# Preference order when more than one is installed. The portable build is the
# one Nomad Studio works best with: it is the one ComfyUI publishes for this,
# its models folder is a plain directory we can point at, and it takes
# --listen for a server on the network. The desktop app manages its own
# install and is harder to steer, and a git clone we can find but not start.
_COMFY_PREFERENCE = ("portable", "desktop", "source")
_COMFY_LAUNCHERS = ("run_nvidia_gpu.bat", "run_cpu.bat", "run_amd_gpu.bat", "run_intel_gpu.bat", LINUX_LAUNCHER)


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
    if sys.platform.startswith("linux"):
        return _find_lmstudio_linux()
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


# LM Studio for Linux is one AppImage file: the wizard downloads it to
# ~/Applications (the usual place for them), makes it executable and adds it
# to the applications menu. Its .deb installs to /opt and puts lm-studio on
# the PATH.
LMSTUDIO_LINUX_URL = "https://lmstudio.ai/download/latest/linux/{arch}"
LMSTUDIO_DESKTOP_FILE = "nomad-lm-studio.desktop"


def _lmstudio_appimages() -> list[Path]:
    home = Path.home()
    found = [p for p in _remembered_installs("lmstudio") if p.is_file()]
    for folder in (home / "Applications", home / "Downloads", home / "Desktop", home):
        try:
            found += sorted(folder.glob("LM[-_ ]Studio*.AppImage"), key=lambda p: p.stat().st_mtime, reverse=True)
        except OSError:
            pass
    return found


def _find_lmstudio_linux() -> dict[str, Any] | None:
    cli = Path.home() / ".lmstudio" / "bin" / "lms"
    launcher = next((p for p in _lmstudio_appimages() if os.access(p, os.X_OK)), None)
    if launcher is None:
        for candidate in (Path("/opt/LM Studio/lm-studio"), Path("/opt/lm-studio/lm-studio")):
            if candidate.is_file():
                launcher = candidate
                break
    if launcher is None and shutil.which("lm-studio"):
        launcher = Path(shutil.which("lm-studio"))
    if launcher is None and not cli.is_file():
        return None
    return {"kind": "app", "path": str(launcher or cli), "launcher": str(launcher or ""),
            "cli": str(cli) if cli.is_file() else ""}


def _lmstudio_linux_arch() -> str | None:
    if not sys.platform.startswith("linux"):
        return None
    return {"x86_64": "x64", "amd64": "x64", "aarch64": "arm64", "arm64": "arm64"}.get(platform.machine().lower())


def _appimage_command(appimage: Path) -> list[str]:
    """How to start an AppImage here. Without libfuse2 (not installed by
    default on recent Ubuntu) it can still unpack itself and run; where
    AppArmor blocks the user namespaces Electron's sandbox needs (Ubuntu 24.04
    and later), it runs without that sandbox, as LM Studio's own docs say."""
    cmd = [str(appimage)]
    try:
        restricted = Path("/proc/sys/kernel/apparmor_restrict_unprivileged_userns").read_text().strip() == "1"
    except OSError:
        restricted = False
    if restricted:
        cmd.append("--no-sandbox")
    return cmd


def _appimage_env() -> dict[str, str] | None:
    has_fuse2 = any(Path(d, "libfuse.so.2").exists() for d in
                    ("/usr/lib/x86_64-linux-gnu", "/usr/lib/aarch64-linux-gnu", "/usr/lib64", "/usr/lib", "/lib/x86_64-linux-gnu"))
    return None if has_fuse2 else {**os.environ, "APPIMAGE_EXTRACT_AND_RUN": "1"}


def _add_to_applications_menu(appimage: Path) -> None:
    """A menu entry, so LM Studio can be opened again like any other app."""
    try:
        apps = Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share"))) / "applications"
        apps.mkdir(parents=True, exist_ok=True)
        cmd = " ".join(shlex.quote(part) for part in _appimage_command(appimage))
        if _appimage_env() is not None:
            cmd = "env APPIMAGE_EXTRACT_AND_RUN=1 " + cmd
        # Its icon, taken out of the AppImage (any AppImage can unpack single
        # files of itself, with or without FUSE). The lm-studio.png at its
        # root is only a link to this one.
        icon = "lm-studio"
        icons = apps.parent / "icons"
        inside = "usr/share/icons/hicolor/512x512/apps/lm-studio.png"
        with tempfile.TemporaryDirectory() as tmp:
            subprocess.run([str(appimage), "--appimage-extract", inside], cwd=tmp,  # noqa: S603
                           capture_output=True, timeout=60)
            png = Path(tmp) / "squashfs-root" / inside
            if png.is_file():
                icons.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(png, icons / "lm-studio.png")
                icon = str(icons / "lm-studio.png")
        (apps / LMSTUDIO_DESKTOP_FILE).write_text(
            "[Desktop Entry]\nType=Application\nName=LM Studio\n"
            f"Exec={cmd} %U\nIcon={icon}\nTerminal=false\nCategories=Development;Utility;\n"
            "StartupWMClass=ai.elementlabs.lmstudio\n", encoding="utf-8")
    except (OSError, subprocess.SubprocessError):
        logger.debug("could not add LM Studio to the applications menu", exc_info=True)


def state() -> dict[str, Any]:
    """What the wizard needs to decide what to offer."""
    vendor = gpu_vendor()
    comfy = find_comfyui()
    return {
        "gpus": gpu_names(),
        "gpuVendor": vendor,
        "canInstallComfy": (sys.platform.startswith("win") and _extractor() is not None) or _can_install_linux(),
        "platform": "windows" if sys.platform.startswith("win") else ("macos" if sys.platform == "darwin" else "linux"),
        # Linux only: the PyTorch the install would bring (cuda | rocm | cpu).
        "comfyBackend": linux_torch_backend() if sys.platform.startswith("linux") else "",
        # LM Studio: its installer on Windows, its AppImage on Linux; on a Mac
        # the wizard links to its download page (start_install_lmstudio refuses).
        "canInstallLms": sys.platform.startswith("win") or _lmstudio_linux_arch() is not None,
        "suggestedLmsDir": str(Path.home() / "Applications") if sys.platform.startswith("linux") else str(Path.home()),
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


def _spawn(args: list[str], cwd: str | None = None, env: dict[str, str] | None = None) -> subprocess.Popen:
    return subprocess.Popen(  # noqa: S603 — paths we found ourselves, local app
        args, cwd=cwd, close_fds=True, env=env,
        start_new_session=not sys.platform.startswith("win"),
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
    py = root / "python_embeded" / ("python.exe" if sys.platform.startswith("win") else "bin/python3")
    return py.is_file() and (root / "ComfyUI" / "main.py").is_file()


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
    if Path(info["launcher"]).name == LINUX_LAUNCHER:
        # Our own launcher (it adds --cpu itself when that is the build).
        # Detached from Nomad Studio, output to a log next to it so an error
        # stays readable — there is no console window on Linux.
        args = ["/bin/sh", info["launcher"]] + (["--listen", "0.0.0.0"] if listen else [])
        log = open(Path(info["path"]) / "comfyui.log", "ab")  # noqa: SIM115 — handed to the child
        subprocess.Popen(args, cwd=info["path"], stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,  # noqa: S603
                         start_new_session=True, close_fds=True)
        log.close()
        return {"ok": True, "started": info["path"], "listening": listen}
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


def _python_processes_under(folder: Path) -> list[int] | None:
    """Memory in use (bytes) of each python.exe running from inside *folder*,
    or None where we cannot tell (not Windows, or the lookup failed). Plain
    Win32 calls through ctypes: the portable build has no psutil."""
    if sys.platform.startswith("linux"):
        return _linux_processes_under(folder)
    if not sys.platform.startswith("win"):
        return None
    try:
        import ctypes
        from ctypes import wintypes

        k32 = ctypes.WinDLL("kernel32", use_last_error=True)

        class Entry(ctypes.Structure):
            _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                        ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.c_size_t),
                        ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                        ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", ctypes.c_long),
                        ("dwFlags", wintypes.DWORD), ("szExeFile", ctypes.c_wchar * 260)]

        class Counters(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD)] + [
                (n, ctypes.c_size_t) for n in ("PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage",
                                               "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage",
                                               "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage")]

        k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        k32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
        k32.Process32FirstW.argtypes = k32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(Entry)]
        k32.OpenProcess.restype = wintypes.HANDLE
        k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        k32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                                                   ctypes.POINTER(wintypes.DWORD)]
        k32.K32GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
        k32.CloseHandle.argtypes = [wintypes.HANDLE]

        snap = k32.CreateToolhelp32Snapshot(0x2, 0)  # TH32CS_SNAPPROCESS
        if not snap or snap == wintypes.HANDLE(-1).value:
            return None
        prefix = str(folder.resolve()).lower().rstrip("\\") + "\\"
        found: list[int] = []
        try:
            entry = Entry()
            entry.dwSize = ctypes.sizeof(Entry)
            more = k32.Process32FirstW(snap, ctypes.byref(entry))
            while more:
                if entry.szExeFile.lower() == "python.exe":
                    h = k32.OpenProcess(0x1000, False, entry.th32ProcessID)  # QUERY_LIMITED_INFORMATION
                    if h:
                        try:
                            buf = ctypes.create_unicode_buffer(1024)
                            size = wintypes.DWORD(1024)
                            if k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)) \
                                    and buf.value.lower().startswith(prefix):
                                mem = Counters()
                                mem.cb = ctypes.sizeof(Counters)
                                ok = k32.K32GetProcessMemoryInfo(h, ctypes.byref(mem), mem.cb)
                                found.append(int(mem.WorkingSetSize) if ok else 0)
                        finally:
                            k32.CloseHandle(h)
                more = k32.Process32NextW(snap, ctypes.byref(entry))
        finally:
            k32.CloseHandle(snap)
        return found
    except Exception:  # noqa: BLE001 — only a progress hint
        logger.debug("process lookup failed", exc_info=True)
        return None


def _linux_processes_under(folder: Path) -> list[int] | None:
    """Resident memory (bytes) of each process whose program lives inside
    *folder*, read from /proc."""
    try:
        prefix = str(folder.resolve()).rstrip("/") + "/"
        page = os.sysconf("SC_PAGE_SIZE")
        found = []
        for proc in Path("/proc").iterdir():
            if not proc.name.isdigit():
                continue
            try:
                if os.readlink(proc / "exe").startswith(prefix):
                    found.append(int((proc / "statm").read_text().split()[1]) * page)
            except OSError:
                continue
        return found
    except Exception:  # noqa: BLE001 — only a progress hint
        return None


def comfy_progress() -> dict[str, Any]:
    """Whether the portable ComfyUI we started is still running, and how much
    it has loaded. Its first start on a new install takes minutes with nothing
    to see, which looked broken: the wizard shows this while it waits, and
    can tell at once when ComfyUI closed instead of waiting the full time."""
    info = find_comfyui()
    if not info or info.get("kind") != "portable":
        return {"running": None}
    procs = _python_processes_under(Path(info["path"]))
    if procs is None:
        return {"running": None}
    return {"running": bool(procs), "memMb": sum(procs) // (1024 * 1024)}


def start_lmstudio(server_only: bool = False) -> dict[str, Any]:
    """Start LM Studio's API. *server_only*: just try `lms server start` again
    (the wizard does this while the user goes through LM Studio's welcome),
    never open the window."""
    info = find_lmstudio()
    if not info:
        return {"ok": False, "error": "No LM Studio installation was found on this computer"}
    if server_only:
        if not info.get("cli"):
            return {"ok": False}
        try:
            res = subprocess.run([info["cli"], "server", "start"], capture_output=True, timeout=30,  # noqa: S603
                                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            return {"ok": res.returncode == 0}
        except Exception:  # noqa: BLE001 — the wizard tries again
            return {"ok": False}
    # `lms server start` brings the API up without opening the window.
    if info.get("cli"):
        try:
            res = subprocess.run([info["cli"], "server", "start"], capture_output=True, timeout=30,  # noqa: S603
                                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            # It fails (non-zero) while LM Studio's own first-run welcome is not
            # done: then open the window below so the user sees it.
            if res.returncode == 0:
                return {"ok": True, "started": info["cli"]}
            logger.info("lms server start returned %s; opening LM Studio instead", res.returncode)
        except Exception:  # noqa: BLE001 — fall back to opening the app
            logger.debug("lms server start failed", exc_info=True)
    if info.get("launcher"):
        if info["launcher"].endswith(".AppImage"):
            _spawn(_appimage_command(Path(info["launcher"])), env=_appimage_env())
        else:
            _spawn([info["launcher"]])
        return {"ok": True, "started": info["launcher"], "needsServerToggle": True}
    return {"ok": False, "error": "LM Studio is installed but could not be started"}


# ── Shortcuts to Nomad Studio itself ────────────────────────────────────────
# A .lnk stores an absolute path, so none can ship inside the portable ZIP
# (it is unpacked anywhere). Created here instead, at the end of the setup
# wizard, pointing at wherever this copy lives: the user's own Desktop and
# Start menu, which need no administrator rights. Updates only swap app\,
# so NomadStudio.bat — what the shortcut opens — stays where it was.

def _portable_launcher() -> Path | None:
    from app import paths
    if not sys.platform.startswith("win") or not paths.IS_PORTABLE:
        return None
    bat = paths.REPO_DIR.parent / "NomadStudio.bat"
    return bat if bat.is_file() else None


def can_create_shortcuts() -> bool:
    return _portable_launcher() is not None


def create_shortcuts(desktop: bool = True, start_menu: bool = True) -> dict[str, Any]:
    bat = _portable_launcher()
    if bat is None:
        return {"ok": False, "error": "Shortcuts are only made for the Windows portable build"}
    from app import paths
    icon = paths.REPO_DIR / "launcher" / "nomad.ico"
    targets = []
    if desktop:
        targets.append("[Environment]::GetFolderPath('Desktop')")
    if start_menu:
        targets.append("[Environment]::GetFolderPath('Programs')")
    if not targets:
        return {"ok": True, "created": []}

    def ps(s: str) -> str:  # PowerShell single-quoted literal
        return "'" + str(s).replace("'", "''") + "'"

    script = (
        "$ws = New-Object -ComObject WScript.Shell; $made = @(); "
        f"foreach ($dir in @({', '.join(targets)})) {{ "
        "  $lnk = $ws.CreateShortcut((Join-Path $dir 'Nomad Studio.lnk')); "
        f"  $lnk.TargetPath = {ps(bat)}; $lnk.WorkingDirectory = {ps(bat.parent)}; "
        "  $lnk.WindowStyle = 7; $lnk.Description = 'Nomad Studio'; "
        + (f"  $lnk.IconLocation = {ps(str(icon) + ',0')}; " if icon.is_file() else "")
        + "  $lnk.Save(); $made += $lnk.FullName }; $made -join \"`n\""
    )
    try:
        out = _powershell(script, 30)
    except Exception as exc:  # noqa: BLE001 — shown in the wizard
        return {"ok": False, "error": str(exc)}
    if out.returncode != 0:
        return {"ok": False, "error": (out.stderr or out.stdout or "").strip()[:300]}
    created = [line for line in (out.stdout or "").splitlines() if line.strip()]
    logger.info("shortcuts created: %s", created)
    return {"ok": True, "created": created}


# ── Starting them with Nomad Studio ─────────────────────────────────────────
# After a reboot a new user opened Nomad Studio and found ComfyUI "off" with
# no idea how to start it: only the setup wizard had a Start button. Now the
# server starts the ones installed on this computer by itself (setting
# autoStartApps, on by default) and tracks how it went for the start screen
# and the settings panel.

DEFAULT_COMFY_URL = "http://127.0.0.1:8188"
DEFAULT_LMSTUDIO_URL = "http://127.0.0.1:1234"
COMFY_START_WAIT = 600     # first start of a fresh portable install: 3-9 minutes
LMSTUDIO_START_WAIT = 120

_autostart: dict[str, str] = {"comfy": "idle", "lmstudio": "idle"}
_autostart_lock = threading.Lock()


def _is_local(url: str) -> bool:
    from urllib.parse import urlparse
    return (urlparse(url).hostname or "").lower() in {"127.0.0.1", "localhost", "::1"}


def _answers(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=3):  # noqa: S310 — local service
            return True
    except urllib.error.HTTPError:
        return True  # it answered, even if with an error
    except Exception:  # noqa: BLE001 — not running
        return False


def _probe(app: str, settings: dict[str, Any]) -> tuple[str, str]:
    """(base url, url to probe) for this app from the saved settings."""
    if app == "comfy":
        base = str(settings.get("comfyApiUrl") or DEFAULT_COMFY_URL).strip().rstrip("/")
        return base, base + "/system_stats"
    base = str(settings.get("lmStudioApiUrl") or DEFAULT_LMSTUDIO_URL).strip().rstrip("/")
    root = base.split("/v1")[0].split("/api/")[0]
    return root, root + "/v1/models"


def autostart_state() -> dict[str, str]:
    with _autostart_lock:
        state = dict(_autostart)
    # "idle": autostart never ran (e.g. the server started before the setup
    # wizard was done). Say whether there is anything to start at all, so the
    # settings panel does not offer "Start LM Studio" where it is not installed.
    for app, find in (("comfy", find_comfyui), ("lmstudio", find_lmstudio)):
        if state.get(app) == "idle" and find() is None:
            state[app] = "notInstalled"
    return state


def _set_state(app: str, value: str) -> None:
    with _autostart_lock:
        _autostart[app] = value


def start_and_wait(app: str, settings: dict[str, Any]) -> str:
    """Start one app if it is installed here and not answering; wait until it
    answers. Returns the final state: running, remote, notInstalled, needsVcRuntime
    or failed."""
    base, probe = _probe(app, settings)
    if not _is_local(base):
        _set_state(app, "remote")
        return "remote"
    if _answers(probe):
        _set_state(app, "running")
        return "running"
    if app == "comfy":
        if not find_comfyui():
            _set_state(app, "notInstalled")
            return "notInstalled"
        _set_state(app, "starting")
        res = start_comfyui(listen=bool(settings.get("comfyListen")))
        wait = COMFY_START_WAIT
    else:
        if not find_lmstudio():
            _set_state(app, "notInstalled")
            return "notInstalled"
        _set_state(app, "starting")
        res = start_lmstudio()
        wait = LMSTUDIO_START_WAIT
    if not res.get("ok"):
        state = "needsVcRuntime" if res.get("needsVcRuntime") else "failed"
        _set_state(app, state)
        logger.warning("autostart %s: %s", app, res.get("error"))
        return state
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        if _answers(probe):
            _set_state(app, "running")
            logger.info("autostart: %s is running", app)
            return "running"
        time.sleep(3)
    # LM Studio opened as a window (its server did not start): most likely its
    # own welcome is waiting for the user.
    if app == "lmstudio" and res.get("needsServerToggle"):
        _set_state(app, "needsUser")
        return "needsUser"
    _set_state(app, "failed")
    logger.warning("autostart: %s did not answer within %ss", app, wait)
    return "failed"


def autostart_in_background(settings: dict[str, Any]) -> None:
    """Called once when the server starts (app.py)."""
    if settings.get("autoStartApps") is False:
        _set_state("comfy", "disabled")
        _set_state("lmstudio", "disabled")
        return
    for app in ("comfy", "lmstudio"):
        threading.Thread(target=start_and_wait, args=(app, settings), daemon=True,
                         name=f"autostart-{app}").start()


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
    request = urllib.request.Request(download_url(url), headers={"User-Agent": "NomadStudio"})
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
    if _lmstudio_linux_arch():
        return _start_install_lmstudio_linux(target_dir)
    if not sys.platform.startswith("win"):
        raise ValueError("Installing LM Studio from here is only available on Windows and Linux for now")
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


def _start_install_lmstudio_linux(target_dir: Path) -> dict[str, Any]:
    """Download LM Studio's AppImage into *target_dir*, make it executable and
    add it to the applications menu. No installer and no password: the
    wizard then opens it like an installed LM Studio (start_lmstudio)."""
    _new_job("lmstudio")

    def work() -> None:
        try:
            target_dir.mkdir(parents=True, exist_ok=True)
            url = LMSTUDIO_LINUX_URL.format(arch=_lmstudio_linux_arch())
            request = urllib.request.Request(download_url(url), headers={"User-Agent": "NomadStudio"})
            with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310
                name = os.path.basename(response.url.split("?", 1)[0])
                if not name.endswith(".AppImage"):
                    raise ValueError("That download is not LM Studio's AppImage")
                _set(total=int(response.headers.get("Content-Length") or 0), asset=name)
                appimage = target_dir / name
                partial = appimage.with_name(name + ".part")
                with partial.open("wb") as out:
                    done = 0
                    while True:
                        chunk = response.read(1 << 20)
                        if not chunk:
                            break
                        out.write(chunk)
                        done += len(chunk)
                        _set(done=done)
            partial.chmod(0o755)
            os.replace(partial, appimage)
            _remember_install(str(appimage), "lmstudio")
            _add_to_applications_menu(appimage)
            _set(state="done", phase="ready", result={"path": str(appimage)})
            logger.info("LM Studio AppImage downloaded to %s", appimage)
        except Exception as exc:  # noqa: BLE001 — shown in the wizard
            logger.exception("downloading LM Studio failed")
            _set(state="error", error=str(exc))

    threading.Thread(target=work, daemon=True, name="install-lmstudio").start()
    return get_job() or {}


def start_install_comfyui(target_dir: Path) -> dict[str, Any]:
    """Download the official portable build and unpack it into *target_dir*.
    Runs in the background; follow it with get_job()."""
    global _job
    if sys.platform.startswith("linux"):
        return _start_install_comfyui_linux(target_dir)
    if not sys.platform.startswith("win"):
        raise ValueError("Installing ComfyUI from here is only available on Windows and Linux for now")
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
            with urllib.request.urlopen(download_url(asset["browser_download_url"]), timeout=60) as response, partial.open("wb") as out:
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
                                    capture_output=True, text=True, errors="replace",
                                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            if result.returncode != 0:
                raise ValueError("The download could not be unpacked: " + (result.stderr or "")[:200])
            archive.unlink(missing_ok=True)

            installed = _comfy_in(target_dir) or find_comfyui() or {}
            if not installed.get("launcher"):
                raise ValueError("Unpacked, but no ComfyUI launcher was found in " + str(target_dir))
            _remember_install(installed["path"])
            _set(state="done", phase="ready", result=installed)
            logger.info("ComfyUI portable installed at %s", installed.get("path"))
        except Exception as exc:  # noqa: BLE001 — shown in the wizard
            logger.exception("installing ComfyUI failed")
            _set(state="error", error=str(exc))

    threading.Thread(target=work, daemon=True, name="install-comfyui").start()
    return get_job() or {}


# ── Installing ComfyUI on Linux ─────────────────────────────────────────────


def _can_install_linux() -> bool:
    return sys.platform.startswith("linux") and platform.machine() in ("x86_64", "AMD64")


def _fetch(url: str, dest: Path, headers: dict[str, str] | None = None) -> None:
    """Download *url* to *dest*, reporting bytes to the current job."""
    request = urllib.request.Request(download_url(url), headers={"User-Agent": "NomadStudio", **(headers or {})})
    partial = dest.with_name(dest.name + ".part")
    with urllib.request.urlopen(request, timeout=60) as response, partial.open("wb") as out:  # noqa: S310
        _set(done=0, total=int(response.headers.get("Content-Length") or 0))
        done = 0
        while True:
            chunk = response.read(1 << 20)
            if not chunk:
                break
            out.write(chunk)
            done += len(chunk)
            _set(done=done)
    os.replace(partial, dest)


def _pip(python: Path, args: list[str], cwd: Path) -> None:
    """Run pip with the new Python; its "Downloading …" lines become the job's
    detail so the wizard shows what the long wait is about."""
    env = {**os.environ, "PIP_DISABLE_PIP_VERSION_CHECK": "1", "PYTHONNOUSERSITE": "1", "PIP_NO_INPUT": "1"}
    proc = subprocess.Popen([str(python), "-m", "pip", "install", "--progress-bar", "off", *args],  # noqa: S603
                            cwd=str(cwd), env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, errors="replace")
    tail: list[str] = []
    for line in proc.stdout or []:
        line = line.strip()
        if not line:
            continue
        tail = (tail + [line])[-12:]
        m = re.match(r"Downloading (\S+?)(?:-\d[^ ]*)? \(([^)]+)\)", line)
        if m:
            _set(detail=f"{m.group(1).rsplit('/', 1)[-1]} ({m.group(2)})")
    if proc.wait() != 0:
        raise ValueError("pip could not install ComfyUI's packages: " + " | ".join(tail[-3:])[:400])


def _start_install_comfyui_linux(target_dir: Path) -> dict[str, Any]:
    """Assemble ComfyUI_linux_portable in *target_dir*: the latest ComfyUI
    release, a python-build-standalone CPython (checked by sha256) and
    PyTorch for this machine's card, then run_nomad.sh to start it."""
    global _job
    if not _can_install_linux():
        raise ValueError("Installing ComfyUI from here needs Linux on an x86-64 computer")
    root = target_dir / COMFY_LINUX_DIR
    if root.exists() and any(root.iterdir()):
        raise ValueError(f"{root} already exists: choose another folder or remove it")
    backend = linux_torch_backend()
    with _job_lock:
        if _job and _job.get("state") == "running":
            raise ValueError("Something else is already being installed")
        _job = {"id": uuid.uuid4().hex[:12], "app": "comfy", "state": "running", "phase": "asset", "done": 0,
                "total": 0, "error": "", "result": None, "backend": backend, "detail": ""}

    def work() -> None:
        created = False
        try:
            target_dir.mkdir(parents=True, exist_ok=True)
            need = LINUX_FREE_BYTES[backend]
            free = shutil.disk_usage(target_dir).free
            if free < need:
                raise ValueError(f"Not enough free space: {free // 2**30} GB available, about {need // 2**30} GB needed")
            request = urllib.request.Request(COMFY_RELEASES_API, headers={"Accept": "application/vnd.github+json",
                                                                          "User-Agent": "NomadStudio"})
            with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
                release = json.loads(response.read().decode("utf-8"))
            tag = release.get("tag_name") or ""
            source_url = release.get("tarball_url")
            if not source_url:
                raise ValueError("That ComfyUI release has no source archive")
            root.mkdir(parents=True, exist_ok=True)
            created = True
            work_dir = root / ".download"
            work_dir.mkdir(exist_ok=True)

            # 1. ComfyUI itself
            _set(phase="download", version=tag, asset=f"ComfyUI {tag}")
            archive = work_dir / "comfyui.tar.gz"
            _fetch(source_url, archive, {"Accept": "application/vnd.github+json"})
            _set(phase="extract", done=0, total=0)
            unpack = work_dir / "comfyui"
            with tarfile.open(archive) as tar:
                tar.extractall(unpack, filter="data")
            top = next(p for p in unpack.iterdir() if p.is_dir())
            shutil.move(str(top), str(root / "ComfyUI"))

            # 2. Its own Python
            _set(phase="python", done=0, total=0, detail="")
            py_archive = work_dir / "python.tar.gz"
            _fetch(LINUX_PYTHON_URL, py_archive)
            digest = hashlib.sha256()
            with py_archive.open("rb") as fh:
                for chunk in iter(lambda: fh.read(1 << 20), b""):
                    digest.update(chunk)
            if digest.hexdigest() != LINUX_PYTHON_SHA256:
                raise ValueError("The Python download does not match its checksum")
            py_unpack = work_dir / "python"
            with tarfile.open(py_archive) as tar:
                tar.extractall(py_unpack, filter="data")
            shutil.move(str(py_unpack / "python"), str(root / "python_embeded"))
            python = root / "python_embeded" / "bin" / "python3"

            # 3. PyTorch for this card, then the rest of ComfyUI's requirements
            _set(phase="torch", done=0, total=0, detail="")
            _pip(python, ["torch", "torchvision", "torchaudio", "--index-url", TORCH_INDEX[backend]], root)
            _set(phase="requirements", detail="")
            _pip(python, ["-r", str(root / "ComfyUI" / "requirements.txt")], root)

            # 4. The launcher (also handy by hand: ./run_nomad.sh)
            flags = " --cpu" if backend == "cpu" else ""
            launcher = root / LINUX_LAUNCHER
            launcher.write_text(
                "#!/bin/sh\n"
                "# Starts this ComfyUI (installed by Nomad Studio's setup wizard). Extra arguments are passed on.\n"
                'cd "$(dirname "$0")" || exit 1\n'
                f'exec ./python_embeded/bin/python3 -s ComfyUI/main.py --disable-auto-launch{flags} "$@"\n',
                encoding="utf-8")
            launcher.chmod(0o755)
            (root / "nomad-install.json").write_text(json.dumps(
                {"comfyui": tag, "torch": backend, "installed_at": time.strftime("%Y-%m-%dT%H:%M:%S")}, indent=2),
                encoding="utf-8")
            shutil.rmtree(work_dir, ignore_errors=True)

            installed = _comfy_in(target_dir) or find_comfyui() or {}
            if not installed.get("launcher"):
                raise ValueError("Installed, but no ComfyUI launcher was found in " + str(root))
            _remember_install(installed["path"])
            _set(state="done", phase="ready", result=installed)
            logger.info("ComfyUI %s (%s) installed at %s", tag, backend, root)
        except Exception as exc:  # noqa: BLE001 — shown in the wizard
            logger.exception("installing ComfyUI on Linux failed")
            if created:
                shutil.rmtree(root, ignore_errors=True)
            _set(state="error", error=str(exc))

    threading.Thread(target=work, daemon=True, name="install-comfyui").start()
    return get_job() or {}
