"""Build the portable Nomad Studio ZIP (docs/APP_UPDATES.md §3, §4.1).

    python tools/build_portable.py --version 0.1.0-internal.1 --python-home C:\\python313

Result in dist/:
    NomadStudio-<version>-windows-x64.zip
    SHA256SUMS.txt

ZIP layout (first install: unzip anywhere and run NomadStudio.bat). No
top-level folder inside the ZIP: Windows "Extract all" already creates one
named after the ZIP, and a second NomadStudio/ inside it only made the paths
longer (found testing on a laptop).
    NomadStudio.bat              launcher (also kept in app/launcher/)
    app/
        ├── portable.json        version, platform, commit (read by app_info.py)
        ├── app.py, app/, docs/  code, exported from git HEAD (committed files only)
        ├── python/              bundled CPython (same version as requirements.lock)
        ├── lib/                 dependencies from requirements.lock (--require-hashes)
        └── launcher/

Windows: the bundled Python is copied from --python-home, which must be the
exact CPython version the lock was made for, with tkinter (the Settings folder
pickers need it).

Linux x64 (--platform linux-x64), built from this Windows machine: Python comes
from python-build-standalone (APP_UPDATES.md §4.1), downloaded once into
dist/python-cache and checked against the release's SHA256SUMS; dependencies
are resolved for manylinux by uv, which evaluates the lock's markers for the
target (pywin32 and colorama stay out). The result is a .tar.gz, which keeps
the executable bits a ZIP would lose. There is no smoke test — Linux binaries
do not run here — so the build checks the tree instead; the real test is
running ./NomadStudio.sh on a Linux machine.

macOS Apple Silicon (--platform macos-arm64, added 2026-10-04): the same
cross-build — python-build-standalone for aarch64-apple-darwin, dependencies
resolved by uv for that target — with NomadStudio.command as the launcher
(opens in Terminal on double-click). Not notarized: the launcher lifts the
download quarantine from its own folder once the user has allowed it, and
the download guide explains that first step. No smoke test here either; the
real test is double-clicking NomadStudio.command on a Mac.

Nothing is signed yet (SHA256SUMS.sig needs the official key, §3).
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import platform
import shutil
import socket
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.parse
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DIST = REPO / "dist"

# Parts of a CPython install a portable build does not need.
PY_EXCLUDE_TOP = {"Doc", "include", "libs", "Scripts", "NEWS.txt", "Tools"}
PY_EXCLUDE_LIB = {"site-packages", "test", "idlelib", "turtledemo", "ensurepip", "venv", "lib2to3"}


def run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    print("  $", " ".join(str(c) for c in cmd))
    return subprocess.run(cmd, check=True, **kw)


def export_code(dest: Path) -> str:
    """git archive HEAD into dest; returns the short commit."""
    status = subprocess.run(["git", "-C", str(REPO), "status", "--porcelain"], capture_output=True, text=True).stdout
    if status.strip():
        print("  ! working tree has uncommitted changes; the build uses HEAD only:")
        print("    " + status.strip().replace("\n", "\n    "))
    commit = subprocess.run(["git", "-C", str(REPO), "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    data = subprocess.run(["git", "-C", str(REPO), "archive", "--format=tar", "HEAD"], capture_output=True, check=True).stdout
    with tarfile.open(fileobj=io.BytesIO(data)) as tar:
        tar.extractall(dest, filter="data")
    shutil.rmtree(dest / "tools", ignore_errors=True)  # build tooling stays out of the app
    return commit


def copy_python(src: Path, dest: Path) -> str:
    version = subprocess.run([str(src / "python.exe"), "-c", "import platform;print(platform.python_version())"],
                             capture_output=True, text=True, check=True).stdout.strip()

    def ignore(dirpath: str, names: list[str]) -> set[str]:
        here = Path(dirpath)
        skipped = {"__pycache__"} & set(names)
        if here == src:
            skipped |= PY_EXCLUDE_TOP & set(names)
        if here == src / "Lib":
            skipped |= PY_EXCLUDE_LIB & set(names)
        return skipped

    shutil.copytree(src, dest, ignore=ignore)
    site_packages = dest / "Lib" / "site-packages"
    site_packages.mkdir(parents=True, exist_ok=True)
    # Register app/lib as a *site* directory, not via PYTHONPATH: only site
    # directories get their .pth files processed, and pywin32 (needed by the
    # mcp package on Windows) relies on pywin32.pth. With PYTHONPATH,
    # `import mcp` failed with "No module named 'pywintypes'".
    (site_packages / "nomad-lib.pth").write_text(
        "import os, site, sys; site.addsitedir(os.path.normpath(os.path.join(sys.prefix, os.pardir, 'lib')))\n",
        encoding="ascii",
    )
    if not (dest / "DLLs" / "_tkinter.pyd").is_file():
        raise SystemExit("bundled Python has no tkinter (_tkinter.pyd): the folder pickers would fail")
    return version


def lock_python_version() -> str | None:
    for line in (REPO / "requirements.lock").read_text(encoding="utf-8").splitlines()[:5]:
        if "--python-version" in line:
            return line.split("--python-version", 1)[1].split()[0]
    return None


def strip_library_tests(lib_dir: Path) -> int:
    """Delete the test suites bundled inside third-party packages (scipy,
    scikit-learn, numpy… ~57 MB). Nomad Studio never imports them. Only
    folders named exactly ``tests`` are removed; ``numpy.testing`` and
    similar runtime helpers are kept."""
    freed = 0
    for tests in sorted(lib_dir.rglob("tests"), key=lambda p: len(p.parts), reverse=True):
        if tests.is_dir() and tests.exists():
            freed += sum(f.stat().st_size for f in tests.rglob("*") if f.is_file())
            shutil.rmtree(tests)
    return freed


def write_launchers(app_dir: Path, root: Path) -> None:
    """Launcher at the root and in app/launcher/ (the copy an update brings),
    plus the update script (app/services/update_service.py) and the start
    screen the launcher opens while the app boots (start.html + its image)."""
    (app_dir / "launcher").mkdir(parents=True, exist_ok=True)
    for name in ("NomadStudio.bat", "apply_update.ps1"):
        text = (REPO / "tools" / "launcher" / name).read_text(encoding="utf-8")
        crlf = text.replace("\r\n", "\n").replace("\n", "\r\n").encode("utf-8")
        (app_dir / "launcher" / name).write_bytes(crlf)
    for name in ("start.html", "raccoon.png", "nomad.ico"):  # nomad.ico: the shortcuts the wizard makes
        shutil.copyfile(REPO / "tools" / "launcher" / name, app_dir / "launcher" / name)
    (root / "NomadStudio.bat").write_bytes((app_dir / "launcher" / "NomadStudio.bat").read_bytes())


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def smoke_test(app_dir: Path, version: str) -> None:
    """Start the built app exactly as the launcher does and wait for /api/health."""
    port = free_port()
    # A portable build keeps its data in ~/Nomad Studio/data (app/paths.py):
    # the smoke test must not create or touch that folder on the build machine.
    data_dir = Path(tempfile.mkdtemp(prefix="nomad-smoke-data-"))
    env = {k: v for k, v in os.environ.items() if not k.startswith(("PYTHON", "VIRTUAL_ENV", "NOMAD_"))}
    env.update(PYTHONNOUSERSITE="1", PYTHONUTF8="1", PORT=str(port), NOMAD_DATA_DIR=str(data_dir),  # lib/ comes from nomad-lib.pth
               NOMAD_NO_AUTOSTART="1")  # never start the build machine's ComfyUI / LM Studio
    proc = subprocess.Popen([str(app_dir / "python" / "python.exe"), str(app_dir / "app.py")],
                            cwd=app_dir, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    try:
        health = None
        for _ in range(120):
            if proc.poll() is not None:
                break
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=2) as r:
                    health = json.loads(r.read().decode())
                    break
            except Exception:  # noqa: BLE001
                time.sleep(0.5)
        if not health:
            out = proc.stdout.read().decode(errors="replace") if proc.poll() is not None else "(still running)"
            raise SystemExit("smoke test failed: /api/health never answered\n" + out[-3000:])
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/setup", timeout=10) as r:
            setup_status = r.status
        print(f"  health: {health}  | /setup: {setup_status}")
        if not health.get("portable") or health.get("version") != version:
            raise SystemExit("smoke test failed: portable.json not picked up")
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/packages", timeout=10) as r:
            pkgs = json.loads(r.read().decode()).get("packages", [])
        expected = len(list((app_dir / "bundled-packages").glob("*.zip")))
        print(f"  bundled packages installed on first start: {sum(1 for p in pkgs if p.get('bundled'))}/{expected}")
        if sum(1 for p in pkgs if p.get("bundled")) != expected:
            raise SystemExit("smoke test failed: bundled packages were not installed")
        # The app must not import anything from outside the bundle.
        # The base libraries for add-ons (PACKAGE_FORMAT.md, level 1) must still
        # import after their test suites were removed.
        leak = subprocess.run([str(app_dir / "python" / "python.exe"), "-c",
                               "import sys,flask,numpy,scipy.ndimage,scipy.spatial,sklearn.cluster,PIL.Image,mcp,mcp.server.fastmcp,pywintypes,tkinter;"
                               "print(flask.__file__);print(numpy.__file__);print(sys.prefix)"],
                              env=env, capture_output=True, text=True, check=True).stdout
        if any(str(app_dir).lower() not in line.lower() for line in leak.strip().splitlines()):
            raise SystemExit("smoke test failed: modules loaded from outside the bundle:\n" + leak)
        print(f"  data folder: registry={(data_dir / 'import_registry.json').is_file()} packages={(data_dir / 'packages' / 'index.json').is_file()}")
        if not (data_dir / "import_registry.json").is_file():
            raise SystemExit("smoke test failed: the app did not use NOMAD_DATA_DIR")
        stray = [p.name for p in (app_dir / "app" / "data").iterdir() if p.name not in ("sfw_characters.json", "sfw_backgrounds.json")]
        if stray or (app_dir / "app" / "workflows" / "import_registry.json").exists():
            raise SystemExit(f"smoke test failed: user data written inside the program folder: {stray}")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        shutil.rmtree(data_dir, ignore_errors=True)


def clean_runtime_files(app_dir: Path) -> None:
    """Remove the caches the smoke test left (its data went to a temp folder)."""
    for cache in app_dir.rglob("__pycache__"):
        if "python" not in cache.relative_to(app_dir).parts[:1] and "lib" not in cache.relative_to(app_dir).parts[:1]:
            shutil.rmtree(cache, ignore_errors=True)


def make_zip(root: Path, zip_path: Path) -> None:
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for path in sorted(root.rglob("*")):
            if path.is_file():
                zf.write(path, path.relative_to(root))


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


PBS_TAG = "20250409"
# python-build-standalone asset per cross-built platform.
PBS_ASSETS = {
    "linux-x64": "cpython-3.13.3+20250409-x86_64-unknown-linux-gnu-install_only.tar.gz",
    "macos-arm64": "cpython-3.13.3+20250409-aarch64-apple-darwin-install_only.tar.gz",
}
# uv's target for the dependency wheels, and the launcher each one ships.
# Free template packs shipped inside the app (also on Ko-fi at 0 USD).
INCLUDED_TEMPLATE_PACKS = ("cinematic", "creature-kingdom", "flat-and-vector", "interiors",
                           "lifelike-portraits", "wild-horizons")
UV_TARGETS = {"linux-x64": "x86_64-manylinux_2_28", "macos-arm64": "aarch64-apple-darwin"}
LAUNCHERS = {"linux-x64": "NomadStudio.sh", "macos-arm64": "NomadStudio.command"}
PBS_BASE = f"https://github.com/astral-sh/python-build-standalone/releases/download/{PBS_TAG}/"


def fetch_linux_python(dest: Path, plat: str = "linux-x64") -> str:
    """python-build-standalone for a cross-built platform, verified against its release's
    SHA256SUMS, unpacked into dest. Returns the Python version."""
    PBS_ASSET = PBS_ASSETS[plat]
    cache = DIST / "python-cache"
    cache.mkdir(parents=True, exist_ok=True)
    archive = cache / PBS_ASSET
    quoted = urllib.parse.quote(PBS_ASSET)
    if not archive.is_file():
        print(f"  downloading {PBS_ASSET} from github.com/astral-sh/python-build-standalone")
        with urllib.request.urlopen(PBS_BASE + quoted, timeout=120) as response, archive.open("wb") as out:
            shutil.copyfileobj(response, out, 1 << 20)
    sums = urllib.request.urlopen(PBS_BASE + "SHA256SUMS", timeout=60).read().decode("utf-8")
    expected = next((line.split()[0] for line in sums.splitlines() if line.strip().endswith(PBS_ASSET)), None)
    actual = sha256(archive)
    if not expected or expected.lower() != actual.lower():
        archive.unlink(missing_ok=True)
        raise SystemExit(f"python-build-standalone checksum mismatch: expected {expected}, got {actual}")
    print(f"  sha256 verified: {actual[:16]}…")
    unpack = dest.parent / ".python-unpack"
    shutil.rmtree(unpack, ignore_errors=True)
    with tarfile.open(archive) as tar:
        tar.extractall(unpack, filter="data")
    shutil.move(str(unpack / "python"), str(dest))
    shutil.rmtree(unpack, ignore_errors=True)
    # The install_only build carries the test suite and IDLE; the app needs neither.
    lib = dest / "lib" / "python3.13"
    for name in ("test", "idlelib", "turtledemo", "ensurepip", "lib2to3"):
        shutil.rmtree(lib / name, ignore_errors=True)
    site_packages = lib / "site-packages"
    site_packages.mkdir(parents=True, exist_ok=True)
    for item in site_packages.iterdir():  # pip/setuptools of the build machine are not needed
        shutil.rmtree(item, ignore_errors=True) if item.is_dir() else item.unlink()
    (site_packages / "nomad-lib.pth").write_text(
        "import os, site, sys; site.addsitedir(os.path.normpath(os.path.join(sys.prefix, os.pardir, 'lib')))\n",
        encoding="ascii",
    )
    return PBS_ASSET.split("+", 1)[0].split("-", 1)[1]


def install_linux_deps(lib_dir: Path, plat: str = "linux-x64") -> None:
    run(["uv", "pip", "install", "--quiet", "--require-hashes", "--only-binary", ":all:", "--no-deps",
         "--python-platform", UV_TARGETS[plat], "--python-version", "3.13",
         "--target", str(lib_dir), "-r", str(REPO / "requirements.lock")])


def check_linux_tree(app_dir: Path, plat: str = "linux-x64") -> None:
    """What a smoke test would catch, without running Linux/macOS binaries."""
    problems = []
    for rel in ("python/bin/python3", "app.py", "app/__init__.py", "portable.json", "launcher/" + LAUNCHERS[plat],
                "launcher/apply_update.sh",
                "python/lib/python3.13/site-packages/nomad-lib.pth"):
        if not (app_dir / rel).exists():
            problems.append("missing " + rel)
    lib = app_dir / "lib"
    for package in ("flask", "numpy", "PIL", "scipy", "sklearn", "mcp"):
        if not (lib / package).is_dir():
            problems.append("missing library " + package)
    if any(lib.glob("pywin32*")) or (lib / "win32").is_dir():
        problems.append("Windows-only packages leaked into lib/")
    windows_binaries = [p.name for p in lib.rglob("*.pyd")][:3]
    if windows_binaries:
        problems.append(f"Windows extension modules in lib/: {windows_binaries}")
    if not any(lib.rglob("*.so")):
        problems.append("no extension modules (.so) in lib/")
    if not (app_dir / "python" / "lib" / "python3.13" / "lib-dynload").is_dir():
        problems.append("python lib-dynload missing")
    if problems:
        raise SystemExit(f"{plat} tree check failed:\n  " + "\n  ".join(problems))
    so_count = sum(1 for _ in lib.rglob("*.so"))
    print(f"  tree ok: python3, app, launcher, {so_count} {plat} extension modules, no Windows binaries")


def make_tarball(root: Path, tar_path: Path) -> None:
    """tar.gz with the executable bits Linux/macOS need (a ZIP made on Windows has none)."""
    executable = {n for l in LAUNCHERS.values() for n in (l, "app/launcher/" + l)} | {"app/launcher/apply_update.sh"}

    def fix(info: tarfile.TarInfo) -> tarfile.TarInfo:
        rel = info.name.replace("\\", "/")
        info.uid = info.gid = 0
        info.uname = info.gname = ""
        if info.isdir():
            info.mode = 0o755
        elif info.isfile():
            info.mode = 0o755 if (rel in executable or "/python/bin/" in "/" + rel) else 0o644
        return info

    with tarfile.open(tar_path, "w:gz", compresslevel=9) as tar:
        for path in sorted(root.rglob("*")):
            tar.add(path, arcname=path.relative_to(root).as_posix(), recursive=False, filter=fix)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", required=True, help="SemVer, e.g. 0.1.0-internal.1")
    ap.add_argument("--platform", choices=("windows-x64", "linux-x64", "macos-arm64"), default="windows-x64")
    ap.add_argument("--python-home", type=Path, help="CPython install to bundle (Windows builds)")
    ap.add_argument("--update-repo", default="nomadstudioapp/NomadStudio")
    ap.add_argument("--packages-dir", type=Path, default=REPO / "dist" / "packages",
                    help="package ZIPs to ship in bundled-packages/ (tools/packages/build_packages.py writes them)")
    # Included packs built in NomadStudioPacks (a sibling checkout): the free
    # template packs the website and the Marketplace list as "Included".
    ap.add_argument("--extra-package", type=Path, action="append",
                    default=[REPO.parent / "NOMADSTUDIO_PACKS" / "dist" / f"nomad.templates-{name}.zip"
                             for name in INCLUDED_TEMPLATE_PACKS],
                    help="another ZIP to ship in bundled-packages/ (default: the free template packs)")
    args = ap.parse_args()

    if platform.system() != "Windows":
        raise SystemExit("this script runs on Windows (it cross-builds the Linux and macOS packages)")
    plat = args.platform
    # Cross-built, tar.gz, no smoke test: Linux and macOS share one path.
    linux = plat in ("linux-x64", "macos-arm64")
    if not linux and not args.python_home:
        raise SystemExit("--python-home is required for the Windows build")
    name = f"NomadStudio-{args.version}-{plat}"
    staging = DIST / name
    shutil.rmtree(staging, ignore_errors=True)
    root = staging / "NomadStudio"
    app_dir = root / "app"
    app_dir.mkdir(parents=True)

    print("1/6 code from git HEAD")
    commit = export_code(app_dir)

    print("2/6 bundled Python")
    py_version = fetch_linux_python(app_dir / "python", plat) if linux else copy_python(args.python_home, app_dir / "python")
    lock_py = lock_python_version()
    print(f"  CPython {py_version} (lock made for {lock_py})")
    if lock_py and not py_version.startswith(lock_py):
        raise SystemExit(f"Python {py_version} does not match the lock ({lock_py})")

    print("3/6 dependencies from requirements.lock")
    if linux:
        install_linux_deps(app_dir / "lib", plat)
    else:
        run([str(args.python_home / "python.exe"), "-m", "pip", "install", "--quiet", "--disable-pip-version-check",
             "--require-hashes", "--only-binary=:all:", "--no-deps",
             "--target", str(app_dir / "lib"), "-r", str(REPO / "requirements.lock")])
    freed = strip_library_tests(app_dir / "lib")
    print(f"  removed library test suites: {freed / 2**20:.0f} MB")

    # Free engines and base flows, installed by the app on its first start.
    bundled = sorted(args.packages_dir.glob("*.zip")) if args.packages_dir.is_dir() else []
    if not bundled:
        raise SystemExit(f"no package ZIPs in {args.packages_dir} — run tools/packages/build_packages.py first")
    for z in args.extra_package:
        if not z.is_file():
            raise SystemExit(f"missing included package {z} — build it in NomadStudioPacks first")
    bundled += args.extra_package
    (app_dir / "bundled-packages").mkdir()
    for z in bundled:
        shutil.copy2(z, app_dir / "bundled-packages" / z.name)
    print(f"  bundled packages: {len(bundled)} ({', '.join(z.stem for z in bundled)})")

    print("4/6 portable.json + launcher")
    (app_dir / "portable.json").write_text(json.dumps({
        "schema_version": 1,
        "version": args.version,
        "channel": "beta" if "-" in args.version else "stable",
        "platform": plat,
        "python": py_version,
        "built_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "commit": commit,
        "update_repo": args.update_repo,
        "data_schema": 1,
    }, indent=2) + "\n", encoding="utf-8")
    if linux:
        (app_dir / "launcher").mkdir(parents=True, exist_ok=True)
        launcher = LAUNCHERS[plat]
        script = (REPO / "tools" / "launcher" / launcher).read_text(encoding="utf-8").replace("\r\n", "\n")
        for target in (app_dir / "launcher" / launcher, root / launcher):
            target.write_bytes(script.encode("utf-8"))
        # Settings › Updates hands the folder swap to this (update_service.apply).
        updater = (REPO / "tools" / "launcher" / "apply_update.sh").read_text(encoding="utf-8").replace("\r\n", "\n")
        (app_dir / "launcher" / "apply_update.sh").write_bytes(updater.encode("utf-8"))
    else:
        write_launchers(app_dir, root)

    if linux:
        print(f"5/6 tree check ({plat} binaries do not run here: test {LAUNCHERS[plat]} on the real system)")
        check_linux_tree(app_dir, plat)
    else:
        print("5/6 smoke test")
        smoke_test(app_dir, args.version)
        clean_runtime_files(app_dir)

    print("6/6 archive + SHA256SUMS")
    DIST.mkdir(exist_ok=True)
    zip_path = DIST / (f"{name}.tar.gz" if linux else f"{name}.zip")
    zip_path.unlink(missing_ok=True)
    if linux:
        make_tarball(root, zip_path)
    else:
        make_zip(root, zip_path)
    sums = DIST / "SHA256SUMS.txt"
    lines = [ln for ln in (sums.read_text(encoding="utf-8").splitlines() if sums.exists() else []) if not ln.endswith(zip_path.name)]
    lines.append(f"{sha256(zip_path)}  {zip_path.name}")
    sums.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"done: {zip_path} ({zip_path.stat().st_size / 2**20:.1f} MB), commit {commit}")


if __name__ == "__main__":
    main()
