#include "src/capture/windows/dxgi_capturer.hpp"
#include "src/core/logger.hpp"
#include "src/core/time.hpp"

#if defined(_WIN32)
#include <windows.h>
#endif

namespace dav {

DxgiCapturer::DxgiCapturer(const CaptureConfig& config)
    : config_(config), current_resolution_(config.target_resolution) {
}

DxgiCapturer::~DxgiCapturer() {
    stop();
}

VoidResult DxgiCapturer::init_d3d11() {
#if defined(_WIN32)
    D3D_FEATURE_LEVEL feature_levels[] = {
        D3D_FEATURE_LEVEL_11_1,
        D3D_FEATURE_LEVEL_11_0,
        D3D_FEATURE_LEVEL_10_1
    };
    D3D_FEATURE_LEVEL created_feature_level;

    UINT create_flags = D3D11_CREATE_DEVICE_BGRA_SUPPORT;
#if defined(_DEBUG)
    create_flags |= D3D11_CREATE_DEVICE_DEBUG;
#endif

    HRESULT hr = D3D11CreateDevice(
        nullptr,
        D3D_DRIVER_TYPE_HARDWARE,
        nullptr,
        create_flags,
        feature_levels,
        ARRAYSIZE(feature_levels),
        D3D11_SDK_VERSION,
        &d3d_device_,
        &created_feature_level,
        &d3d_context_
    );

    if (FAILED(hr)) {
        log::error("D3D11CreateDevice failed with HRESULT {:#x}", static_cast<uint32_t>(hr));
        return make_error(ErrorCode::DeviceNotFound, "Failed to create D3D11 device for DXGI capture");
    }

    log::debug("D3D11 Device created successfully with feature level {:#x}", static_cast<uint32_t>(created_feature_level));
    return {};
#else
    return make_error(ErrorCode::NotSupported, "DXGI is only supported on Windows");
#endif
}

VoidResult DxgiCapturer::init_duplication() {
#if defined(_WIN32)
    if (!d3d_device_) {
        auto d3d_res = init_d3d11();
        if (!d3d_res.has_value()) return d3d_res;
    }

    Microsoft::WRL::ComPtr<IDXGIDevice> dxgi_device;
    HRESULT hr = d3d_device_.As(&dxgi_device);
    if (FAILED(hr)) return make_error(ErrorCode::DeviceLost, "Failed to query IDXGIDevice");

    Microsoft::WRL::ComPtr<IDXGIAdapter> dxgi_adapter;
    hr = dxgi_device->GetAdapter(&dxgi_adapter);
    if (FAILED(hr)) return make_error(ErrorCode::DeviceLost, "Failed to get DXGI adapter");

    Microsoft::WRL::ComPtr<IDXGIOutput> dxgi_output;
    hr = dxgi_adapter->EnumOutputs(config_.display_index, &dxgi_output);
    if (FAILED(hr)) {
        return make_error(ErrorCode::DeviceNotFound, std::format("Display index {} not found", config_.display_index));
    }

    Microsoft::WRL::ComPtr<IDXGIOutput1> dxgi_output1;
    hr = dxgi_output.As(&dxgi_output1);
    if (FAILED(hr)) return make_error(ErrorCode::NotSupported, "Failed to query IDXGIOutput1");

    DXGI_OUTPUT_DESC output_desc;
    dxgi_output->GetDesc(&output_desc);
    current_resolution_.width = static_cast<uint32_t>(output_desc.DesktopCoordinates.right - output_desc.DesktopCoordinates.left);
    current_resolution_.height = static_cast<uint32_t>(output_desc.DesktopCoordinates.bottom - output_desc.DesktopCoordinates.top);

    hr = dxgi_output1->DuplicateOutput(d3d_device_.Get(), &dxgi_dup_);
    if (FAILED(hr)) {
        log::error("DuplicateOutput failed with HRESULT {:#x}", static_cast<uint32_t>(hr));
        return make_error(ErrorCode::AccessDenied, "Failed to duplicate desktop output (check fullscreen exclusivity/UAC)");
    }

    // Create CPU staging texture for fallback
    D3D11_TEXTURE2D_DESC staging_desc{};
    staging_desc.Width = current_resolution_.width;
    staging_desc.Height = current_resolution_.height;
    staging_desc.MipLevels = 1;
    staging_desc.ArraySize = 1;
    staging_desc.Format = DXGI_FORMAT_B8G8R8A8_UNORM;
    staging_desc.SampleDesc.Count = 1;
    staging_desc.Usage = D3D11_USAGE_STAGING;
    staging_desc.CPUAccessFlags = D3D11_CPU_ACCESS_READ;

    hr = d3d_device_->CreateTexture2D(&staging_desc, nullptr, &staging_texture_);
    if (FAILED(hr)) {
        log::error("Failed to create staging texture for DXGI frame capture");
        return make_error(ErrorCode::OutOfMemory, "Failed to create staging texture");
    }

    log::info("DXGI Desktop Duplication initialized on display {}: {}x{} @ {} FPS",
              config_.display_index, current_resolution_.width, current_resolution_.height, config_.target_fps);
    return {};
#else
    return make_error(ErrorCode::NotSupported, "DXGI is only supported on Windows");
#endif
}

VoidResult DxgiCapturer::start() {
    if (running_) return {};

    auto init_res = init_duplication();
    if (!init_res.has_value()) {
        log::error("DXGI Capturer start failed: {}", init_res.error().message);
        return init_res;
    }

    running_ = true;
    capture_thread_ = std::thread(&DxgiCapturer::capture_loop, this);
    log::info("DXGI Capturer thread started.");
    return {};
}

void DxgiCapturer::stop() {
    if (!running_) return;
    running_ = false;

    if (capture_thread_.joinable()) {
        capture_thread_.join();
    }
    cleanup();
    log::info("DXGI Capturer stopped.");
}

void DxgiCapturer::cleanup() {
#if defined(_WIN32)
    staging_texture_.Reset();
    dxgi_dup_.Reset();
    d3d_context_.Reset();
    d3d_device_.Reset();
#endif
}

bool DxgiCapturer::is_capturing() const noexcept {
    return running_;
}

void DxgiCapturer::set_frame_callback(FrameCallback cb) {
    frame_callback_ = std::move(cb);
}

Resolution DxgiCapturer::get_resolution() const noexcept {
    return current_resolution_;
}

uint32_t DxgiCapturer::get_target_fps() const noexcept {
    return config_.target_fps;
}

void DxgiCapturer::set_target_fps(uint32_t fps) {
    config_.target_fps = fps > 0 ? fps : 60;
}

void DxgiCapturer::capture_loop() {
#if defined(_WIN32)
    const auto frame_interval_us = std::chrono::microseconds(1000000 / (config_.target_fps > 0 ? config_.target_fps : 60));

    while (running_) {
        auto start_time = std::chrono::steady_clock::now();

        DXGI_OUTDUPL_FRAME_INFO frame_info{};
        Microsoft::WRL::ComPtr<IDXGIResource> desktop_resource;

        HRESULT hr = dxgi_dup_->AcquireNextFrame(10, &frame_info, &desktop_resource);

        if (hr == DXGI_ERROR_WAIT_TIMEOUT) {
            // No new frame rendered by desktop compositor, continue pacing
            std::this_thread::sleep_for(std::chrono::milliseconds(1));
            continue;
        }

        if (FAILED(hr)) {
            if (hr == DXGI_ERROR_ACCESS_LOST) {
                log::warn("DXGI Access lost (resolution change or lock screen). Re-initializing...");
                dxgi_dup_.Reset();
                init_duplication();
            }
            continue;
        }

        Microsoft::WRL::ComPtr<ID3D11Texture2D> desktop_texture;
        hr = desktop_resource.As(&desktop_texture);
        if (SUCCEEDED(hr)) {
            CapturedFrame frame{};
            frame.frame_index = ++frame_counter_;
            frame.timestamp_us = time::now_microseconds();
            frame.resolution = current_resolution_;
            frame.format = PixelFormat::BGRA;
            frame.gpu_surface_ptr = desktop_texture.Get(); // Zero-copy GPU pointer for NVENC

            // If CPU mapping is needed, copy to staging
            if (!config_.zero_copy_gpu && staging_texture_) {
                d3d_context_->CopyResource(staging_texture_.Get(), desktop_texture.Get());
                
                D3D11_MAPPED_SUBRESOURCE mapped{};
                if (SUCCEEDED(d3d_context_->Map(staging_texture_.Get(), 0, D3D11_MAP_READ, 0, &mapped))) {
                    frame.pitch_stride = mapped.RowPitch;
                    size_t data_size = static_cast<size_t>(mapped.RowPitch) * current_resolution_.height;
                    frame.data.resize(data_size);
                    std::memcpy(frame.data.data(), mapped.pData, data_size);
                    d3d_context_->Unmap(staging_texture_.Get(), 0);
                }
            }

            if (frame_callback_) {
                frame_callback_(frame);
            }
        }

        dxgi_dup_->ReleaseFrame();

        auto elapsed = std::chrono::duration_cast<std::chrono::microseconds>(std::chrono::steady_clock::now() - start_time);
        if (elapsed < frame_interval_us) {
            std::this_thread::sleep_for(frame_interval_us - elapsed);
        }
    }
#endif
}

} // namespace dav
