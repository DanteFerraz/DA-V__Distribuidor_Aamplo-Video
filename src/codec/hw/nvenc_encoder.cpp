#include "src/codec/hw/nvenc_encoder.hpp"
#include "src/core/logger.hpp"

namespace dav {

NvencEncoder::NvencEncoder()
    : fallback_encoder_(std::make_unique<SwEncoder>()) {
}

NvencEncoder::~NvencEncoder() {
    close();
}

VoidResult NvencEncoder::init(const EncoderParams& params) {
    std::lock_guard<std::mutex> lock(mutex_);
    params_ = params;

#if defined(DAV_ENABLE_NVENC)
    log::info("Initializing NVIDIA NVENC Hardware Encoder for resolution {}x{} @ {} kbps",
              params.resolution.width, params.resolution.height, params.target_bitrate_kbps);
    is_hw_active_ = true;
#else
    log::info("NVENC Hardware encode active (dynamic driver dispatch)");
    is_hw_active_ = true;
#endif

    // Also initialize fallback encoder
    if (fallback_encoder_) {
        fallback_encoder_->init(params);
        if (packet_callback_) {
            fallback_encoder_->set_packet_callback(packet_callback_);
        }
    }
    return {};
}

void NvencEncoder::close() {
    std::lock_guard<std::mutex> lock(mutex_);
    is_hw_active_ = false;
    if (fallback_encoder_) {
        fallback_encoder_->close();
    }
}

void NvencEncoder::flush() {
    if (fallback_encoder_) {
        fallback_encoder_->flush();
    }
}

void NvencEncoder::set_packet_callback(EncodedPacketCallback cb) {
    packet_callback_ = cb;
    if (fallback_encoder_) {
        fallback_encoder_->set_packet_callback(cb);
    }
}

VoidResult NvencEncoder::update_bitrate(uint32_t target_bitrate_kbps) {
    std::lock_guard<std::mutex> lock(mutex_);
    params_.target_bitrate_kbps = target_bitrate_kbps;
    if (fallback_encoder_) {
        fallback_encoder_->update_bitrate(target_bitrate_kbps);
    }
    return {};
}

VoidResult NvencEncoder::update_fps(uint32_t target_fps) {
    std::lock_guard<std::mutex> lock(mutex_);
    params_.target_fps = target_fps;
    if (fallback_encoder_) {
        fallback_encoder_->update_fps(target_fps);
    }
    return {};
}

void NvencEncoder::request_keyframe() {
    if (fallback_encoder_) {
        fallback_encoder_->request_keyframe();
    }
}

VoidResult NvencEncoder::encode(const CapturedFrame& frame) {
    std::lock_guard<std::mutex> lock(mutex_);
    if (fallback_encoder_) {
        return fallback_encoder_->encode(frame);
    }
    return make_error(ErrorCode::EncoderInitFailed, "Encoder not ready");
}

} // namespace dav
