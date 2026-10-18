#pragma once

#include "src/core/types.hpp"
#include "src/core/result.hpp"
#include <functional>
#include <memory>
#include <string_view>
#include <vector>

namespace dav {

struct Rect {
    int32_t left{0};
    int32_t top{0};
    int32_t right{0};
    int32_t bottom{0};

    [[nodiscard]] int32_t width() const noexcept { return right - left; }
    [[nodiscard]] int32_t height() const noexcept { return bottom - top; }
};

struct CapturedFrame {
    uint32_t frame_index{0};
    uint64_t timestamp_us{0};
    Resolution resolution{1920, 1080};
    PixelFormat format{PixelFormat::BGRA};
    uint32_t pitch_stride{0};
    
    // CPU-accessible memory span (if mapped)
    Buffer data;
    
    // Native GPU surface pointer for zero-copy NVENC/Direct3D integration
    void* gpu_surface_ptr{nullptr};
    
    // Dirty rects (regions changed since last frame) for bandwidth optimization
    std::vector<Rect> dirty_rects;
    bool is_keyframe_hint{false};
};

using FrameCallback = std::function<void(const CapturedFrame& frame)>;

class ICapturer {
public:
    virtual ~ICapturer() = default;

    virtual VoidResult start() = 0;
    virtual void stop() = 0;
    [[nodiscard]] virtual bool is_capturing() const noexcept = 0;

    virtual void set_frame_callback(FrameCallback cb) = 0;
    [[nodiscard]] virtual Resolution get_resolution() const noexcept = 0;
    [[nodiscard]] virtual uint32_t get_target_fps() const noexcept = 0;
    virtual void set_target_fps(uint32_t fps) = 0;

    [[nodiscard]] virtual std::string_view get_backend_name() const noexcept = 0;
};

} // namespace dav
