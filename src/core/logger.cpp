#include "src/core/logger.hpp"
#include <chrono>
#include <iomanip>

namespace dav::log {

Logger& Logger::instance() {
    static Logger logger;
    return logger;
}

void Logger::set_level(Level lvl) noexcept {
    std::lock_guard<std::mutex> lock(mutex_);
    current_level_ = lvl;
}

Level Logger::get_level() const noexcept {
    return current_level_;
}

void Logger::write_log(Level lvl, std::string_view msg) {
    std::lock_guard<std::mutex> lock(mutex_);
    
    const auto now = std::chrono::system_clock::now();
    const auto time_t_now = std::chrono::system_clock::to_time_t(now);
    const auto ms = std::chrono::duration_cast<std::chrono::milliseconds>(now.time_since_epoch()) % 1000;

    std::tm tm_buf{};
#if defined(_WIN32)
    localtime_s(&tm_buf, &time_t_now);
#else
    localtime_r(&time_t_now, &tm_buf);
#endif

    const char* lvl_str = "INFO";
    const char* color_code = "\033[0m";
    switch (lvl) {
        case Level::Trace:    lvl_str = "TRACE"; color_code = "\033[90m"; break;
        case Level::Debug:    lvl_str = "DEBUG"; color_code = "\033[36m"; break;
        case Level::Info:     lvl_str = "INFO "; color_code = "\033[32m"; break;
        case Level::Warn:     lvl_str = "WARN "; color_code = "\033[33m"; break;
        case Level::Error:    lvl_str = "ERROR"; color_code = "\033[31m"; break;
        case Level::Critical: lvl_str = "CRIT "; color_code = "\033[1;31m"; break;
    }

    std::cout << std::format("{}[{:04d}-{:02d}-{:02d} {:02d}:{:02d}:{:02d}.{:03d}] [{}] {}\033[0m\n",
        color_code,
        tm_buf.tm_year + 1900, tm_buf.tm_mon + 1, tm_buf.tm_mday,
        tm_buf.tm_hour, tm_buf.tm_min, tm_buf.tm_sec,
        static_cast<int>(ms.count()),
        lvl_str,
        msg
    );
}

} // namespace dav::log
