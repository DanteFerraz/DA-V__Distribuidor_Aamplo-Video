#pragma once

#include "src/core/types.hpp"
#include "src/core/result.hpp"
#include <string>
#include <string_view>
#include <cstdint>

#if defined(_WIN32)
#include <winsock2.h>
#include <ws2tcpip.h>
using SocketHandle = SOCKET;
constexpr SocketHandle InvalidSocket = INVALID_SOCKET;
#else
#include <sys/types.h>
#include <sys/socket.h>
#include <netinet/in.h>
#include <arpa/inet.h>
#include <unistd.h>
#include <fcntl.h>
using SocketHandle = int;
constexpr SocketHandle InvalidSocket = -1;
#endif

namespace dav {

class UdpSocket {
public:
    UdpSocket();
    ~UdpSocket();

    UdpSocket(const UdpSocket&) = delete;
    UdpSocket& operator=(const UdpSocket&) = delete;
    UdpSocket(UdpSocket&& other) noexcept;
    UdpSocket& operator=(UdpSocket&& other) noexcept;

    VoidResult bind(uint16_t port, std::string_view ip = "0.0.0.0");
    VoidResult set_destination(std::string_view host, uint16_t port);
    VoidResult set_nonblocking(bool nonblocking = true);
    VoidResult set_dscp(uint8_t dscp_val);
    VoidResult set_buffer_sizes(int snd_buf_size, int rcv_buf_size);

    Result<size_t> send(ConstByteSpan data);
    Result<size_t> send_to(ConstByteSpan data, std::string_view host, uint16_t port);
    Result<size_t> receive(MutableByteSpan buffer, std::string* from_ip = nullptr, uint16_t* from_port = nullptr);

    void close();
    [[nodiscard]] bool is_valid() const noexcept { return socket_ != InvalidSocket; }
    [[nodiscard]] uint16_t get_bound_port() const noexcept { return bound_port_; }

private:
    static void ensure_sockets_initialized();

    SocketHandle socket_{InvalidSocket};
    sockaddr_in dest_addr_{};
    bool has_dest_{false};
    uint16_t bound_port_{0};
};

} // namespace dav
