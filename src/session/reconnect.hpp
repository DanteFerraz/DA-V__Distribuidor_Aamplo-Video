#pragma once

#include "src/core/types.hpp"
#include <cstdint>
#include <random>

namespace dav {

class ReconnectHandler {
public:
    explicit ReconnectHandler(
        uint32_t initial_delay_ms = 500,
        uint32_t max_delay_ms = 10000,
        uint32_t max_attempts = 10,
        double backoff_multiplier = 1.5
    );

    bool should_retry() const noexcept;
    uint32_t get_next_delay_ms();
    void record_failure();
    void reset();

    [[nodiscard]] uint32_t get_attempt_count() const noexcept { return attempts_; }
    [[nodiscard]] bool is_exhausted() const noexcept { return attempts_ >= max_attempts_; }

private:
    uint32_t initial_delay_ms_;
    uint32_t max_delay_ms_;
    uint32_t max_attempts_;
    double backoff_multiplier_;

    uint32_t attempts_{0};
    uint32_t current_delay_ms_;
    std::mt19937 rng_;
};

} // namespace dav
