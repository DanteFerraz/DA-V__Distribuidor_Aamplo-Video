#include "src/qos/adaptive_bitrate.hpp"
#include <algorithm>

namespace dav {

AdaptiveBitrateController::AdaptiveBitrateController(
    uint32_t min_bitrate_kbps,
    uint32_t max_bitrate_kbps,
    Resolution base_resolution
) : min_bitrate_kbps_(min_bitrate_kbps),
    max_bitrate_kbps_(max_bitrate_kbps),
    base_resolution_(base_resolution),
    current_bitrate_kbps_(std::clamp(8000u, min_bitrate_kbps, max_bitrate_kbps)),
    current_resolution_(base_resolution) {
}

void AdaptiveBitrateController::reset() {
    current_bitrate_kbps_ = std::clamp(8000u, min_bitrate_kbps_, max_bitrate_kbps_);
    current_fps_ = 60;
    current_resolution_ = base_resolution_;
}

AbrDecision AdaptiveBitrateController::evaluate(const BandwidthEstimate& bw_est, uint32_t current_queue_size) {
    AbrDecision decision{};

    uint32_t estimated_kbps = bw_est.estimated_bitrate_bps / 1000;
    
    // AIMD Bitrate adaptation
    if (bw_est.state == NetworkState::Overusing || bw_est.packet_loss_rate > 0.03 || current_queue_size > 8) {
        // Multiplicative decrease: -20%
        current_bitrate_kbps_ = static_cast<uint32_t>(current_bitrate_kbps_ * 0.80);
    } else if (bw_est.state == NetworkState::Underusing && bw_est.packet_loss_rate < 0.005 && current_queue_size <= 2) {
        // Additive increase: +500 kbps
        current_bitrate_kbps_ = std::min(current_bitrate_kbps_ + 500, estimated_kbps);
    }

    current_bitrate_kbps_ = std::clamp(current_bitrate_kbps_, min_bitrate_kbps_, max_bitrate_kbps_);

    // FPS & Resolution Tiering based on Bitrate
    if (current_bitrate_kbps_ >= 6000) {
        current_fps_ = 60;
        current_resolution_ = base_resolution_; // 1080p
        decision.recommended_fec_ratio = 0.10;  // 10% FEC
    } else if (current_bitrate_kbps_ >= 3000) {
        current_fps_ = 45;
        current_resolution_ = {1280, 720};      // 720p
        decision.recommended_fec_ratio = 0.20;  // 20% FEC
    } else {
        current_fps_ = 30;
        current_resolution_ = {854, 480};       // 480p
        decision.recommended_fec_ratio = 0.35;  // 35% FEC for high loss links
    }

    decision.target_bitrate_kbps = current_bitrate_kbps_;
    decision.target_fps = current_fps_;
    decision.target_resolution = current_resolution_;
    decision.should_downscale = (current_resolution_.width < base_resolution_.width);
    decision.should_drop_frame = (current_queue_size > 12);

    return decision;
}

} // namespace dav
