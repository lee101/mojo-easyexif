"""Load the Mojo shared library and define its C signatures."""

from __future__ import annotations

import ctypes
import os
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC = os.path.join(ROOT, "src", "easyexif.mojo")
LIB = os.environ.get("MOJO_EASYEXIF_LIB") or os.path.join(
    ROOT, "dist", "libmojo-easyexif.so"
)

I = ctypes.c_int64
P = ctypes.c_void_p

_SIGNATURES = {
    "easyexif_parse_jpeg": ([P, I, P], I),
    "easyexif_parse_segment": ([P, I, P], I),
    "easyexif_parse_many": ([P, I, P, P, I, P, P], I),
}


class BuildError(RuntimeError):
    pass


def build(force: bool = False) -> str:
    if os.environ.get("MOJO_EASYEXIF_LIB") and os.path.exists(LIB) and not force:
        return LIB
    if not force and os.path.exists(LIB) and os.path.getmtime(LIB) >= os.path.getmtime(SRC):
        return LIB
    script = os.path.join(ROOT, "build", "build.sh")
    proc = subprocess.run(
        ["bash", script], capture_output=True, text=True, timeout=1800
    )
    if proc.returncode != 0 or not os.path.exists(LIB):
        raise BuildError((proc.stderr or proc.stdout).strip()[:4000])
    return LIB


_loaded: ctypes.CDLL | None = None


def lib() -> ctypes.CDLL:
    global _loaded
    if _loaded is None:
        _loaded = ctypes.CDLL(build())
        for name, (argtypes, restype) in _SIGNATURES.items():
            function = getattr(_loaded, name)
            function.argtypes = argtypes
            function.restype = restype
    return _loaded
