#include "src/metrics/http_exporter.hpp"
#include "src/metrics/metrics_registry.hpp"
#include "src/core/logger.hpp"

#if defined(_WIN32)
#include <winsock2.h>
#include <ws2tcpip.h>
#else
#include <sys/socket.h>
#include <netinet/in.h>
#include <unistd.h>
#endif

namespace dav {

HttpMetricsExporter::HttpMetricsExporter(uint16_t port) : port_(port) {
}

HttpMetricsExporter::~HttpMetricsExporter() {
    stop();
}

VoidResult HttpMetricsExporter::start() {
    if (running_) return {};
    running_ = true;
    server_thread_ = std::thread(&HttpMetricsExporter::server_loop, this);
    log::info("Prometheus HTTP Metrics Exporter started on http://0.0.0.0:{}/metrics", port_);
    return {};
}

void HttpMetricsExporter::stop() {
    if (!running_) return;
    running_ = false;
    if (server_thread_.joinable()) {
        server_thread_.join();
    }
    log::info("Prometheus HTTP Metrics Exporter stopped.");
}

void HttpMetricsExporter::server_loop() {
#if defined(_WIN32)
    SOCKET server_sock = ::socket(AF_INET, SOCK_STREAM, IPPROTO_TCP);
    if (server_sock == INVALID_SOCKET) return;

    int opt = 1;
    setsockopt(server_sock, SOL_SOCKET, SO_REUSEADDR, reinterpret_cast<const char*>(&opt), sizeof(opt));

    sockaddr_in addr{};
    addr.sin_family = AF_INET;
    addr.sin_addr.s_addr = INADDR_ANY;
    addr.sin_port = htons(port_);

    if (::bind(server_sock, reinterpret_cast<sockaddr*>(&addr), sizeof(addr)) != 0) {
        ::closesocket(server_sock);
        return;
    }

    ::listen(server_sock, 5);

    // Set 500ms timeout on accept
    DWORD timeout_ms = 500;
    setsockopt(server_sock, SOL_SOCKET, SO_RCVTIMEO, reinterpret_cast<const char*>(&timeout_ms), sizeof(timeout_ms));

    while (running_) {
        SOCKET client_sock = ::accept(server_sock, nullptr, nullptr);
        if (client_sock != INVALID_SOCKET) {
            char buffer[1024] = {0};
            ::recv(client_sock, buffer, sizeof(buffer) - 1, 0);

            std::string body = MetricsRegistry::instance().export_prometheus_text();
            std::string response = std::format(
                "HTTP/1.1 200 OK\r\n"
                "Content-Type: text/plain; version=0.0.4; charset=utf-8\r\n"
                "Content-Length: {}\r\n"
                "Connection: close\r\n\r\n{}",
                body.size(), body
            );

            ::send(client_sock, response.c_str(), static_cast<int>(response.size()), 0);
            ::closesocket(client_sock);
        }
    }

    ::closesocket(server_sock);
#endif
}

} // namespace dav
