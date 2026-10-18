#pragma once

#include "src/capture/capturer.hpp"
#include "src/core/config.hpp"
#include <atomic>
#include <thread>
#include <vector>

#if defined(DAV_PLATFORM_LINUX)
#include <X11/Xlib.h>
#include <X11/Xutil.h>
#include <X11/extensions/XShm.h>
#include <sys/ipc.h>
#include <sys/shm.h>
#endif

namespace dav {

class X11Capturer : public ICapturer {
public:
    explicit X11Capturer(const CaptureConfig& config);
    ~X11Capturer() override;

    VoidResult start() override;
    void stop() override;
    [[nodiscard]] bool is_capturing() const noexcept override;

    void set_frame_callback(FrameCallback cb) override;
    [[nodiscard]] Resolution get_resolution() const noexcept override;
    [[nodiscard]] uint32_t get_target_fps() const noexcept override;
    void set_target_fps(uint32_t fps) override;

    [[nodiscard]] std::string_view get_backend_name() const noexcept override {
        return "Linux_X11_SHM_Capturer";
    }

private:
    void capture_loop();

    CaptureConfig config_;
    std::atomic<bool> running_{false};
    std::thread capture_thread_;
    FrameCallback frame_callback_;

    uint32_t frame_counter_{0};
    Resolution current_resolution_{1920, 1080};

#if defined(DAV_PLATFORM_LINUX)
    Display* display_{nullptr};
    Window root_window_{0};
    XShmSegmentInfo shminfo_{};
    XImage* ximage_{nullptr};
    bool shm_attached_{false};

    bool init_x11_shm();
    void cleanup_x11_shm();
#else
    std::vector<uint8_t> synthetic_buffer_;
#endif
};

} // namespace dav
