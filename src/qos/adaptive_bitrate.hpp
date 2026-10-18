#pragma once

#include "src/core/types.hpp"
#include "src/transport/bandwidth_estimator.hpp"
#include <cstdint>

namespace dav {

struct AbrDecision {
    uint32_t target_bitrate_kbps{8000};
    uint32_t target_fps{60};
    Resolution target_resolution{1920, 1080};
    bool should_downscale{false};
    bool should_drop_frame{false};
    double recommended_fec_ratio{0.20};
};

class AdaptiveBitrateController {
public:
    AdaptiveBitrateController(
        uint32_t min_bitrate_kbps = 1000,
        uint32_t max_bitrate_kbps = 25000,
        Resolution base_resolution = {1920, 1080}
    );

    AbrDecision evaluate(const BandwidthEstimate& bw_est, uint32_t current_queue_size);
    void reset();

    [[nodiscard]] uint32_t get_current_bitrate_kbps() const noexcept { return current_bitrate_kbps_; }
    [[nodiscard]] uint32_t get_current_fps() const noexcept { return current_fps_; }

private:
    uint32_t min_bitrate_kbps_;
    uint32_t max_bitrate_kbps_;
    Resolution base_resolution_;

    uint32_t current_bitrate_kbps_{8000};
    uint32_t current_fps_{60};
    Resolution current_resolution_{1920, 1080};
};

} // namespace dav
