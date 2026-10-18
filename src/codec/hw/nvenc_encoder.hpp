#pragma once

#include "src/codec/encoder.hpp"
#include "src/codec/sw_encoder.hpp"
#include <atomic>
#include <memory>
#include <mutex>

namespace dav {

class NvencEncoder : public IEncoder {
public:
    NvencEncoder();
    ~NvencEncoder() override;

    VoidResult init(const EncoderParams& params) override;
    VoidResult encode(const CapturedFrame& frame) override;
    void flush() override;
    void close() override;

    void set_packet_callback(EncodedPacketCallback cb) override;
    VoidResult update_bitrate(uint32_t target_bitrate_kbps) override;
    VoidResult update_fps(uint32_t target_fps) override;
    void request_keyframe() override;

    [[nodiscard]] bool is_hardware_accelerated() const noexcept override { return is_hw_active_; }
    [[nodiscard]] std::string_view get_encoder_name() const noexcept override {
        return is_hw_active_ ? "NVIDIA_NVENC_Hardware_Encoder" : "Software_H264_Fallback";
    }
    [[nodiscard]] EncoderParams get_params() const noexcept override { return params_; }

private:
    EncoderParams params_{};
    EncodedPacketCallback packet_callback_;
    bool is_hw_active_{false};
    std::unique_ptr<SwEncoder> fallback_encoder_;
    std::mutex mutex_;
};

} // namespace dav
