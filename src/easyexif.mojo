"""EasyEXIF JPEG/TIFF parsing kernels and their C ABI."""

from std.sys.info import simd_width_of as simdwidthof

comptime BPtr = UnsafePointer[UInt8, AnyOrigin[mut=True]]
comptime FPtr = UnsafePointer[Float64, AnyOrigin[mut=True]]
comptime IPtr = UnsafePointer[Int64, AnyOrigin[mut=True]]

comptime RESULT_SIZE = 17
comptime SUCCESS = 0
comptime ERROR_NO_JPEG = 1982
comptime ERROR_NO_EXIF = 1983
comptime ERROR_UNKNOWN_BYTEALIGN = 1984
comptime ERROR_CORRUPT = 1985


def clear_result(result: FPtr):
    comptime W = simdwidthof[DType.float64]()
    var zero = SIMD[DType.float64, W](0.0)
    var i = 0
    while i + W <= RESULT_SIZE:
        result.store[alignment=1](i, zero)
        i += W
    while i < RESULT_SIZE:
        result[i] = 0.0
        i += 1
    result[12] = 63.0
    result[16] = 63.0


def has_range(position: Int, size: Int, length: Int) -> Bool:
    return (
        position >= 0
        and size >= 0
        and position <= length
        and size <= length - position
    )


# easyexif: exif.cpp parse<uint16_t>/parse<uint32_t>
def read_u16(buf: BPtr, position: Int, align_intel: Bool) -> Int:
    if align_intel:
        return Int(buf[position]) | (Int(buf[position + 1]) << 8)
    return (Int(buf[position]) << 8) | Int(buf[position + 1])


def read_u32(buf: BPtr, position: Int, align_intel: Bool) -> Int:
    if align_intel:
        return (
            Int(buf[position])
            | (Int(buf[position + 1]) << 8)
            | (Int(buf[position + 2]) << 16)
            | (Int(buf[position + 3]) << 24)
        )
    return (
        (Int(buf[position]) << 24)
        | (Int(buf[position + 1]) << 16)
        | (Int(buf[position + 2]) << 8)
        | Int(buf[position + 3])
    )


# easyexif: exif.cpp Rational::operator double
def read_rational(buf: BPtr, position: Int, align_intel: Bool) -> Float64:
    var numerator = read_u32(buf, position, align_intel)
    var denominator = read_u32(buf, position + 4, align_intel)
    if denominator == 0:
        return 0.0
    return Float64(numerator) / Float64(denominator)


def format_size(format: Int) -> Int:
    if format == 1 or format == 2:
        return 1
    if format == 3:
        return 2
    if format == 4 or format == 9:
        return 4
    if format == 5 or format == 10:
        return 8
    if format == 7:
        return 1
    return 0


# easyexif: exif.cpp extract_values/parseIFEntry_temp
@always_inline
def entry_is_valid(
    buf: BPtr,
    entry: Int,
    base: Int,
    length: Int,
    align_intel: Bool,
    format: Int,
    count: Int,
) -> Bool:
    var size = format_size(format)
    if size == 0:
        return False
    if format == 7 or format == 9 or format == 10:
        return True
    var total = size * count
    if total <= 4:
        return True
    var data_position = base + read_u32(buf, entry + 8, align_intel)
    return has_range(data_position, total, length)


@always_inline
def first_short(
    buf: BPtr,
    entry: Int,
    base: Int,
    length: Int,
    align_intel: Bool,
    count: Int,
) -> Int:
    if count == 0:
        return 0
    if count * 2 <= 4:
        return read_u16(buf, entry + 8, align_intel)
    var position = base + read_u32(buf, entry + 8, align_intel)
    if not has_range(position, count * 2, length):
        return 0
    return read_u16(buf, position, align_intel)


# easyexif: exif.cpp extract_values<Rational>
@always_inline
def first_rational(
    buf: BPtr,
    entry: Int,
    base: Int,
    length: Int,
    align_intel: Bool,
    count: Int,
) -> Float64:
    var position = base + read_u32(buf, entry + 8, align_intel)
    if count == 0 or not has_range(position, count * 8, length):
        return 0.0
    return read_rational(buf, position, align_intel)


# easyexif: exif.cpp EXIFInfo::parseFromEXIFSegment EXIF SubIFD loop
def parse_sub_ifd(
    buf: BPtr,
    offset: Int,
    base: Int,
    length: Int,
    align_intel: Bool,
    result: FPtr,
) -> Int:
    if not has_range(offset, 2, length):
        return ERROR_CORRUPT
    var count = read_u16(buf, offset, align_intel)
    if not has_range(offset, 6 + 12 * count, length):
        return ERROR_CORRUPT
    var entry = offset + 2
    for _ in range(count):
        var tag = read_u16(buf, entry, align_intel)
        var format = read_u16(buf, entry + 2, align_intel)
        var value_count = read_u32(buf, entry + 4, align_intel)
        if entry_is_valid(
            buf, entry, base, length, align_intel, format, value_count
        ):
            if tag == 0x920A and format == 5:
                result[2] = first_rational(
                    buf, entry, base, length, align_intel, value_count
                )
            elif tag == 0xA405 and format == 3:
                result[3] = Float64(
                    first_short(
                        buf,
                        entry,
                        base,
                        length,
                        align_intel,
                        value_count,
                    )
                )
        entry += 12
    return SUCCESS


# easyexif: exif.cpp EXIFInfo::parseFromEXIFSegment GPS SubIFD loop
def parse_gps_ifd(
    buf: BPtr,
    offset: Int,
    base: Int,
    length: Int,
    align_intel: Bool,
    result: FPtr,
) -> Int:
    if not has_range(offset, 2, length):
        return ERROR_CORRUPT
    var count = read_u16(buf, offset, align_intel)
    if not has_range(offset, 6 + 12 * count, length):
        return ERROR_CORRUPT
    var entry = offset + 2
    for _ in range(count):
        var tag = read_u16(buf, entry, align_intel)
        if tag == 1:
            var direction = Int(buf[entry + 8])
            if direction == 0:
                direction = 63
            result[12] = Float64(direction)
            if direction == 83:
                result[4] = -result[4]
        elif tag == 2:
            var format = read_u16(buf, entry + 2, align_intel)
            var value_count = read_u32(buf, entry + 4, align_intel)
            if (format == 5 or format == 10) and value_count == 3:
                var data = read_u32(buf, entry + 8, align_intel)
                var position = base + data
                if not has_range(position, 24, length):
                    return ERROR_CORRUPT
                result[9] = read_rational(buf, position, align_intel)
                result[10] = read_rational(buf, position + 8, align_intel)
                result[11] = read_rational(buf, position + 16, align_intel)
                result[4] = (
                    result[9] + result[10] / 60.0 + result[11] / 3600.0
                )
                if Int(result[12]) == 83:
                    result[4] = -result[4]
        elif tag == 3:
            var direction = Int(buf[entry + 8])
            if direction == 0:
                direction = 63
            result[16] = Float64(direction)
            if direction == 87:
                result[5] = -result[5]
        elif tag == 4:
            var format = read_u16(buf, entry + 2, align_intel)
            var value_count = read_u32(buf, entry + 4, align_intel)
            if (format == 5 or format == 10) and value_count == 3:
                var data = read_u32(buf, entry + 8, align_intel)
                var position = base + data
                if not has_range(position, 24, length):
                    return ERROR_CORRUPT
                result[13] = read_rational(buf, position, align_intel)
                result[14] = read_rational(buf, position + 8, align_intel)
                result[15] = read_rational(buf, position + 16, align_intel)
                result[5] = (
                    result[13] + result[14] / 60.0 + result[15] / 3600.0
                )
                if Int(result[16]) == 87:
                    result[5] = -result[5]
        elif tag == 5:
            result[7] = Float64(buf[entry + 8])
            if Int(result[7]) == 1:
                result[6] = -result[6]
        elif tag == 6:
            var format = read_u16(buf, entry + 2, align_intel)
            if format == 5 or format == 10:
                var data = read_u32(buf, entry + 8, align_intel)
                var position = base + data
                if not has_range(position, 8, length):
                    return ERROR_CORRUPT
                result[6] = read_rational(buf, position, align_intel)
                if Int(result[7]) == 1:
                    result[6] = -result[6]
        elif tag == 11:
            var format = read_u16(buf, entry + 2, align_intel)
            if format == 5 or format == 10:
                var data = read_u32(buf, entry + 8, align_intel)
                var position = base + data
                if not has_range(position, 8, length):
                    return ERROR_CORRUPT
                result[8] = read_rational(buf, position, align_intel)
        entry += 12
    return SUCCESS


# easyexif: exif.cpp EXIFInfo::parseFromEXIFSegment
def parse_exif_segment(buf: BPtr, length: Int, result: FPtr) -> Int:
    if length < 6:
        return ERROR_NO_EXIF
    if (
        buf[0] != 69
        or buf[1] != 120
        or buf[2] != 105
        or buf[3] != 102
        or buf[4] != 0
        or buf[5] != 0
    ):
        return ERROR_NO_EXIF
    if length < 14:
        return ERROR_CORRUPT

    var base = 6
    var align_intel = True
    if buf[6] == 73 and buf[7] == 73:
        align_intel = True
        result[0] = 1.0
    elif buf[6] == 77 and buf[7] == 77:
        align_intel = False
        result[0] = 0.0
    else:
        return ERROR_UNKNOWN_BYTEALIGN
    if read_u16(buf, 8, align_intel) != 0x2A:
        return ERROR_CORRUPT

    var first_ifd = base + read_u32(buf, 10, align_intel)
    if not has_range(first_ifd, 2, length):
        return ERROR_CORRUPT
    var count = read_u16(buf, first_ifd, align_intel)
    if not has_range(first_ifd, 6 + 12 * count, length):
        return ERROR_CORRUPT

    var exif_offset = length
    var gps_offset = length
    var entry = first_ifd + 2
    for _ in range(count):
        var tag = read_u16(buf, entry, align_intel)
        var format = read_u16(buf, entry + 2, align_intel)
        var value_count = read_u32(buf, entry + 4, align_intel)
        if entry_is_valid(
            buf, entry, base, length, align_intel, format, value_count
        ):
            if tag == 0x112 and format == 3:
                result[1] = Float64(
                    first_short(
                        buf,
                        entry,
                        base,
                        length,
                        align_intel,
                        value_count,
                    )
                )
            elif tag == 0x8769:
                exif_offset = base + read_u32(buf, entry + 8, align_intel)
            elif tag == 0x8825:
                gps_offset = base + read_u32(buf, entry + 8, align_intel)
        entry += 12

    if has_range(exif_offset, 4, length):
        var code = parse_sub_ifd(
            buf, exif_offset, base, length, align_intel, result
        )
        if code != SUCCESS:
            return code
    if has_range(gps_offset, 4, length):
        var code = parse_gps_ifd(
            buf, gps_offset, base, length, align_intel, result
        )
        if code != SUCCESS:
            return code
    return SUCCESS


# easyexif: exif.cpp EXIFInfo::parseFrom
def parse_jpeg(buf: BPtr, original_length: Int, result: FPtr) -> Int:
    if original_length < 4:
        return ERROR_NO_JPEG
    if buf[0] != 0xFF or buf[1] != 0xD8:
        return ERROR_NO_JPEG

    var length = original_length
    while length > 2:
        if buf[length - 2] == 0xFF and buf[length - 1] == 0xD9:
            break
        length -= 1
    if length <= 2:
        return ERROR_NO_JPEG

    var offset = 0
    while offset < length - 1:
        if buf[offset] == 0xFF and buf[offset + 1] == 0xE1:
            break
        offset += 1
    if offset + 4 > length:
        return ERROR_NO_EXIF
    offset += 2
    var section_length = read_u16(buf, offset, False)
    if section_length < 16 or not has_range(offset, section_length, length):
        return ERROR_CORRUPT
    offset += 2
    return parse_exif_segment(buf + offset, length - offset, result)


@export("easyexif_parse_jpeg")
def easyexif_parse_jpeg(
    data_addr: Int, length: Int, result_addr: Int
) abi("C") -> Int:
    if result_addr == 0:
        return ERROR_CORRUPT
    var result = FPtr(unsafe_from_address=result_addr)
    clear_result(result)
    if data_addr == 0 or length < 0:
        return ERROR_NO_JPEG
    var buf = BPtr(unsafe_from_address=data_addr)
    return parse_jpeg(buf, length, result)


@export("easyexif_parse_segment")
def easyexif_parse_segment(
    data_addr: Int, length: Int, result_addr: Int
) abi("C") -> Int:
    if result_addr == 0:
        return ERROR_CORRUPT
    var result = FPtr(unsafe_from_address=result_addr)
    clear_result(result)
    if data_addr == 0 or length < 0:
        return ERROR_NO_EXIF
    var buf = BPtr(unsafe_from_address=data_addr)
    return parse_exif_segment(buf, length, result)


@export("easyexif_parse_many")
def easyexif_parse_many(
    data_addr: Int,
    data_length: Int,
    offsets_addr: Int,
    lengths_addr: Int,
    count: Int,
    results_addr: Int,
    statuses_addr: Int,
) abi("C") -> Int:
    if count < 0:
        return ERROR_CORRUPT
    if count == 0:
        return SUCCESS
    if (
        data_addr == 0
        or data_length < 0
        or offsets_addr == 0
        or lengths_addr == 0
        or results_addr == 0
        or statuses_addr == 0
    ):
        return ERROR_CORRUPT
    var data = BPtr(unsafe_from_address=data_addr)
    var offsets = IPtr(unsafe_from_address=offsets_addr)
    var lengths = IPtr(unsafe_from_address=lengths_addr)
    var results = FPtr(unsafe_from_address=results_addr)
    var statuses = IPtr(unsafe_from_address=statuses_addr)
    for i in range(count):
        var result = results + i * RESULT_SIZE
        clear_result(result)
        var offset = Int(offsets[i])
        var length = Int(lengths[i])
        if not has_range(offset, length, data_length):
            statuses[i] = Int64(ERROR_CORRUPT)
            continue
        statuses[i] = Int64(
            parse_jpeg(data + offset, length, result)
        )
    return SUCCESS
