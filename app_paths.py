"""Resolve runtime paths for source runs and PyInstaller frozen builds.

Frozen builds live in a copied folder (USB stick / network share). Writable
files such as reports must sit next to the exe, not inside the read-only
``_MEIPASS`` extract dir.
"""
from __future__ import annotations

import sys
from pathlib import Path

AMCAP_NAME = "amcap+v3.0.9.exe"


def app_dir() -> Path:
    """Directory that travels with the program.

    Frozen: folder containing the exe. Source: project root.
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def resource_dir() -> Path:
    """Read-only bundled resources (PyInstaller ``_MEIPASS``, else :func:`app_dir`)."""
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass)
    return app_dir()


def reports_dir() -> Path:
    return app_dir() / "reports"


def amcap_path() -> Path:
    sidecar = app_dir() / AMCAP_NAME
    if sidecar.is_file():
        return sidecar
    return resource_dir() / AMCAP_NAME
