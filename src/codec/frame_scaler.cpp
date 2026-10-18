#include "src/codec/frame_scaler.hpp"
#include <algorithm>

namespace dav {

VoidResult FrameScaler::bgra_to_nv12(
    ConstByteSpan src_bgra,
    uint32_t width,
    uint32_t height,
    uint32_t src_stride,
    MutableByteSpan dst_nv12,
    uint32_t dst_stride_y,
    uint32_t dst_stride_uv
) {
    const size_t y_plane_size = static_cast<size_t>(dst_stride_y) * height;
    const size_t uv_plane_size = static_cast<size_t>(dst_stride_uv) * (height / 2);
    if (dst_nv12.size() < y_plane_size + uv_plane_size) {
        return make_error(ErrorCode::BufferUnderflow, "Destination NV12 buffer is too small");
    }

    Byte* y_plane = dst_nv12.data();
    Byte* uv_plane = dst_nv12.data() + y_plane_size;

    for (uint32_t y = 0; y < height; ++y) {
        const Byte* src_row = src_bgra.data() + y * src_stride;
        Byte* y_row = y_plane + y * dst_stride_y;

        for (uint32_t x = 0; x < width; ++x) {
            uint32_t b = src_row[x * 4 + 0];
            uint32_t g = src_row[x * 4 + 1];
            uint32_t r = src_row[x * 4 + 2];

            // BT.601 Y conversion: Y = 0.299R + 0.587G + 0.114B (scaled by 256 for fast integer math)
            uint32_t y_val = ((66 * r + 129 * g + 25 * b + 128) >> 8) + 16;
            y_row[x] = static_cast<Byte>(std::clamp(y_val, 0u, 255u));

            // UV plane (2x2 subsampling)
            if ((y % 2 == 0) && (x % 2 == 0)) {
                Byte* uv_row = uv_plane + (y / 2) * dst_stride_uv;
                uint32_t u_val = ((-38 * r - 74 * g + 112 * b + 128) >> 8) + 128;
                uint32_t v_val = ((112 * r - 94 * g - 18 * b + 128) >> 8) + 128;
                
                uv_row[x] = static_cast<Byte>(std::clamp(u_val, 0u, 255u));
                uv_row[x + 1] = static_cast<Byte>(std::clamp(v_val, 0u, 255u));
            }
        }
    }
    return {};
}

VoidResult FrameScaler::scale_bgra(
    ConstByteSpan src,
    Resolution src_res,
    uint32_t src_stride,
    MutableByteSpan dst,
    Resolution dst_res,
    uint32_t dst_stride
) {
    if (!src_res.is_valid() || !dst_res.is_valid()) {
        return make_error(ErrorCode::InvalidParameter, "Invalid resolution for scaling");
    }

    const float x_ratio = static_cast<float>(src_res.width) / dst_res.width;
    const float y_ratio = static_cast<float>(src_res.height) / dst_res.height;

    for (uint32_t y = 0; y < dst_res.height; ++y) {
        uint32_t src_y = static_cast<uint32_t>(y * y_ratio);
        const Byte* src_row = src.data() + src_y * src_stride;
        Byte* dst_row = dst.data() + y * dst_stride;

        for (uint32_t x = 0; x < dst_res.width; ++x) {
            uint32_t src_x = static_cast<uint32_t>(x * x_ratio);
            const Byte* src_pixel = src_row + src_x * 4;
            Byte* dst_pixel = dst_row + x * 4;

            dst_pixel[0] = src_pixel[0]; // B
            dst_pixel[1] = src_pixel[1]; // G
            dst_pixel[2] = src_pixel[2]; // R
            dst_pixel[3] = src_pixel[3]; // A
        }
    }
    return {};
}

} // namespace dav
