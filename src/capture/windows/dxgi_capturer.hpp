#pragma once

#include "src/capture/capturer.hpp"
#include "src/core/config.hpp"
#include <atomic>
#include <thread>
#include <mutex>

#if defined(_WIN32)
#include <d3d11.h>
#include <dxgi1_2.h>
#include <wrl/client.h>
#endif

namespace dav {

class DxgiCapturer : public ICapturer {
public:
    explicit DxgiCapturer(const CaptureConfig& config);
    ~DxgiCapturer() override;

    VoidResult start() override;
    void stop() override;
    [[nodiscard]] bool is_capturing() const noexcept override;

    void set_frame_callback(FrameCallback cb) override;
    [[nodiscard]] Resolution get_resolution() const noexcept override;
    [[nodiscard]] uint32_t get_target_fps() const noexcept override;
    void set_target_fps(uint32_t fps) override;

    [[nodiscard]] std::string_view get_backend_name() const noexcept override {
        return "DXGI_Desktop_Duplication";
    }

private:
    VoidResult init_d3d11();
    VoidResult init_duplication();
    void capture_loop();
    void cleanup();

    CaptureConfig config_;
    std::atomic<bool> running_{false};
    std::thread capture_thread_;
    FrameCallback frame_callback_;

    uint32_t frame_counter_{0};
    Resolution current_resolution_{1920, 1080};

#if defined(_WIN32)
    Microsoft::WRL::ComPtr<ID3D11Device> d3d_device_;
    Microsoft::WRL::ComPtr<ID3D11DeviceContext> d3d_context_;
    Microsoft::WRL::ComPtr<IDXGIOutputDuplication> dxgi_dup_;
    Microsoft::WRL::ComPtr<ID3D11Texture2D> staging_texture_;
#endif
};

} // namespace dav
