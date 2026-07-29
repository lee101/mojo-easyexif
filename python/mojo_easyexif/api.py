"""Python objects for the Mojo EasyEXIF parser."""

from __future__ import annotations

import ctypes
from dataclasses import dataclass
from os import PathLike
from pathlib import Path
from typing import Iterable

import numpy as np

from ._lib import lib

PARSE_EXIF_SUCCESS = 0
PARSE_EXIF_ERROR_NO_JPEG = 1982
PARSE_EXIF_ERROR_NO_EXIF = 1983
PARSE_EXIF_ERROR_UNKNOWN_BYTEALIGN = 1984
PARSE_EXIF_ERROR_CORRUPT = 1985

_ERROR_MESSAGES = {
    PARSE_EXIF_ERROR_NO_JPEG: "not a JPEG image",
    PARSE_EXIF_ERROR_NO_EXIF: "no EXIF header found",
    PARSE_EXIF_ERROR_UNKNOWN_BYTEALIGN: "unknown TIFF byte alignment",
    PARSE_EXIF_ERROR_CORRUPT: "corrupt EXIF data",
}
_RESULT_SIZE = 17


class ExifParseError(ValueError):
    def __init__(self, code: int):
        self.code = int(code)
        super().__init__(_ERROR_MESSAGES.get(self.code, f"EXIF parse error {self.code}"))


@dataclass(frozen=True, slots=True)
class Coordinate:
    degrees: float
    minutes: float
    seconds: float
    direction: str


@dataclass(frozen=True, slots=True)
class GPSInfo:
    latitude: float
    longitude: float
    altitude: float
    altitude_ref: int
    dop: float
    latitude_components: Coordinate
    longitude_components: Coordinate


@dataclass(frozen=True, slots=True)
class ExifInfo:
    byte_order: str
    orientation: int
    focal_length: float
    focal_length_35mm: int
    gps: GPSInfo


def _as_u8(data: bytes | bytearray | memoryview) -> np.ndarray:
    try:
        view = memoryview(data)
    except TypeError as exc:
        raise TypeError("data must be a bytes-like object") from exc
    if not view.contiguous or view.itemsize != 1:
        view = memoryview(view.tobytes())
    return np.frombuffer(view, dtype=np.uint8)


def _direction(value: float) -> str:
    code = int(value)
    return chr(code) if 0 <= code <= 127 else "?"


def _decode(values: np.ndarray) -> ExifInfo:
    latitude = Coordinate(
        float(values[9]),
        float(values[10]),
        float(values[11]),
        _direction(values[12]),
    )
    longitude = Coordinate(
        float(values[13]),
        float(values[14]),
        float(values[15]),
        _direction(values[16]),
    )
    gps = GPSInfo(
        latitude=float(values[4]),
        longitude=float(values[5]),
        altitude=float(values[6]),
        altitude_ref=int(values[7]),
        dop=float(values[8]),
        latitude_components=latitude,
        longitude_components=longitude,
    )
    return ExifInfo(
        byte_order="II" if int(values[0]) else "MM",
        orientation=int(values[1]),
        focal_length=float(values[2]),
        focal_length_35mm=int(values[3]),
        gps=gps,
    )


def _parse(
    data: bytes | bytearray | memoryview, *, segment: bool
) -> tuple[int, ExifInfo]:
    source = _as_u8(data)
    values = np.empty(_RESULT_SIZE, dtype=np.float64)
    function = lib().easyexif_parse_segment if segment else lib().easyexif_parse_jpeg
    code = int(
        function(
            source.ctypes.data_as(ctypes.c_void_p),
            source.size,
            values.ctypes.data_as(ctypes.c_void_p),
        )
    )
    return code, _decode(values)


def parse(data: bytes | bytearray | memoryview) -> ExifInfo:
    """Parse a complete JPEG buffer, raising :class:`ExifParseError` on failure."""
    code, info = _parse(data, segment=False)
    if code:
        raise ExifParseError(code)
    return info


def parse_exif_segment(data: bytes | bytearray | memoryview) -> ExifInfo:
    """Parse a buffer beginning with ``Exif\\0\\0``."""
    code, info = _parse(data, segment=True)
    if code:
        raise ExifParseError(code)
    return info


def parse_file(path: str | PathLike[str]) -> ExifInfo:
    return parse(Path(path).read_bytes())


def parse_many(
    images: Iterable[bytes | bytearray | memoryview],
) -> list[ExifInfo]:
    """Parse many JPEG buffers in one native call."""
    chunks = [_as_u8(image) for image in images]
    if not chunks:
        return []
    lengths = np.asarray([chunk.size for chunk in chunks], dtype=np.int64)
    offsets = np.empty(len(chunks), dtype=np.int64)
    offsets[0] = 0
    if len(chunks) > 1:
        np.cumsum(lengths[:-1], out=offsets[1:])
    source = np.frombuffer(b"".join(chunks), dtype=np.uint8)
    values = np.empty((len(chunks), _RESULT_SIZE), dtype=np.float64)
    statuses = np.empty(len(chunks), dtype=np.int64)
    code = lib().easyexif_parse_many(
        source.ctypes.data_as(ctypes.c_void_p),
        source.size,
        offsets.ctypes.data_as(ctypes.c_void_p),
        lengths.ctypes.data_as(ctypes.c_void_p),
        len(chunks),
        values.ctypes.data_as(ctypes.c_void_p),
        statuses.ctypes.data_as(ctypes.c_void_p),
    )
    if code:
        raise ExifParseError(int(code))
    for code in statuses:
        if code:
            raise ExifParseError(int(code))
    return [_decode(row) for row in values]
