#pragma once
#include <cstdint>
#include <memory_resource>
#include <optional>
#include <stdexcept>
#include <string>
#include <string_view>
#include <unordered_map>
#include <vector>

namespace fluidgateway {
inline constexpr std::size_t state_limit = 8 * 1024 * 1024;
inline constexpr std::size_t resource_limit = 4096;
inline constexpr std::size_t operation_limit = 16384;
struct Error : std::runtime_error {
    std::uint16_t code;
    bool fatal;
    Error(std::uint16_t c, const char* message, bool f = false)
        : std::runtime_error(message), code(c), fatal(f) {}
};
class BudgetResource final : public std::pmr::memory_resource {
public:
    std::size_t used = 0, peak = 0;
    std::uint64_t allocation_count = 0, allocated_bytes = 0;

private:
    void* do_allocate(std::size_t bytes, std::size_t alignment) override;
    void do_deallocate(void* p, std::size_t bytes, std::size_t alignment) override;
    bool do_is_equal(const std::pmr::memory_resource& other) const noexcept override {
        return this == &other;
    }
};
struct Operation {
    std::string id, source, target, reason;
    std::vector<std::string> dependencies;
    std::optional<std::uint64_t> frame;
    std::uint64_t bytes = 0;
    std::uint32_t microseconds = 0;
    std::uint8_t type = 0, queue = 0;
};
struct Decision {
    std::uint8_t opcode = 0;
    bool operation = false;
    std::uint64_t saved_us = 0, saved_bytes = 0;
};
struct TextHash {
    using is_transparent = void;
    std::size_t operator()(std::string_view text) const noexcept {
        return std::hash<std::string_view>{}(text);
    }
};
template <class T>
using TextMap = std::pmr::unordered_map<std::pmr::string, T, TextHash, std::equal_to<>>;
struct StoredOperation {
    std::pmr::string id, source, target;
    std::pmr::vector<std::pmr::string> replacements;
    std::optional<std::uint64_t> frame;
    std::uint64_t bytes;
    std::uint8_t queue;
    bool removed = false, eliminated = false;
    StoredOperation(const Operation& op, std::pmr::memory_resource* memory);
};
struct Resource {
    std::pmr::vector<std::pmr::string> aliases;
    std::uint8_t memory;
    const StoredOperation* copy = nullptr;
    const StoredOperation* allocation = nullptr;
    Resource(std::uint8_t layer,
             const std::vector<std::string>& names,
             std::pmr::memory_resource* allocator);
};
class State {
public:
    BudgetResource budget;
    State() : resources_(&budget), operations_(&budget) {}
    State(const State&) = delete;
    State& operator=(const State&) = delete;
    void begin_frame(std::uint64_t frame);
    void end_frame(std::uint64_t frame);
    void end_session() const;
    void register_resource(std::string_view id,
                           std::uint8_t memory,
                           const std::vector<std::string>& aliases);
    void release_resource(std::string_view id);
    Decision process(Operation op);
    std::size_t resource_count() const {
        return resources_.size();
    }
    std::size_t operation_count() const {
        return operations_.size();
    }

private:
    TextMap<Resource> resources_;
    TextMap<StoredOperation> operations_;
    std::optional<std::uint64_t> current_frame_;
    void invalidate(std::string_view id);
};
} // namespace fluidgateway
