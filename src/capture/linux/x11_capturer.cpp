// ==============================================================================
// DA-V: Motor de Captura Nativa X11 com Memória Compartilhada (MIT-SHM)
// Autor: Dante Ferraz (MonoTech)
//
// Racional de Engenharia:
// A função padrão XGetImage transfere o bitmap bruto através de sockets Unix de
// domínio local (IPC), o que para 1080p BGRA significa ~8.3 MB copiados em espaço
// de usuário a cada frame (sobrecarregando CPU e gerando jitter).
// Com a extensão MIT-SHM (XShmGetImage), o servidor X grava os pixels diretamente
// em um segmento de memória compartilhada (shmget/shmat) mapeado no espaço de
// endereçamento virtual do processo, viabilizando captura zero-copy em < 2ms.
// ==============================================================================

#include "src/capture/linux/x11_capturer.hpp"
#include "src/core/logger.hpp"
#include "src/core/time.hpp"
#include <chrono>

namespace dav {

X11Capturer::X11Capturer(const CaptureConfig& config)
    : config_(config), current_resolution_(config.target_resolution) {
#if !defined(DAV_PLATFORM_LINUX)
    synthetic_buffer_.resize(current_resolution_.width * current_resolution_.height * 4, 128);
#endif
}

X11Capturer::~X11Capturer() {
    stop();
}

#if defined(DAV_PLATFORM_LINUX)
bool X11Capturer::init_x11_shm() {
    display_ = XOpenDisplay(nullptr);
    if (!display_) {
        log::error("[X11Capturer] Failed to open default X11 display. Is DISPLAY env set?");
        return false;
    }

    int screen = DefaultScreen(display_);
    root_window_ = RootWindow(display_, screen);

    if (!XShmQueryExtension(display_)) {
        log::error("[X11Capturer] MIT-SHM extension is not available on this X server.");
        XCloseDisplay(display_);
        display_ = nullptr;
        return false;
    }

    XWindowAttributes win_attr;
    XGetWindowAttributes(display_, root_window_, &win_attr);
    current_resolution_.width = static_cast<uint32_t>(win_attr.width);
    current_resolution_.height = static_cast<uint32_t>(win_attr.height);

    ximage_ = XShmCreateImage(
        display_,
        DefaultVisual(display_, screen),
        static_cast<uint32_t>(DefaultDepth(display_, screen)),
        ZPixmap,
        nullptr,
        &shminfo_,
        current_resolution_.width,
        current_resolution_.height
    );

    if (!ximage_) {
        log::error("[X11Capturer] XShmCreateImage failed.");
        XCloseDisplay(display_);
        display_ = nullptr;
        return false;
    }

    shminfo_.shmid = shmget(IPC_PRIVATE, static_cast<size_t>(ximage_->bytes_per_line * ximage_->height), IPC_CREAT | 0777);
    if (shminfo_.shmid < 0) {
        log::error("[X11Capturer] shmget failed for image size {} bytes", ximage_->bytes_per_line * ximage_->height);
        XDestroyImage(ximage_);
        ximage_ = nullptr;
        XCloseDisplay(display_);
        display_ = nullptr;
        return false;
    }

    shminfo_.shmaddr = ximage_->data = static_cast<char*>(shmat(shminfo_.shmid, nullptr, 0));
    if (shminfo_.shmaddr == reinterpret_cast<char*>(-1)) {
        log::error("[X11Capturer] shmat failed.");
        shmctl(shminfo_.shmid, IPC_RMID, nullptr);
        XDestroyImage(ximage_);
        ximage_ = nullptr;
        XCloseDisplay(display_);
        display_ = nullptr;
        return false;
    }

    shminfo_.readOnly = False;
    if (!XShmAttach(display_, &shminfo_)) {
        log::error("[X11Capturer] XShmAttach failed.");
        shmdt(shminfo_.shmaddr);
        shmctl(shminfo_.shmid, IPC_RMID, nullptr);
        XDestroyImage(ximage_);
        ximage_ = nullptr;
        XCloseDisplay(display_);
        display_ = nullptr;
        return false;
    }

    XSync(display_, False);
    shm_attached_ = true;
    shmctl(shminfo_.shmid, IPC_RMID, nullptr); // Marked for removal upon detach

    log::info("[X11Capturer] MIT-SHM initialised for {}x{} (depth={}, stride={})",
              current_resolution_.width, current_resolution_.height,
              win_attr.depth, ximage_->bytes_per_line);
    return true;
}

void X11Capturer::cleanup_x11_shm() {
    if (display_) {
        if (shm_attached_) {
            XShmDetach(display_, &shminfo_);
            shm_attached_ = false;
        }
        if (ximage_) {
            if (shminfo_.shmaddr && shminfo_.shmaddr != reinterpret_cast<char*>(-1)) {
                shmdt(shminfo_.shmaddr);
                shminfo_.shmaddr = nullptr;
            }
            ximage_->data = nullptr; // Prevent double-free in XDestroyImage
            XDestroyImage(ximage_);
            ximage_ = nullptr;
        }
        XCloseDisplay(display_);
        display_ = nullptr;
    }
}
#endif

VoidResult X11Capturer::start() {
    if (running_) return {};

#if defined(DAV_PLATFORM_LINUX)
    if (!init_x11_shm()) {
        log::warn("[X11Capturer] Falling back to synthetic pattern loop in Linux (No X11 display available).");
    } else {
        log::info("[X11Capturer] Starting Linux X11 SHM Capturer for resolution {}x{} @ {} FPS",
                  current_resolution_.width, current_resolution_.height, config_.target_fps);
    }
#else
    log::info("[X11Capturer] Initialized (Host cross-compilation emulation mode)");
#endif

    running_ = true;
    capture_thread_ = std::thread(&X11Capturer::capture_loop, this);
    return {};
}

void X11Capturer::stop() {
    if (!running_) return;
    running_ = false;

    if (capture_thread_.joinable()) {
        capture_thread_.join();
    }

#if defined(DAV_PLATFORM_LINUX)
    cleanup_x11_shm();
#endif
    log::info("[X11Capturer] Stopped.");
}

bool X11Capturer::is_capturing() const noexcept {
    return running_;
}

void X11Capturer::set_frame_callback(FrameCallback cb) {
    frame_callback_ = std::move(cb);
}

Resolution X11Capturer::get_resolution() const noexcept {
    return current_resolution_;
}

uint32_t X11Capturer::get_target_fps() const noexcept {
    return config_.target_fps;
}

void X11Capturer::set_target_fps(uint32_t fps) {
    config_.target_fps = fps > 0 ? fps : 60;
}

void X11Capturer::capture_loop() {
    const auto interval_us = std::chrono::microseconds(1000000 / (config_.target_fps > 0 ? config_.target_fps : 60));

    while (running_) {
        auto start_time = std::chrono::steady_clock::now();

        CapturedFrame frame{};
        frame.frame_index = ++frame_counter_;
        frame.timestamp_us = time::now_microseconds();
        frame.resolution = current_resolution_;
        frame.format = PixelFormat::BGRA;

#if defined(DAV_PLATFORM_LINUX)
        if (display_ && ximage_ && shm_attached_) {
            XShmGetImage(display_, root_window_, ximage_, 0, 0, AllPlanes);
            frame.raw_data = reinterpret_cast<const uint8_t*>(ximage_->data);
            frame.data_size = static_cast<size_t>(ximage_->bytes_per_line * ximage_->height);
            frame.pitch_stride = static_cast<uint32_t>(ximage_->bytes_per_line);
        } else {
            frame.raw_data = synthetic_buffer_.data();
            frame.data_size = synthetic_buffer_.size();
            frame.pitch_stride = current_resolution_.width * 4;
        }
#else
        frame.raw_data = synthetic_buffer_.data();
        frame.data_size = synthetic_buffer_.size();
        frame.pitch_stride = current_resolution_.width * 4;
#endif

        if (frame_callback_) {
            frame_callback_(frame);
        }

        auto elapsed = std::chrono::duration_cast<std::chrono::microseconds>(std::chrono::steady_clock::now() - start_time);
        if (elapsed < interval_us) {
            std::this_thread::sleep_for(interval_us - elapsed);
        }
    }
}

} // namespace dav
