#pragma once

#include "src/codec/codec_params.hpp"
#include "src/capture/capturer.hpp"
#include "src/core/result.hpp"
#include <functional>
#include <memory>
#include <string_view>

namespace dav {

using EncodedPacketCallback = std::function<void(const EncodedPacket& packet)>;

class IEncoder {
public:
    virtual ~IEncoder() = default;

    virtual VoidResult init(const EncoderParams& params) = 0;
    virtual VoidResult encode(const CapturedFrame& frame) = 0;
    virtual void flush() = 0;
    virtual void close() = 0;

    virtual void set_packet_callback(EncodedPacketCallback cb) = 0;
    virtual VoidResult update_bitrate(uint32_t target_bitrate_kbps) = 0;
    virtual VoidResult update_fps(uint32_t target_fps) = 0;
    virtual void request_keyframe() = 0;

    [[nodiscard]] virtual bool is_hardware_accelerated() const noexcept = 0;
    [[nodiscard]] virtual std::string_view get_encoder_name() const noexcept = 0;
    [[nodiscard]] virtual EncoderParams get_params() const noexcept = 0;
};

} // namespace dav
