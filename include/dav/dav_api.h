#pragma once

#include <stdint.h>
#include <stddef.h>

#if defined(_WIN32) || defined(__CYGWIN__)
    #if defined(DAV_BUILDING_DLL)
        #define DAV_API __declspec(dllexport)
    #else
        #define DAV_API __declspec(dllimport)
    #endif
#else
    #if defined(DAV_BUILDING_DLL)
        #define DAV_API __attribute__((visibility("default")))
    #else
        #define DAV_API
    #endif
#endif

#ifdef __cplusplus
extern "C" {
#endif

// ============================================================================
// Data Structures
// ============================================================================

typedef enum {
    DAV_SUCCESS = 0,
    DAV_ERROR_INVALID_PARAM = -1,
    DAV_ERROR_INIT_FAILED = -2,
    DAV_ERROR_DEVICE_NOT_FOUND = -3,
    DAV_ERROR_SOCKET_FAILED = -4,
    DAV_ERROR_CRYPTO_FAILED = -5,
    DAV_ERROR_SESSION_CLOSED = -6
} DavErrorCode;

typedef struct {
    uint32_t width;
    uint32_t height;
    uint32_t stride;
    uint64_t timestamp_us;
    const uint8_t* rgba_data;
    size_t data_size;
    int is_keyframe;
} DavRenderFrame;

typedef struct {
    float fps;
    float bitrate_mbps;
    float latency_ms;
    uint64_t packets_sent;
    uint64_t packets_received;
    uint64_t packets_lost;
    uint64_t frames_captured;
    uint64_t frames_rendered;
    int is_connected;
} DavTelemetry;

typedef void (*DavFrameReadyCallback)(const DavRenderFrame* frame, void* user_data);
typedef void (*DavTelemetryCallback)(const DavTelemetry* telemetry, void* user_data);
typedef void (*DavLogCallback)(int level, const char* message, void* user_data);

// ============================================================================
// Core Engine API
// ============================================================================

/**
 * Initializes the DA-V Core Engine with optional configuration path.
 * If config_toml is NULL, defaults are loaded.
 */
DAV_API int dav_init(const char* config_toml);

/**
 * Starts the Video Streaming Sender (Screen Capture -> Encode -> Encrypt -> UDP/KCP).
 */
DAV_API int dav_start_sender(
    const char* target_ip,
    uint16_t target_port,
    const char* pin,
    uint32_t width,
    uint32_t height,
    uint32_t fps
);

/**
 * Starts the Video Streaming Receiver (UDP/KCP -> Decrypt -> Reassembly -> Frame Callback).
 */
DAV_API int dav_start_receiver(
    uint16_t bind_port,
    const char* pin,
    DavFrameReadyCallback on_frame,
    DavTelemetryCallback on_telemetry,
    void* user_data
);

/**
 * Stops any active sender or receiver in the core engine.
 */
DAV_API void dav_stop(void);

/**
 * Requests an immediate IDR keyframe from the active sender.
 */
DAV_API void dav_request_keyframe(void);

/**
 * Retrieves instantaneous telemetry metrics from the active session.
 */
DAV_API int dav_get_telemetry(DavTelemetry* out_telemetry);

/**
 * Registers an optional logging callback for diagnostic logs.
 */
DAV_API void dav_set_log_callback(DavLogCallback cb, void* user_data);

/**
 * Returns the version string of the DA-V Core engine.
 */
DAV_API const char* dav_get_version(void);

#ifdef __cplusplus
}
#endif
