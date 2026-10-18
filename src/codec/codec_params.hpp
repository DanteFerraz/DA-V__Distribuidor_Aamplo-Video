#pragma once

#include "src/core/types.hpp"
#include <cstdint>
#include <string>

namespace dav {

enum class FrameType : uint8_t {
    Unknown,
    IDR,        // Instantaneous Decoder Refresh (Keyframe)
    I_Frame,    // Intra-coded frame
    P_Frame,    // Predicted frame
    B_Frame     // Bi-directional frame
};

enum class RateControlMode : uint8_t {
    CBR,        // Constant Bitrate (Recommended for real-time video streaming)
    VBR,        // Variable Bitrate
    CQP         // Constant Quantization Parameter
};

struct EncoderParams {
    CodecType codec{CodecType::H264};
    Resolution resolution{1920, 1080};
    uint32_t target_fps{60};
    uint32_t target_bitrate_kbps{8000};
    uint32_t max_bitrate_kbps{25000};
    uint32_t min_bitrate_kbps{1000};
    uint32_t gop_size{60}; // Keyframe interval (frames)
    RateControlMode rate_control{RateControlMode::CBR};
    std::string preset{"ultrafast"};
    std::string tune{"zerolatency"};
    bool repeat_sps_pps{true};
    bool enable_zero_copy{true};
};

struct EncodedPacket {
    uint32_t frame_index{0};
    uint64_t timestamp_us{0};
    FrameType frame_type{FrameType::P_Frame};
    Buffer data;                // Annex-B H.264 bitstream (00 00 00 01 NAL units)
    bool is_keyframe{false};
    uint32_t pts{0};
    uint32_t dts{0};
};

} // namespace dav
