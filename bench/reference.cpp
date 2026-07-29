#include <cstdint>

#include "../vendor/easyexif/exif.h"

namespace {
constexpr std::int64_t result_size = 17;

void write_result(const easyexif::EXIFInfo& info, double* result) {
  result[0] = info.ByteAlign;
  result[1] = info.Orientation;
  result[2] = info.FocalLength;
  result[3] = info.FocalLengthIn35mm;
  result[4] = info.GeoLocation.Latitude;
  result[5] = info.GeoLocation.Longitude;
  result[6] = info.GeoLocation.Altitude;
  result[7] = info.GeoLocation.AltitudeRef;
  result[8] = info.GeoLocation.DOP;
  result[9] = info.GeoLocation.LatComponents.degrees;
  result[10] = info.GeoLocation.LatComponents.minutes;
  result[11] = info.GeoLocation.LatComponents.seconds;
  result[12] = info.GeoLocation.LatComponents.direction;
  result[13] = info.GeoLocation.LonComponents.degrees;
  result[14] = info.GeoLocation.LonComponents.minutes;
  result[15] = info.GeoLocation.LonComponents.seconds;
  result[16] = info.GeoLocation.LonComponents.direction;
}
}  // namespace

extern "C" std::int64_t easyexif_reference_parse_jpeg(
    const unsigned char* data, std::int64_t length, double* result) {
  easyexif::EXIFInfo info;
  const int status = info.parseFrom(data, static_cast<unsigned>(length));
  write_result(info, result);
  return status;
}

extern "C" void easyexif_reference_parse_many(
    const unsigned char* data, const std::int64_t* offsets,
    const std::int64_t* lengths, std::int64_t count, double* results,
    std::int64_t* statuses) {
  for (std::int64_t i = 0; i < count; ++i) {
    statuses[i] = easyexif_reference_parse_jpeg(
        data + offsets[i], lengths[i], results + i * result_size);
  }
}
