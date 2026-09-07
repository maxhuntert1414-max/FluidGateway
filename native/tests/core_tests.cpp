#include "protocol.hpp"
#include <functional>
#include <iostream>
#include <limits>

using namespace fluidgateway;
static void check(bool value, const char* message) {
    if (!value)
        throw std::runtime_error(message);
}
static void rejected(const std::function<void()>& action, bool fatal = false) {
    try {
        action();
    } catch (const Error& e) {
        check(e.fatal == fatal, "wrong fatality");
        return;
    }
    throw std::runtime_error("expected rejection");
}
static Operation copy(std::string id, std::string source = "ram", std::string target = "vram") {
    Operation op;
    op.id = std::move(id);
    op.source = std::move(source);
    op.target = std::move(target);
    op.type = 4;
    op.queue = 2;
    op.frame = 0;
    op.bytes = 1024;
    op.microseconds = 300;
    return op;
}
static void run_tests() {
    State state;
    state.register_resource("ram", 1, {});
    state.register_resource("vram", 2, {});
    check(state.process(copy("a")).opcode == 0, "seed");
    check(state.process(copy("b")).opcode == 2, "duplicate");
    Operation wait;
    wait.id = "wait";
    wait.type = 2;
    wait.dependencies = {"b"};
    wait.microseconds = 1;
    check(state.process(wait).opcode == 0, "retained copy still needs wait");
    Operation write;
    write.id = "write";
    write.type = 6;
    write.target = "ram";
    state.process(write);
    check(state.process(copy("c")).opcode == 0, "write invalidates source");
    rejected([&] { state.process(copy("c")); });
    rejected([&] { state.register_resource("ram", 1, {}); });
    check(state.process(copy("self", "ram", "ram")).opcode == 1, "self copy");
    wait.id = "orphan";
    wait.dependencies = {"self"};
    check(state.process(wait).opcode == 4, "orphan");
    auto self = copy("self-dependency", "ram", "ram");
    self.dependencies = {self.id};
    state.process(self);
    wait.id = "self-wait";
    wait.dependencies = {self.id};
    check(state.process(wait).opcode == 0, "self dependency must not disappear");
    check(state.process(copy("unknown", "missing", "missing")).opcode == 0, "unknown endpoints");
    state.release_resource("vram");
    state.register_resource("vram", 2, {});
    check(state.process(copy("fresh")).opcode == 0, "release invalidates");
    auto different = copy("queue");
    different.queue = 3;
    check(state.process(different).opcode == 0, "different queue");
    different.id = "frame";
    different.frame = 1;
    check(state.process(different).opcode == 0, "different frame");
    state.begin_frame(0);
    rejected([&] { state.begin_frame(1); });
    rejected([&] { state.end_session(); });
    rejected([&] { state.end_frame(1); });
    state.end_frame(0);
    state.end_session();
    State alias;
    alias.register_resource("ram", 1, {"a"});
    alias.register_resource("view", 1, {"a", "b"});
    alias.register_resource("view2", 1, {"b"});
    alias.register_resource("vram", 2, {});
    alias.process(copy("a"));
    write.id = "write";
    write.target = "view2";
    alias.process(write);
    check(alias.process(copy("b")).opcode == 0, "transitive aliases");
    State allocation;
    allocation.register_resource("vram", 2, {});
    auto alloc = copy("alloc");
    alloc.type = 3;
    alloc.reason = "transient";
    allocation.process(alloc);
    alloc.id = "reuse";
    check(allocation.process(alloc).opcode == 6, "allocation reuse");
    alloc.id = "resize";
    alloc.bytes = 2048;
    check(allocation.process(alloc).opcode == 0, "resize");
    alloc.id = "old-size";
    alloc.bytes = 1024;
    check(allocation.process(alloc).opcode == 0, "old allocation retired");
    State precise;
    precise.register_resource("ram", 1, {});
    precise.register_resource("vram", 2, {});
    auto large = copy("large");
    large.bytes = (std::uint64_t{1} << 53);
    precise.process(large);
    ++large.bytes;
    large.id = "adjacent";
    check(precise.process(large).opcode == 0, "integer precision");
    large.id = "maximum";
    large.bytes = std::numeric_limits<std::uint64_t>::max();
    precise.process(large);
    large.id = "maximum-duplicate";
    check(precise.process(large).saved_bytes == large.bytes, "u64 exact saving");
    State limits;
    for (std::size_t i = 0; i < operation_limit; ++i) {
        Operation op;
        op.id = std::to_string(i);
        op.type = 5;
        limits.process(op);
    }
    rejected(
        [&] {
            Operation op;
            op.id = "overflow";
            limits.process(op);
        },
        true);
    check(limits.budget.peak <= state_limit, "operation state bound");
    State resources;
    for (std::size_t i = 0; i < resource_limit; ++i)
        resources.register_resource(std::to_string(i), 1, {});
    rejected([&] { resources.register_resource("overflow", 1, {}); }, true);
    BudgetResource memory;
    auto* block = memory.allocate(state_limit);
    rejected([&] { (void)memory.allocate(1); }, true);
    memory.deallocate(block, state_limit);
    check(memory.used == 0, "budget release");
    std::cout << "Native state regression checks passed\n";
}
int main(int argc, char** argv) {
    try {
        if (argc == 2 && std::string_view(argv[1]) == "--roundtrip") {
            std::string line;
            while (std::getline(std::cin, line)) {
                try {
                    std::cout << hex(encode_frame(decode_frame(unhex(line)))) << '\n';
                } catch (const Error&) {
                    std::cout << "error\n";
                }
            }
        } else if (argc == 2 && std::string_view(argv[1]) == "--replay") {
            Identity id{};
            for (std::size_t i = 0; i < id.size(); ++i)
                id[i] = static_cast<std::uint8_t>(17 + i);
            ProtocolSession session(id);
            std::string line;
            while (std::getline(std::cin, line)) {
                try {
                    std::cout << hex(encode_frame(session.process(decode_frame(unhex(line)))))
                              << '\n';
                } catch (const Error&) {
                    std::cout << "error\n";
                }
            }
            std::cerr << "peak_state_bytes=" << session.state.budget.peak << '\n';
        } else
            run_tests();
        return 0;
    } catch (const std::exception& e) {
        std::cerr << e.what() << '\n';
        return 1;
    }
}
