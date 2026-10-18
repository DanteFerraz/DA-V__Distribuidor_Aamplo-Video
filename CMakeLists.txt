cmake_minimum_required(VERSION 3.28)

project(dav_service
    VERSION 1.0.0
    DESCRIPTION "DA-V: Distribuidor Aamplo - High-Performance Video Distribution Service"
    LANGUAGES C CXX
)

set(CMAKE_CXX_STANDARD 23)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

# Modules and Platform
list(APPEND CMAKE_MODULE_PATH "${CMAKE_CURRENT_SOURCE_DIR}/cmake")
include(cmake/platform.cmake)
include(cmake/detect_hardware.cmake)
include(cmake/dependencies.cmake)

# Source files
set(DAV_CORE_SOURCES
    src/core/config.cpp
    src/core/logger.cpp
    src/transport/udp_socket.cpp
    src/transport/kcp_transport.cpp
    src/transport/bandwidth_estimator.cpp
    src/capture/frame_buffer.cpp
    src/codec/frame_scaler.cpp
    src/codec/sw_encoder.cpp
    src/packetizer/rtp_packetizer.cpp
    src/packetizer/frame_assembler.cpp
    src/crypto/crypto_channel.cpp
    src/qos/fec.cpp
    src/qos/adaptive_bitrate.cpp
    src/qos/jitter_buffer.cpp
    src/qos/nack_handler.cpp
    src/qos/qos_engine.cpp
    src/session/session.cpp
    src/session/session_manager.cpp
    src/session/reconnect.cpp
    src/session/peer_registry.cpp
    src/metrics/metrics_registry.cpp
    src/metrics/http_exporter.cpp
    src/core/dav_api.cpp
    third_party/kcp/ikcp.c
)

# Platform specific capture sources
if(WIN32)
    list(APPEND DAV_CORE_SOURCES
        src/capture/windows/dxgi_capturer.cpp
        src/codec/hw/nvenc_encoder.cpp
    )
elseif(UNIX AND NOT APPLE)
    list(APPEND DAV_CORE_SOURCES
        src/capture/linux/x11_capturer.cpp
        src/codec/hw/nvenc_encoder.cpp
    )
endif()

# Core static library
add_library(dav_core STATIC ${DAV_CORE_SOURCES})
target_include_directories(dav_core PUBLIC
    ${CMAKE_CURRENT_SOURCE_DIR}/include
    ${CMAKE_CURRENT_SOURCE_DIR}/src
    ${CMAKE_CURRENT_SOURCE_DIR}/third_party
    ${CMAKE_CURRENT_SOURCE_DIR}/third_party/kcp
)
target_link_libraries(dav_core PUBLIC ${DAV_PLATFORM_LIBS})

# Core shared library (C-ABI DLL / .so for external frontends)
add_library(dav_shared SHARED ${DAV_CORE_SOURCES})
set_target_properties(dav_shared PROPERTIES OUTPUT_NAME "dav_core")
target_compile_definitions(dav_shared PRIVATE DAV_BUILDING_DLL)
target_include_directories(dav_shared PUBLIC
    ${CMAKE_CURRENT_SOURCE_DIR}/include
    ${CMAKE_CURRENT_SOURCE_DIR}/src
    ${CMAKE_CURRENT_SOURCE_DIR}/third_party
    ${CMAKE_CURRENT_SOURCE_DIR}/third_party/kcp
)
target_link_libraries(dav_shared PUBLIC ${DAV_PLATFORM_LIBS})

# Service Daemon Executable
add_executable(dav_daemon src/core/main.cpp)
target_link_libraries(dav_daemon PRIVATE dav_core)

# Tests & Benchmarks
enable_testing()
add_subdirectory(tests)
