#include <windows.h>
#include "core.hpp"
#include <algorithm>
#include <chrono>
#include <iomanip>
#include <iostream>

using namespace fluidgateway;
static std::uint64_t cycles() {
    ULONG64 value = 0;
    if (!QueryProcessCycleTime(GetCurrentProcess(), &value))
        throw std::runtime_error("Cannot read CPU cycles.");
    return value;
}
int main() {
    try {
        std::vector<double> latencies;
        latencies.reserve(32768);
        std::size_t peak = 0;
        std::uint64_t start_cycles = 0;
        auto started = std::chrono::steady_clock::now();
        for (unsigned session = 0; session < 69; ++session) {
            if (session == 5) {
                start_cycles = cycles();
                started = std::chrono::steady_clock::now();
            }
            State state;
            state.register_resource("ram", 1, {});
            state.register_resource("vram", 2, {});
            for (unsigned i = 0; i < 512; ++i) {
                Operation op;
                op.id = std::to_string(i);
                op.frame = 0;
                op.source = "ram";
                op.target = i % 64 == 0 ? "ram" : "vram";
                op.type = i % 64 == 0 ? 6 : 4;
                op.bytes = 4194304;
                op.microseconds = 300;
                op.queue = 2;
                const auto start = std::chrono::steady_clock::now();
                const auto decision = state.process(op);
                const auto elapsed = std::chrono::duration<double, std::micro>(
                                         std::chrono::steady_clock::now() - start)
                                         .count();
                if (decision.opcode != (i % 64 < 2 ? 0 : 2))
                    throw std::runtime_error("Decision mismatch.");
                if (session >= 5)
                    latencies.push_back(elapsed);
            }
            peak = std::max(peak, state.budget.peak);
        }
        const auto used_cycles = cycles() - start_cycles;
        const auto elapsed =
            std::chrono::duration<double>(std::chrono::steady_clock::now() - started).count();
        std::sort(latencies.begin(), latencies.end());
        auto percentile = [&](double p) {
            const auto position = (latencies.size() - 1) * p;
            const auto index = static_cast<std::size_t>(position);
            return latencies[index] +
                   (latencies[std::min(index + 1, latencies.size() - 1)] - latencies[index]) *
                       (position - index);
        };
        std::cout << std::setprecision(12) << "{\"operations\":" << latencies.size()
                  << ",\"p50_us\":" << percentile(.5) << ",\"p95_us\":" << percentile(.95)
                  << ",\"p99_us\":" << percentile(.99) << ",\"cpu_cycles_per_operation\":"
                  << static_cast<double>(used_cycles) / latencies.size()
                  << ",\"peak_state_bytes\":" << peak
                  << ",\"operations_per_second\":" << latencies.size() / elapsed << "}\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
