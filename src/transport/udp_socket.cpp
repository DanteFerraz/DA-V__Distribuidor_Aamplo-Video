#include "src/transport/udp_socket.hpp"
#include "src/core/logger.hpp"
#include <cstring>
#include <mutex>

namespace dav {

static std::once_flag g_wsa_init_flag;

void UdpSocket::ensure_sockets_initialized() {
#if defined(_WIN32)
    std::call_once(g_wsa_init_flag, []() {
        WSADATA wsa_data;
        int res = WSAStartup(MAKEWORD(2, 2), &wsa_data);
        if (res != 0) {
            log::error("WSAStartup failed with error: {}", res);
        } else {
            log::debug("Winsock2 initialized successfully.");
        }
    });
#endif
}

UdpSocket::UdpSocket() {
    ensure_sockets_initialized();
    socket_ = ::socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP);
    if (socket_ == InvalidSocket) {
        log::error("Failed to create UDP socket");
    }
}

UdpSocket::~UdpSocket() {
    close();
}

UdpSocket::UdpSocket(UdpSocket&& other) noexcept 
    : socket_(other.socket_), dest_addr_(other.dest_addr_), has_dest_(other.has_dest_), bound_port_(other.bound_port_) {
    other.socket_ = InvalidSocket;
    other.has_dest_ = false;
    other.bound_port_ = 0;
}

UdpSocket& UdpSocket::operator=(UdpSocket&& other) noexcept {
    if (this != &other) {
        close();
        socket_ = other.socket_;
        dest_addr_ = other.dest_addr_;
        has_dest_ = other.has_dest_;
        bound_port_ = other.bound_port_;
        other.socket_ = InvalidSocket;
        other.has_dest_ = false;
        other.bound_port_ = 0;
    }
    return *this;
}

void UdpSocket::close() {
    if (socket_ != InvalidSocket) {
#if defined(_WIN32)
        ::closesocket(socket_);
#else
        ::close(socket_);
#endif
        socket_ = InvalidSocket;
        has_dest_ = false;
        bound_port_ = 0;
    }
}

VoidResult UdpSocket::bind(uint16_t port, std::string_view ip) {
    if (socket_ == InvalidSocket) {
        return make_error(ErrorCode::SocketError, "Socket is invalid");
    }

    sockaddr_in addr{};
    addr.sin_family = AF_INET;
    addr.sin_port = htons(port);

    if (ip == "0.0.0.0" || ip.empty()) {
        addr.sin_addr.s_addr = INADDR_ANY;
    } else {
        if (inet_pton(AF_INET, std::string(ip).c_str(), &addr.sin_addr) <= 0) {
            return make_error(ErrorCode::InvalidParameter, std::format("Invalid bind IP: {}", ip));
        }
    }

    // Set reuse address
    int reuse = 1;
    setsockopt(socket_, SOL_SOCKET, SO_REUSEADDR, reinterpret_cast<const char*>(&reuse), sizeof(reuse));

    if (::bind(socket_, reinterpret_cast<sockaddr*>(&addr), sizeof(addr)) != 0) {
        return make_error(ErrorCode::SocketError, std::format("Failed to bind UDP socket on port {}", port));
    }

    bound_port_ = port;
    log::debug("UDP Socket bound to {}:{}", ip, port);
    return {};
}

VoidResult UdpSocket::set_destination(std::string_view host, uint16_t port) {
    std::memset(&dest_addr_, 0, sizeof(dest_addr_));
    dest_addr_.sin_family = AF_INET;
    dest_addr_.sin_port = htons(port);

    if (inet_pton(AF_INET, std::string(host).c_str(), &dest_addr_.sin_addr) <= 0) {
        return make_error(ErrorCode::InvalidParameter, std::format("Invalid remote host address: {}", host));
    }

    has_dest_ = true;
    return {};
}

VoidResult UdpSocket::set_nonblocking(bool nonblocking) {
    if (socket_ == InvalidSocket) return make_error(ErrorCode::SocketError, "Socket is invalid");

#if defined(_WIN32)
    u_long mode = nonblocking ? 1 : 0;
    if (ioctlsocket(socket_, FIONBIO, &mode) != 0) {
        return make_error(ErrorCode::SocketError, "Failed to set non-blocking mode on Windows socket");
    }
#else
    int flags = fcntl(socket_, F_GETFL, 0);
    if (flags == -1) return make_error(ErrorCode::SocketError, "Failed to get socket flags");
    flags = nonblocking ? (flags | O_NONBLOCK) : (flags & ~O_NONBLOCK);
    if (fcntl(socket_, F_SETFL, flags) != 0) {
        return make_error(ErrorCode::SocketError, "Failed to set non-blocking mode on POSIX socket");
    }
#endif
    return {};
}

VoidResult UdpSocket::set_dscp(uint8_t dscp_val) {
    if (socket_ == InvalidSocket) return make_error(ErrorCode::SocketError, "Socket is invalid");
    int tos = static_cast<int>(dscp_val << 2);
    int res = setsockopt(socket_, IPPROTO_IP, IP_TOS, reinterpret_cast<const char*>(&tos), sizeof(tos));
    if (res != 0) {
        log::warn("Failed to set IP_TOS/DSCP field on socket");
    }
    return {};
}

VoidResult UdpSocket::set_buffer_sizes(int snd_buf_size, int rcv_buf_size) {
    if (socket_ == InvalidSocket) return make_error(ErrorCode::SocketError, "Socket is invalid");
    setsockopt(socket_, SOL_SOCKET, SO_SNDBUF, reinterpret_cast<const char*>(&snd_buf_size), sizeof(snd_buf_size));
    setsockopt(socket_, SOL_SOCKET, SO_RCVBUF, reinterpret_cast<const char*>(&rcv_buf_size), sizeof(rcv_buf_size));
    return {};
}

Result<size_t> UdpSocket::send(ConstByteSpan data) {
    if (socket_ == InvalidSocket) return make_error(ErrorCode::SocketError, "Socket invalid");
    if (!has_dest_) return make_error(ErrorCode::InvalidParameter, "Destination not set");

    int res = ::sendto(
        socket_,
        reinterpret_cast<const char*>(data.data()),
        static_cast<int>(data.size()),
        0,
        reinterpret_cast<const sockaddr*>(&dest_addr_),
        sizeof(dest_addr_)
    );

    if (res < 0) {
#if defined(_WIN32)
        int err = WSAGetLastError();
        if (err == WSAEWOULDBLOCK) return size_t{0};
#else
        if (errno == EWOULDBLOCK || errno == EAGAIN) return size_t{0};
#endif
        return make_error(ErrorCode::SocketError, std::format("UDP send error: {}", res));
    }
    return static_cast<size_t>(res);
}

Result<size_t> UdpSocket::send_to(ConstByteSpan data, std::string_view host, uint16_t port) {
    if (socket_ == InvalidSocket) return make_error(ErrorCode::SocketError, "Socket invalid");

    sockaddr_in target_addr{};
    target_addr.sin_family = AF_INET;
    target_addr.sin_port = htons(port);
    if (inet_pton(AF_INET, std::string(host).c_str(), &target_addr.sin_addr) <= 0) {
        return make_error(ErrorCode::InvalidParameter, "Invalid destination IP");
    }

    int res = ::sendto(
        socket_,
        reinterpret_cast<const char*>(data.data()),
        static_cast<int>(data.size()),
        0,
        reinterpret_cast<const sockaddr*>(&target_addr),
        sizeof(target_addr)
    );

    if (res < 0) {
#if defined(_WIN32)
        int err = WSAGetLastError();
        if (err == WSAEWOULDBLOCK) return size_t{0};
#else
        if (errno == EWOULDBLOCK || errno == EAGAIN) return size_t{0};
#endif
        return make_error(ErrorCode::SocketError, "UDP sendto failed");
    }
    return static_cast<size_t>(res);
}

Result<size_t> UdpSocket::receive(MutableByteSpan buffer, std::string* from_ip, uint16_t* from_port) {
    if (socket_ == InvalidSocket) return make_error(ErrorCode::SocketError, "Socket invalid");

    sockaddr_in from_addr{};
    socklen_t from_len = sizeof(from_addr);

    int res = ::recvfrom(
        socket_,
        reinterpret_cast<char*>(buffer.data()),
        static_cast<int>(buffer.size()),
        0,
        reinterpret_cast<sockaddr*>(&from_addr),
        &from_len
    );

    if (res < 0) {
#if defined(_WIN32)
        int err = WSAGetLastError();
        if (err == WSAEWOULDBLOCK) return size_t{0};
#else
        if (errno == EWOULDBLOCK || errno == EAGAIN) return size_t{0};
#endif
        return make_error(ErrorCode::SocketError, "UDP recvfrom failed");
    }

    if (from_ip) {
        char ip_str[INET_ADDRSTRLEN];
        inet_ntop(AF_INET, &from_addr.sin_addr, ip_str, INET_ADDRSTRLEN);
        *from_ip = ip_str;
    }
    if (from_port) {
        *from_port = ntohs(from_addr.sin_port);
    }

    return static_cast<size_t>(res);
}

} // namespace dav
