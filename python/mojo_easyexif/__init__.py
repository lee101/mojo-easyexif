"""A Mojo port of EasyEXIF's orientation, focal-length, and GPS parser."""

from .api import (
    PARSE_EXIF_ERROR_CORRUPT,
    PARSE_EXIF_ERROR_NO_EXIF,
    PARSE_EXIF_ERROR_NO_JPEG,
    PARSE_EXIF_ERROR_UNKNOWN_BYTEALIGN,
    PARSE_EXIF_SUCCESS,
    Coordinate,
    ExifInfo,
    ExifParseError,
    GPSInfo,
    parse,
    parse_exif_segment,
    parse_file,
    parse_many,
)

__all__ = [
    "Coordinate",
    "ExifInfo",
    "ExifParseError",
    "GPSInfo",
    "PARSE_EXIF_ERROR_CORRUPT",
    "PARSE_EXIF_ERROR_NO_EXIF",
    "PARSE_EXIF_ERROR_NO_JPEG",
    "PARSE_EXIF_ERROR_UNKNOWN_BYTEALIGN",
    "PARSE_EXIF_SUCCESS",
    "parse",
    "parse_exif_segment",
    "parse_file",
    "parse_many",
]
