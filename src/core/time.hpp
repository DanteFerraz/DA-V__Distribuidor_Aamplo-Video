#pragma once

#include "src/core/types.hpp"
#include <chrono>

namespace dav::time {

[[nodiscard]] inline uint64_t now_microseconds() noexcept {
    const auto now = std::chrono::steady_clock::now().time_since_epoch();
    return static_cast<uint64_t>(std::chrono::duration_cast<std::chrono::microseconds>(now).count());
}

[[nodiscard]] inline uint32_t now_milliseconds() noexcept {
    const auto now = std::chrono::steady_clock::now().time_since_epoch();
    return static_cast<uint32_t>(std::chrono::duration_cast<std::chrono::milliseconds>(now).count() & 0xFFFFFFFF);
}

[[nodiscard]] inline double now_seconds() noexcept {
    const auto now = std::chrono::steady_clock::now().time_since_epoch();
    return std::chrono::duration<double>(now).count();
}

} // namespace dav::time
