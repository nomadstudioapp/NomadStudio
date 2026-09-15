"""Build the portable Nomad Studio ZIP (docs/APP_UPDATES.md §3, §4.1).

    python tools/build_portable.py --version 0.1.0-internal.1 --python-home C:\\python313

Result in dist/:
    NomadStudio-<version>-windows-x64.zip
    SHA256SUMS.txt

ZIP layout (first install: unzip anywhere and run NomadStudio.bat):
    NomadStudio/
    ├── NomadStudio.bat          launcher (also kept in app/launcher/)
    └── app/
        ├── portable.json        version, platform, commit (read by app_info.py)
        ├── app.py, app/, docs/  code, exported from git HEAD (committed files only)
        ├── python/              bundled CPython (same version as requirements.lock)
        ├── lib/                 dependencies from requirements.lock (--require-hashes)
        └── launcher/

Windows only for now. The bundled Python is copied from --python-home, which
must be the exact CPython version the lock was made for, with tkinter (the
Settings folder pickers need it). Linux/macOS will use python-build-standalone
(APP_UPDATES.md §4.1) and are added later.

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
import time
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
    text = (REPO / "tools" / "launcher" / "NomadStudio.bat").read_text(encoding="utf-8")
    crlf = text.replace("\r\n", "\n").replace("\n", "\r\n").encode("utf-8")
    (app_dir / "launcher").mkdir(parents=True, exist_ok=True)
    (app_dir / "launcher" / "NomadStudio.bat").write_bytes(crlf)
    (root / "NomadStudio.bat").write_bytes(crlf)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def smoke_test(app_dir: Path, version: str) -> None:
    """Start the built app exactly as the launcher does and wait for /api/health."""
    port = free_port()
    env = {k: v for k, v in os.environ.items() if not k.startswith(("PYTHON", "VIRTUAL_ENV"))}
    env.update(PYTHONNOUSERSITE="1", PYTHONUTF8="1", PORT=str(port))  # lib/ comes from nomad-lib.pth
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
        # The app must not import anything from outside the bundle.
        # The base libraries for add-ons (PACKAGE_FORMAT.md, level 1) must still
        # import after their test suites were removed.
        leak = subprocess.run([str(app_dir / "python" / "python.exe"), "-c",
                               "import sys,flask,numpy,scipy.ndimage,scipy.spatial,sklearn.cluster,PIL.Image,mcp,mcp.server.fastmcp,pywintypes,tkinter;"
                               "print(flask.__file__);print(numpy.__file__);print(sys.prefix)"],
                              env=env, capture_output=True, text=True, check=True).stdout
        if any(str(app_dir).lower() not in line.lower() for line in leak.strip().splitlines()):
            raise SystemExit("smoke test failed: modules loaded from outside the bundle:\n" + leak)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


def clean_runtime_files(app_dir: Path) -> None:
    """Remove what the smoke test created (registry, data) so the ZIP is empty."""
    shutil.rmtree(app_dir / "app" / "workflows", ignore_errors=True)
    data = app_dir / "app" / "data"
    keep = {"sfw_characters.json", "sfw_backgrounds.json"}
    for p in data.iterdir() if data.is_dir() else []:
        if p.name not in keep:
            shutil.rmtree(p) if p.is_dir() else p.unlink()
    for cache in app_dir.rglob("__pycache__"):
        if "python" not in cache.relative_to(app_dir).parts[:1] and "lib" not in cache.relative_to(app_dir).parts[:1]:
            shutil.rmtree(cache, ignore_errors=True)


def make_zip(root: Path, zip_path: Path) -> None:
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for path in sorted(root.rglob("*")):
            if path.is_file():
                zf.write(path, Path("NomadStudio") / path.relative_to(root))


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", required=True, help="SemVer, e.g. 0.1.0-internal.1")
    ap.add_argument("--python-home", required=True, type=Path, help="CPython install to bundle")
    ap.add_argument("--update-repo", default="juanpaexpedite/NomadStudio")
    args = ap.parse_args()

    if platform.system() != "Windows":
        raise SystemExit("this script builds the Windows package only (for now)")
    plat = "windows-x64"
    name = f"NomadStudio-{args.version}-{plat}"
    staging = DIST / name
    shutil.rmtree(staging, ignore_errors=True)
    root = staging / "NomadStudio"
    app_dir = root / "app"
    app_dir.mkdir(parents=True)

    print("1/6 code from git HEAD")
    commit = export_code(app_dir)

    print("2/6 bundled Python")
    py_version = copy_python(args.python_home, app_dir / "python")
    lock_py = lock_python_version()
    print(f"  CPython {py_version} (lock made for {lock_py})")
    if lock_py and not py_version.startswith(lock_py):
        raise SystemExit(f"Python {py_version} does not match the lock ({lock_py})")

    print("3/6 dependencies from requirements.lock")
    run([str(args.python_home / "python.exe"), "-m", "pip", "install", "--quiet", "--disable-pip-version-check",
         "--require-hashes", "--only-binary=:all:", "--no-deps",
         "--target", str(app_dir / "lib"), "-r", str(REPO / "requirements.lock")])
    freed = strip_library_tests(app_dir / "lib")
    print(f"  removed library test suites: {freed / 2**20:.0f} MB")

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
    write_launchers(app_dir, root)

    print("5/6 smoke test")
    smoke_test(app_dir, args.version)
    clean_runtime_files(app_dir)

    print("6/6 zip + SHA256SUMS")
    DIST.mkdir(exist_ok=True)
    zip_path = DIST / f"{name}.zip"
    zip_path.unlink(missing_ok=True)
    make_zip(root, zip_path)
    sums = DIST / "SHA256SUMS.txt"
    lines = [ln for ln in (sums.read_text(encoding="utf-8").splitlines() if sums.exists() else []) if not ln.endswith(zip_path.name)]
    lines.append(f"{sha256(zip_path)}  {zip_path.name}")
    sums.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"done: {zip_path} ({zip_path.stat().st_size / 2**20:.1f} MB), commit {commit}")


if __name__ == "__main__":
    main()
