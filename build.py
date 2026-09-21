"""Build a portable onedir folder that can be copied to a USB stick."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV_PY = ROOT / ".venv" / "Scripts" / "python.exe"
AMCAP = ROOT / "amcap+v3.0.9.exe"
DIST = ROOT / "dist" / "WinAutoTest"
LAUNCHER = DIST / "run.bat"


def run(cmd: list[str]) -> None:
    print("+", " ".join(cmd), flush=True)
    result = subprocess.run(cmd, cwd=ROOT)
    if result.returncode != 0:
        raise SystemExit(result.returncode)


def pip_install(py: Path) -> None:
    base = [
        str(py), "-m", "pip", "install",
        "--disable-pip-version-check",
        "-r", str(ROOT / "requirements.txt"),
        "pyinstaller",
    ]
    print("+", " ".join(base), flush=True)
    if subprocess.run(base, cwd=ROOT).returncode == 0:
        return
    fallback = base + [
        "-i", "https://pypi.org/simple",
        "--trusted-host", "pypi.org",
        "--trusted-host", "files.pythonhosted.org",
    ]
    print("pip failed, retrying with pypi.org ...", flush=True)
    run(fallback)


def python_exe() -> Path:
    if VENV_PY.is_file():
        return VENV_PY
    print("Creating venv...", flush=True)
    run([sys.executable, "-m", "venv", str(ROOT / ".venv")])
    if not VENV_PY.is_file():
        raise SystemExit("Failed to create .venv")
    return VENV_PY


def write_crlf(path: Path, text: str) -> None:
    path.write_bytes(text.replace("\r\n", "\n").replace("\n", "\r\n").encode("ascii"))


def main() -> None:
    py = python_exe()
    print("Installing dependencies...", flush=True)
    pip_install(py)
    print("Building portable folder...", flush=True)
    run([
        str(py), "-m", "PyInstaller",
        "--noconfirm", "--clean",
        str(ROOT / "WinAutoTest.spec"),
    ])
    if not (DIST / "WinAutoTest.exe").is_file():
        raise SystemExit(f"Build finished but {DIST / 'WinAutoTest.exe'} is missing")
    if AMCAP.is_file():
        dest = DIST / AMCAP.name
        dest.write_bytes(AMCAP.read_bytes())
        print(f"Copied {AMCAP.name}", flush=True)
    write_crlf(LAUNCHER, "\n".join([
        "@echo off",
        "cd /d \"%~dp0\"",
        "start \"\" \"%~dp0WinAutoTest.exe\"",
        "",
    ]))
    print(flush=True)
    print(f"Portable folder: {DIST}", flush=True)
    print("Copy that entire folder to a USB stick, then double-click WinAutoTest.exe", flush=True)
    print("or run.bat", flush=True)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as exc:
        print(f"Build failed: {type(exc).__name__}: {exc}", flush=True)
        raise SystemExit(1) from exc
