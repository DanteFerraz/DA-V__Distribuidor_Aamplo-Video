#pragma once

#include "src/codec/encoder.hpp"
#include <atomic>
#include <mutex>
#include <vector>

namespace dav {

class SwEncoder : public IEncoder {
public:
    SwEncoder();
    ~SwEncoder() override;

    VoidResult init(const EncoderParams& params) override;
    VoidResult encode(const CapturedFrame& frame) override;
    void flush() override;
    void close() override;

    void set_packet_callback(EncodedPacketCallback cb) override;
    VoidResult update_bitrate(uint32_t target_bitrate_kbps) override;
    VoidResult update_fps(uint32_t target_fps) override;
    void request_keyframe() override;

    [[nodiscard]] bool is_hardware_accelerated() const noexcept override { return false; }
    [[nodiscard]] std::string_view get_encoder_name() const noexcept override { return "Software_H264_Encoder"; }
    [[nodiscard]] EncoderParams get_params() const noexcept override { return params_; }

private:
    Buffer generate_sps_pps();
    Buffer encode_h264_slice(const CapturedFrame& frame, bool is_keyframe);

    EncoderParams params_{};
    EncodedPacketCallback packet_callback_;
    std::atomic<bool> force_keyframe_{true};
    std::atomic<bool> initialized_{false};
    uint32_t frame_index_{0};

    std::vector<Byte> nv12_scratch_;
    std::mutex mutex_;
};

} // namespace dav
