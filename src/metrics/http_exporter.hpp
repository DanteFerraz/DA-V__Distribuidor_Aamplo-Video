#pragma once

#include "src/core/types.hpp"
#include "src/core/result.hpp"
#include <atomic>
#include <thread>
#include <string>

namespace dav {

class HttpMetricsExporter {
public:
    explicit HttpMetricsExporter(uint16_t port = 9200);
    ~HttpMetricsExporter();

    VoidResult start();
    void stop();
    [[nodiscard]] bool is_running() const noexcept { return running_; }

private:
    void server_loop();

    uint16_t port_;
    std::atomic<bool> running_{false};
    std::thread server_thread_;
};

} // namespace dav
