# mojo-easyexif

`mojo-easyexif` is a standalone Mojo port of the metadata path in
[EasyEXIF](https://github.com/mayanklahiri/easyexif). It reads a JPEG buffer,
walks TIFF IFD0 plus the EXIF and GPS sub-IFDs, and returns orientation, focal
length, and geolocation data through a small Python API.

The port is derived from EasyEXIF's `exif.cpp`, specifically
`EXIFInfo::parseFrom`, `EXIFInfo::parseFromEXIFSegment`, `parseIFEntry_temp`,
`extract_values`, and the integer/rational parsing helpers. EasyEXIF is
BSD-2-Clause licensed. This repository is MIT licensed and retains the
upstream attribution and license in [NOTICE](NOTICE) and
[`vendor/easyexif/LICENSE`](vendor/easyexif/LICENSE).

## Coverage

Implemented:

- JPEG APP1/EXIF discovery, including EasyEXIF's end-marker and camera-padding
  behavior
- Intel (`II`) and Motorola (`MM`) TIFF byte order
- IFD0 traversal and EXIF/GPS sub-IFD offsets
- orientation (`0x0112`)
- focal length (`0x920a`) and 35mm-equivalent focal length (`0xa405`)
- GPS latitude/longitude, original degree/minute/second components and
  direction, altitude/reference, and DOP
- complete-JPEG, standalone `Exif\0\0` segment, file, and batch APIs
- bounds checks for truncated IFD entries and out-of-range external values

Not implemented are EasyEXIF's descriptive strings, timestamps, exposure,
flash, ISO, dimensions, metering, or extended lens information. MakerNotes,
XMP, IPTC, thumbnails, and rewriting metadata are also outside this port.

## Install and build

```bash
pixi install
pixi run build
```

The build produces `dist/libmojo-easyexif.so`. Pixi activates `python/` on
`PYTHONPATH`.

## Usage

This example runs against a copied upstream test image:

```python
from mojo_easyexif import parse_file

info = parse_file("tests/data/test1.jpg")
print(info.orientation)                # 1
print(info.focal_length)               # 4.28
print(info.focal_length_35mm)          # 35
print(info.gps.latitude)               # 37.885
print(info.gps.longitude)              # -122.6225
print(info.gps.longitude_components)   # Coordinate(..., direction='W')
```

For in-memory workloads use `parse(jpeg_bytes)` or
`parse_exif_segment(exif_segment)`. `parse_many(images)` concatenates the
buffers and enters Mojo once, which is useful when indexing a photo
collection. Invalid input raises `ExifParseError`; its `code` uses EasyEXIF's
original error numbers 1982 through 1985.

## How it works

Python holds all memory. A contiguous `uint8` buffer crosses the C ABI as an
integer address, and Mojo writes 17 `float64` result slots containing the
requested scalar fields. The wrapper converts that flat row into immutable
`ExifInfo`, `GPSInfo`, and `Coordinate` dataclasses. Batch parsing adds two
contiguous `int64` arrays for offsets and lengths and an `N x 17` result
matrix. There are no native allocations in the Mojo path.

The parser follows TIFF offsets relative to the TIFF header, validates the
whole IFD before walking its 12-byte entries, handles values stored inline or
out of line, and preserves EasyEXIF's zero-denominator rational result and
GPS sign behavior when direction/reference tags appear before or after their
values.

## Correctness

`pixi run test` runs 22 tests. Eight parameterized parity cases read original
EasyEXIF JPEGs and assert against their published `.expected` files. Further
tests cover both byte orders, inline and external values, a zero rational
denominator, late GPS sign tags, below-sea-level altitude, JPEG padding,
batch/scalar equality, missing markers, corrupt headers, and truncated
external data. Raw FFI tests exercise the SIMD result-clear tail, null
pointers, and out-of-range batch slices. Bytes-like tests cover non-contiguous
and wider-item views. No installable Python binding to this exact upstream C++
library exists, so the upstream project's own fixtures and expected results
are the parity oracle.

## Benchmark

Run only through `pixi run bench`; that task takes a machine-wide lock. The
benchmark compiles the vendored, unmodified upstream `exif.cpp` with `-O3`
and calls `EXIFInfo::parseFrom` through a C wrapper. Times below are the best
of five runs and include the same ctypes boundary and result writes for both
implementations.

Measured on an Intel Xeon E5-2697 v4 system (2 sockets, 36 physical cores,
72 threads), Linux x86-64, Mojo `1.1.0.dev2026081105`, GCC 14.3.0:

| case | Mojo (us/image) | EasyEXIF C++ (us/image) | C++ / Mojo |
|---|---:|---:|---:|
| single GPS JPEG | 3.967 | 6.478 | 1.63x |
| batch 1,000 GPS JPEGs | 0.184 | 2.448 | 13.31x |
| batch 1,000 mixed fixtures | 0.129 | 1.746 | 13.56x |

A ratio above `1x` means the Mojo port was faster. The larger batch advantage
comes from one FFI crossing and from the port storing only the covered fields;
the upstream object also constructs strings and temporary STL containers for
the broader metadata set.

The implementation clears result rows with unaligned-safe `float64` SIMD
stores plus a scalar tail. The IFD walks decode formats, counts, and external
offsets only for tags represented by the result schema, and the EXIF dispatch
path is inlined. A singleton batch crosses the FFI boundary zero-copy; larger
batches are packed once before entering Mojo.

Batch parsing remains serial because it was already more than 5x faster than
the reference before this optimization pass, so it was not a parallelization
target. No GPU path is provided: EXIF parsing consists almost entirely of byte
loads, comparisons, branches, and range checks, with only a few rational
divisions per image. Its arithmetic intensity is far below the roughly 2
flops-per-byte threshold at which device transfer and launch overhead could be
justified.
