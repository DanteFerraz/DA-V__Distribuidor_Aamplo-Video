#pragma once

#include <expected>
#include <string>
#include <string_view>
#include <format>
#include <system_error>

namespace dav {

enum class ErrorCode : uint32_t {
    Success = 0,
    InvalidParameter,
    OutOfMemory,
    Timeout,
    NotFound,
    AlreadyExists,
    PermissionDenied,
    NotSupported,
    
    // Transport & Network
    SocketError,
    ConnectionFailed,
    ConnectionReset,
    PacketTooLarge,
    BufferOverflow,
    BufferUnderflow,
    CryptoError,
    AuthenticationFailed,
    
    // Capture & Codec
    DeviceNotFound,
    DeviceLost,
    AccessDenied,
    EncoderInitFailed,
    EncodingFailed,
    DecoderInitFailed,
    DecodingFailed,
    
    // Session & Protocol
    ProtocolError,
    SessionNotFound,
    SessionClosed,
    MaxSessionsReached,
    
    Unknown = 9999
};

struct Error {
    ErrorCode code{ErrorCode::Unknown};
    std::string message;

    Error() = default;
    Error(ErrorCode c, std::string_view msg) : code(c), message(msg) {}

    [[nodiscard]] std::string to_string() const {
        return std::format("[Error {:#x}] {}", static_cast<uint32_t>(code), message);
    }
};

template <typename T>
using Result = std::expected<T, Error>;

using VoidResult = std::expected<void, Error>;

inline Error make_error(ErrorCode code, std::string_view message) {
    return Error(code, message);
}

} // namespace dav
