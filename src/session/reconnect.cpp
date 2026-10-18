#include "src/session/reconnect.hpp"
#include <algorithm>

namespace dav {

ReconnectHandler::ReconnectHandler(
    uint32_t initial_delay_ms,
    uint32_t max_delay_ms,
    uint32_t max_attempts,
    double backoff_multiplier
) : initial_delay_ms_(initial_delay_ms),
    max_delay_ms_(max_delay_ms),
    max_attempts_(max_attempts),
    backoff_multiplier_(backoff_multiplier),
    current_delay_ms_(initial_delay_ms),
    rng_(std::random_device{}()) {
}

void ReconnectHandler::reset() {
    attempts_ = 0;
    current_delay_ms_ = initial_delay_ms_;
}

bool ReconnectHandler::should_retry() const noexcept {
    return attempts_ < max_attempts_;
}

void ReconnectHandler::record_failure() {
    attempts_++;
    double next_delay = current_delay_ms_ * backoff_multiplier_;
    current_delay_ms_ = std::min(static_cast<uint32_t>(next_delay), max_delay_ms_);
}

uint32_t ReconnectHandler::get_next_delay_ms() {
    // Add ±15% full jitter to prevent thundering herd
    std::uniform_real_distribution<double> dist(0.85, 1.15);
    double jittered = current_delay_ms_ * dist(rng_);
    return static_cast<uint32_t>(std::clamp(jittered, static_cast<double>(initial_delay_ms_), static_cast<double>(max_delay_ms_)));
}

} // namespace dav
