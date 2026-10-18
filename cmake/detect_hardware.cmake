# cmake/detect_hardware.cmake
# Hardware acceleration & GPU detection module for DA-V

message(STATUS "[DA-V] Scanning hardware acceleration capabilities...")

set(DAV_HAS_CUDA OFF)
set(DAV_HAS_NVENC OFF)
set(DAV_HAS_QSV OFF)
set(DAV_HAS_AMF OFF)

# 1. NVIDIA CUDA & NVENC Detection
find_package(CUDAToolkit QUIET)
if(CUDAToolkit_FOUND)
    set(DAV_HAS_CUDA ON)
    message(STATUS "[DA-V] CUDA Toolkit found (v${CUDAToolkit_VERSION})")
    
    find_library(NVENC_LIB NAMES nvEncodeAPI nvEncodeAPI64 PATHS ${CUDAToolkit_LIBRARY_DIR} "C:/Program Files/NVIDIA GPU Computing Toolkit/CUDA/lib/x64")
    if(NVENC_LIB OR EXISTS "C:/Windows/System32/nvEncodeAPI64.dll")
        set(DAV_HAS_NVENC ON)
        message(STATUS "[DA-V] NVIDIA NVENC hardware encoder detected and enabled")
    endif()
else()
    # Check if NVIDIA Driver NVENC DLL exists on Windows
    if(WIN32 AND EXISTS "C:/Windows/System32/nvEncodeAPI64.dll")
        set(DAV_HAS_NVENC ON)
        message(STATUS "[DA-V] NVIDIA Driver detected (nvEncodeAPI64.dll present) — NVENC runtime enabled")
    endif()
endif()

# 2. Intel QuickSync (QSV)
if(WIN32)
    if(EXISTS "C:/Windows/System32/libmfx64.dll")
        set(DAV_HAS_QSV ON)
        message(STATUS "[DA-V] Intel QuickSync (QSV) detected")
    endif()
endif()

# 3. AMD AMF
if(WIN32)
    if(EXISTS "C:/Windows/System32/amfrt64.dll")
        set(DAV_HAS_AMF ON)
        message(STATUS "[DA-V] AMD AMF detected")
    endif()
endif()

# Summary
if(DAV_HAS_NVENC)
    add_compile_definitions(DAV_ENABLE_NVENC=1)
endif()
if(DAV_HAS_QSV)
    add_compile_definitions(DAV_ENABLE_QSV=1)
endif()
if(DAV_HAS_AMF)
    add_compile_definitions(DAV_ENABLE_AMF=1)
endif()

message(STATUS "[DA-V] Hardware acceleration status: NVENC=${DAV_HAS_NVENC}, QSV=${DAV_HAS_QSV}, AMF=${DAV_HAS_AMF}")
