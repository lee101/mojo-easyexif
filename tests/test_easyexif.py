from __future__ import annotations

import re
import struct
from pathlib import Path

import numpy as np
import pytest

import mojo_easyexif as exif
from mojo_easyexif._lib import lib

DATA = Path(__file__).with_name("data")
FIXTURES = [
    "bb-android.jpg",
    "down-mirrored.jpg",
    "evil1.jpg",
    "lens_info.jpg",
    "right.jpg",
    "short-ascii-MM.jpg",
    "test1.jpg",
    "test2.jpg",
]


def expected_value(text: str, label: str) -> float:
    match = re.search(rf"^{re.escape(label)}\s*: ([-+0-9.]+)", text, re.MULTILINE)
    assert match
    return float(match.group(1))


def expected_coordinate(text: str, label: str):
    match = re.search(
        rf"^{re.escape(label)}\s*: ([-+0-9.]+) deg "
        r"\(([-+0-9.]+) deg, ([-+0-9.]+) min, "
        r"([-+0-9.]+) sec (.)\)",
        text,
        re.MULTILINE,
    )
    assert match
    return (
        float(match.group(1)),
        float(match.group(2)),
        float(match.group(3)),
        float(match.group(4)),
        match.group(5),
    )


@pytest.mark.parametrize("name", FIXTURES)
def test_upstream_published_expected_values(name: str):
    info = exif.parse_file(DATA / name)
    expected = (DATA / f"{name}.expected").read_text()

    assert info.orientation == int(expected_value(expected, "Image orientation"))
    assert info.focal_length == pytest.approx(
        expected_value(expected, "Lens focal length"), abs=5e-7
    )
    assert info.focal_length_35mm == int(
        expected_value(expected, "35mm focal length")
    )
    assert info.gps.altitude == pytest.approx(
        expected_value(expected, "GPS Altitude"), abs=5e-7
    )
    assert info.gps.dop == pytest.approx(
        expected_value(expected, "GPS Precision (DOP)"), abs=5e-7
    )

    lat = expected_coordinate(expected, "GPS Latitude")
    lon = expected_coordinate(expected, "GPS Longitude")
    assert info.gps.latitude == pytest.approx(lat[0], abs=5e-7)
    assert info.gps.latitude_components.degrees == pytest.approx(lat[1])
    assert info.gps.latitude_components.minutes == pytest.approx(lat[2])
    assert info.gps.latitude_components.seconds == pytest.approx(lat[3])
    assert info.gps.latitude_components.direction == lat[4]
    assert info.gps.longitude == pytest.approx(lon[0], abs=5e-7)
    assert info.gps.longitude_components.degrees == pytest.approx(lon[1])
    assert info.gps.longitude_components.minutes == pytest.approx(lon[2])
    assert info.gps.longitude_components.seconds == pytest.approx(lon[3])
    assert info.gps.longitude_components.direction == lon[4]


def make_segment(endian: str, denominator: int = 10) -> bytes:
    order = "<" if endian == "II" else ">"
    segment = bytearray(b"Exif\0\0")
    segment += endian.encode()
    segment += struct.pack(f"{order}HI", 42, 8)

    def offset() -> int:
        return len(segment) - 6

    def entry(tag: int, fmt: int, count: int, value: int | bytes):
        segment.extend(struct.pack(f"{order}HHI", tag, fmt, count))
        if isinstance(value, bytes):
            segment.extend(value.ljust(4, b"\0"))
        else:
            segment.extend(struct.pack(f"{order}I", value))

    segment += struct.pack(f"{order}H", 3)
    entry(0x112, 3, 1, struct.pack(f"{order}H", 6))
    exif_pointer = 8 + 2 + 3 * 12 + 4
    entry(0x8769, 4, 1, exif_pointer)
    gps_pointer = exif_pointer + 2 + 2 * 12 + 4 + 8
    entry(0x8825, 4, 1, gps_pointer)
    segment += b"\0\0\0\0"

    assert offset() == exif_pointer
    segment += struct.pack(f"{order}H", 2)
    focal_data_offset = offset() + 2 * 12 + 4
    entry(0x920A, 5, 1, focal_data_offset)
    entry(0xA405, 3, 1, struct.pack(f"{order}H", 50))
    segment += b"\0\0\0\0"
    segment += struct.pack(f"{order}II", 425, denominator)

    assert offset() == gps_pointer
    segment += struct.pack(f"{order}H", 7)
    gps_data_offset = offset() + 7 * 12 + 4
    latitude_offset = gps_data_offset
    longitude_offset = latitude_offset + 24
    altitude_offset = longitude_offset + 24
    dop_offset = altitude_offset + 8
    entry(2, 5, 3, latitude_offset)
    entry(1, 2, 2, b"S\0")
    entry(4, 5, 3, longitude_offset)
    entry(3, 2, 2, b"W\0")
    entry(6, 5, 1, altitude_offset)
    entry(5, 1, 1, b"\x01")
    entry(11, 5, 1, dop_offset)
    segment += b"\0\0\0\0"
    for numerator, divisor in [(12, 1), (30, 1), (0, 1)]:
        segment += struct.pack(f"{order}II", numerator, divisor)
    for numerator, divisor in [(45, 1), (15, 1), (30, 1)]:
        segment += struct.pack(f"{order}II", numerator, divisor)
    segment += struct.pack(f"{order}II", 1234, 10)
    segment += struct.pack(f"{order}II", 7, 2)
    return bytes(segment)


def make_jpeg(segment: bytes, padding: bytes = b"") -> bytes:
    section_length = len(segment) + 2
    return (
        b"\xff\xd8\xff\xe1"
        + struct.pack(">H", section_length)
        + segment
        + b"\xff\xd9"
        + padding
    )


@pytest.mark.parametrize("endian", ["II", "MM"])
def test_synthetic_ifd_walk_covers_byte_order_and_late_gps_refs(endian: str):
    segment = make_segment(endian)
    info = exif.parse(make_jpeg(segment, padding=b"camera padding"))
    assert info.byte_order == endian
    assert info.orientation == 6
    assert info.focal_length == 42.5
    assert info.focal_length_35mm == 50
    assert info.gps.latitude == -12.5
    assert info.gps.longitude == pytest.approx(-(45 + 15 / 60 + 30 / 3600))
    assert info.gps.altitude == -123.4
    assert info.gps.altitude_ref == 1
    assert info.gps.dop == 3.5
    assert info.gps.latitude_components.direction == "S"
    assert info.gps.longitude_components.direction == "W"


def test_zero_denominator_matches_upstream_rational_epsilon_choice():
    info = exif.parse_exif_segment(make_segment("II", denominator=0))
    assert info.focal_length == 0.0


def test_parse_many_matches_scalar_results():
    images = [(DATA / name).read_bytes() for name in FIXTURES]
    assert exif.parse_many(images) == [exif.parse(image) for image in images]
    assert exif.parse_many([memoryview(images[0])]) == [exif.parse(images[0])]
    buffers = [memoryview(images[0]), bytearray(images[1])]
    assert exif.parse_many(buffers) == [exif.parse(image) for image in buffers]
    assert exif.parse_many([]) == []


def test_bytes_like_inputs_are_normalized_without_dtype_or_stride_assumptions():
    image = (DATA / FIXTURES[0]).read_bytes()
    word_view = memoryview(np.frombuffer(image, dtype=np.uint16, count=len(image) // 2))
    assert exif.parse(word_view) == exif.parse(word_view.tobytes())

    padded = np.zeros(len(image) * 2, dtype=np.uint8)
    padded[::2] = np.frombuffer(image, dtype=np.uint8)
    strided = memoryview(padded)[::2]
    assert not strided.contiguous
    assert exif.parse(strided) == exif.parse(image)


def test_simd_result_clear_handles_tail_without_overwrite():
    segment = b"Exif\0\0II" + struct.pack("<HIH", 42, 8, 0) + b"\0" * 4
    source = np.frombuffer(segment, dtype=np.uint8)
    values = np.full(18, 123456.0, dtype=np.float64)
    code = lib().easyexif_parse_segment(
        source.ctypes.data, source.size, values.ctypes.data
    )
    assert code == exif.PARSE_EXIF_SUCCESS
    assert np.all(values[1:12] == 0.0)
    assert np.all(values[13:16] == 0.0)
    assert values[12] == ord("?")
    assert values[16] == ord("?")
    assert values[17] == 123456.0


def test_native_boundary_rejects_null_and_out_of_range_batch_inputs():
    library = lib()
    assert (
        library.easyexif_parse_jpeg(None, 0, None)
        == exif.PARSE_EXIF_ERROR_CORRUPT
    )

    source = np.frombuffer(b"\xff\xd8\xff\xd9", dtype=np.uint8)
    offsets = np.asarray([source.size], dtype=np.int64)
    lengths = np.asarray([1], dtype=np.int64)
    values = np.full((1, 17), 123456.0, dtype=np.float64)
    statuses = np.full(1, -1, dtype=np.int64)
    code = library.easyexif_parse_many(
        source.ctypes.data,
        source.size,
        offsets.ctypes.data,
        lengths.ctypes.data,
        1,
        values.ctypes.data,
        statuses.ctypes.data,
    )
    assert code == exif.PARSE_EXIF_SUCCESS
    assert statuses[0] == exif.PARSE_EXIF_ERROR_CORRUPT
    assert np.all(values[0, :12] == 0.0)


@pytest.mark.parametrize(
    ("data", "code"),
    [
        (b"", exif.PARSE_EXIF_ERROR_NO_JPEG),
        (b"not a jpeg", exif.PARSE_EXIF_ERROR_NO_JPEG),
        (b"\xff\xd8garbage", exif.PARSE_EXIF_ERROR_NO_JPEG),
        (b"\xff\xd8\xff\xd9", exif.PARSE_EXIF_ERROR_NO_EXIF),
        (
            b"\xff\xd8\xff\xe1\x00\x0f" + b"x" * 13 + b"\xff\xd9",
            exif.PARSE_EXIF_ERROR_CORRUPT,
        ),
    ],
)
def test_jpeg_error_codes(data: bytes, code: int):
    with pytest.raises(exif.ExifParseError) as caught:
        exif.parse(data)
    assert caught.value.code == code


def test_segment_error_codes():
    with pytest.raises(exif.ExifParseError) as caught:
        exif.parse_exif_segment(b"bad")
    assert caught.value.code == exif.PARSE_EXIF_ERROR_NO_EXIF

    unknown = b"Exif\0\0ZZ" + b"\0" * 8
    with pytest.raises(exif.ExifParseError) as caught:
        exif.parse_exif_segment(unknown)
    assert caught.value.code == exif.PARSE_EXIF_ERROR_UNKNOWN_BYTEALIGN

    corrupt = b"Exif\0\0II" + struct.pack("<HI", 41, 8)
    with pytest.raises(exif.ExifParseError) as caught:
        exif.parse_exif_segment(corrupt)
    assert caught.value.code == exif.PARSE_EXIF_ERROR_CORRUPT


def test_truncated_external_value_is_corrupt_not_out_of_bounds():
    segment = bytearray(make_segment("MM"))
    gps = segment.find(struct.pack(">HHI", 2, 5, 3))
    segment[gps + 8 : gps + 12] = struct.pack(">I", len(segment) + 100)
    with pytest.raises(exif.ExifParseError) as caught:
        exif.parse_exif_segment(segment)
    assert caught.value.code == exif.PARSE_EXIF_ERROR_CORRUPT
