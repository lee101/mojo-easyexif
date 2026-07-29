"""Benchmark the Mojo port against the actual upstream EasyEXIF C++ parser."""

from __future__ import annotations

import ctypes
import math
import os
from pathlib import Path
import subprocess
import sys
import time

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))

from mojo_easyexif._lib import lib as mojo_lib  # noqa: E402

REFERENCE = ROOT / "build" / "libeasyexif-reference.so"
REFERENCE_SOURCES = [
    ROOT / "bench" / "reference.cpp",
    ROOT / "vendor" / "easyexif" / "exif.cpp",
    ROOT / "vendor" / "easyexif" / "exif.h",
]
I = ctypes.c_int64
P = ctypes.c_void_p


def reference_lib() -> ctypes.CDLL:
    newest = max(source.stat().st_mtime for source in REFERENCE_SOURCES)
    if not REFERENCE.exists() or REFERENCE.stat().st_mtime < newest:
        REFERENCE.parent.mkdir(exist_ok=True)
        compiler = os.environ.get("CXX", "c++")
        subprocess.run(
            [
                compiler,
                "-O3",
                "-DNDEBUG",
                "-std=c++17",
                "-fPIC",
                "-shared",
                str(ROOT / "bench" / "reference.cpp"),
                str(ROOT / "vendor" / "easyexif" / "exif.cpp"),
                "-o",
                str(REFERENCE),
            ],
            check=True,
        )
    library = ctypes.CDLL(str(REFERENCE))
    library.easyexif_reference_parse_jpeg.argtypes = [P, I, P]
    library.easyexif_reference_parse_jpeg.restype = I
    library.easyexif_reference_parse_many.argtypes = [P, P, P, I, P, P]
    library.easyexif_reference_parse_many.restype = None
    return library


def best_time(function, calls: int, repeat: int = 5) -> float:
    best = math.inf
    function()
    for _ in range(repeat):
        start = time.perf_counter()
        for _ in range(calls):
            function()
        best = min(best, (time.perf_counter() - start) / calls)
    return best


def single_functions(image: bytes):
    source = np.frombuffer(image, dtype=np.uint8)
    result = np.empty(17, dtype=np.float64)
    mojo = mojo_lib()
    reference = reference_lib()
    return (
        lambda: mojo.easyexif_parse_jpeg(
            source.ctypes.data, source.size, result.ctypes.data
        ),
        lambda: reference.easyexif_reference_parse_jpeg(
            source.ctypes.data, source.size, result.ctypes.data
        ),
    )


def batch_functions(images: list[bytes], repetitions: int):
    chunks = images
    lengths = np.asarray([len(chunk) for chunk in chunks], dtype=np.int64)
    offsets = np.empty(len(chunks), dtype=np.int64)
    offsets[0] = 0
    if len(chunks) > 1:
        np.cumsum(lengths[:-1], out=offsets[1:])
    source = np.frombuffer(b"".join(chunks), dtype=np.uint8)
    offsets = np.tile(offsets, repetitions)
    lengths = np.tile(lengths, repetitions)
    count = offsets.size
    results = np.empty((count, 17), dtype=np.float64)
    statuses = np.empty(count, dtype=np.int64)
    mojo = mojo_lib()
    reference = reference_lib()

    def mojo_call():
        mojo.easyexif_parse_many(
            source.ctypes.data,
            source.size,
            offsets.ctypes.data,
            lengths.ctypes.data,
            count,
            results.ctypes.data,
            statuses.ctypes.data,
        )

    def reference_call():
        reference.easyexif_reference_parse_many(
            source.ctypes.data,
            offsets.ctypes.data,
            lengths.ctypes.data,
            count,
            results.ctypes.data,
            statuses.ctypes.data,
        )

    return (
        mojo_call,
        reference_call,
        count,
    )


def main() -> None:
    data = ROOT / "tests" / "data"
    gps = (data / "bb-android.jpg").read_bytes()
    fixture_names = [
        "bb-android.jpg",
        "down-mirrored.jpg",
        "evil1.jpg",
        "lens_info.jpg",
        "right.jpg",
        "short-ascii-MM.jpg",
        "test1.jpg",
        "test2.jpg",
    ]
    fixtures = [(data / name).read_bytes() for name in fixture_names]

    single_mojo, single_cpp = single_functions(gps)
    mixed_mojo, mixed_cpp, mixed_count = batch_functions(fixtures, 125)
    gps_mojo, gps_cpp, gps_count = batch_functions([gps], 1000)
    cases = [
        ("single GPS JPEG", single_mojo, single_cpp, 20_000, 1),
        ("batch 1,000 GPS JPEGs", gps_mojo, gps_cpp, 100, gps_count),
        (
            "batch 1,000 mixed fixtures",
            mixed_mojo,
            mixed_cpp,
            100,
            mixed_count,
        ),
    ]

    print("| case | Mojo (us/image) | EasyEXIF C++ (us/image) | C++ / Mojo |")
    print("|---|---:|---:|---:|")
    for name, mojo, cpp, calls, images_per_call in cases:
        mojo_time = best_time(mojo, calls) / images_per_call
        cpp_time = best_time(cpp, calls) / images_per_call
        print(
            f"| {name} | {mojo_time * 1e6:.3f} | {cpp_time * 1e6:.3f} "
            f"| {cpp_time / mojo_time:.2f}x |"
        )


if __name__ == "__main__":
    main()
