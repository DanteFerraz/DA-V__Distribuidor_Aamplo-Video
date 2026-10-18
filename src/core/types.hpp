#pragma once

#include <cstdint>
#include <cstddef>
#include <string>
#include <vector>
#include <span>
#include <memory>
#include <chrono>

namespace dav {

using Byte = uint8_t;
using Buffer = std::vector<Byte>;
using ConstByteSpan = std::span<const Byte>;
using MutableByteSpan = std::span<Byte>;

using Microseconds = std::chrono::microseconds;
using Milliseconds = std::chrono::milliseconds;
using SteadyClock = std::chrono::steady_clock;
using TimePoint = std::chrono::time_point<SteadyClock>;

struct Resolution {
    uint32_t width{1920};
    uint32_t height{1080};

    [[nodiscard]] constexpr size_t pixel_count() const noexcept {
        return static_cast<size_t>(width) * height;
    }

    [[nodiscard]] constexpr bool is_valid() const noexcept {
        return width > 0 && height > 0;
    }

    auto operator<=>(const Resolution&) const = default;
};

enum class PixelFormat : uint8_t {
    BGRA,
    RGBA,
    NV12,
    I420,
    YUY2
};

enum class CodecType : uint8_t {
    H264,
    H265,
    AV1
};

enum class HardwareVendor : uint8_t {
    None,
    NVIDIA,
    Intel,
    AMD
};

enum class TransportMode : uint8_t {
    KCP,
    DirectUDP,
    QUIC
};

enum class SessionState : uint8_t {
    Disconnected,
    Resolving,
    Connecting,
    Handshake,
    Streaming,
    Reconnecting,
    Closed
};

} // namespace dav
