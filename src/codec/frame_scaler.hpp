#pragma once

#include "src/core/types.hpp"
#include "src/core/result.hpp"
#include <vector>

namespace dav {

class FrameScaler {
public:
    FrameScaler() = default;
    ~FrameScaler() = default;

    // Convert BGRA (4 bytes/pixel) to NV12 (1.5 bytes/pixel)
    static VoidResult bgra_to_nv12(
        ConstByteSpan src_bgra,
        uint32_t width,
        uint32_t height,
        uint32_t src_stride,
        MutableByteSpan dst_nv12,
        uint32_t dst_stride_y,
        uint32_t dst_stride_uv
    );

    // Downscale BGRA frame with bilinear interpolation
    static VoidResult scale_bgra(
        ConstByteSpan src,
        Resolution src_res,
        uint32_t src_stride,
        MutableByteSpan dst,
        Resolution dst_res,
        uint32_t dst_stride
    );
};

} // namespace dav
