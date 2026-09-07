#include "core.hpp"
#include <algorithm>
#include <array>
#include <cctype>

namespace fluidgateway {
void* BudgetResource::do_allocate(std::size_t bytes, std::size_t alignment) {
    if (bytes > state_limit - used) throw Error(11, "Session state exceeds 8 MiB; reconnect.", true);
    void* p = std::pmr::new_delete_resource()->allocate(bytes, alignment);
    used += bytes;
    peak = std::max(used, peak);
    return p;
}
void BudgetResource::do_deallocate(void* p, std::size_t bytes, std::size_t alignment) {
    std::pmr::new_delete_resource()->deallocate(p, bytes, alignment);
    used -= bytes;
}
StoredOperation::StoredOperation(const Operation& op, std::pmr::memory_resource* memory)
    : id(op.id, memory), source(op.source, memory), target(op.target, memory), replacements(memory),
      frame(op.frame), bytes(op.bytes), queue(op.queue) {}
Resource::Resource(std::uint8_t layer, const std::vector<std::string>& names,
                   std::pmr::memory_resource* allocator) : aliases(allocator), memory(layer) {
    for (const auto& name : names) aliases.emplace_back(name);
}
void State::begin_frame(std::uint64_t frame) {
    if (current_frame_) throw Error(11, "A frame is already open.");
    current_frame_ = frame;
}
void State::end_frame(std::uint64_t frame) {
    if (current_frame_ != frame) throw Error(11, "Frame does not match the open frame.");
    current_frame_.reset();
}
void State::end_session() const {
    if (current_frame_) throw Error(11, "Cannot end session with an open frame.");
}
static bool aliases_intersect(const Resource& a, const Resource& b) {
    if (a.memory != b.memory) return false;
    for (const auto& name : a.aliases)
        if (std::find(b.aliases.begin(), b.aliases.end(), name) != b.aliases.end()) return true;
    return false;
}
void State::register_resource(std::string_view id, std::uint8_t memory,
                              const std::vector<std::string>& aliases) {
    if (resources_.contains(id)) throw Error(11, "Duplicate resource id.");
    if (resources_.size() == resource_limit) throw Error(11, "Resource limit reached; reconnect.", true);
    resources_.try_emplace(std::pmr::string(id, &budget), memory, aliases, &budget);
}
void State::invalidate(std::string_view id) {
    const auto first = resources_.find(id);
    if (first == resources_.end()) {
        for (auto& entry : resources_) entry.second.copy = nullptr;
        return;
    }
    // Traverse alias connectivity, including indirect views, before retiring provenance.
    std::array<const Resource*, resource_limit> affected{};
    std::array<const Resource*, resource_limit> remaining{};
    std::size_t count = 1;
    affected[0] = &first->second;
    std::size_t remaining_count = 0;
    for (const auto& [name, resource] : resources_) {
        (void)name;
        if (&resource != affected[0]) remaining[remaining_count++] = &resource;
    }
    for (std::size_t cursor = 0; cursor < count; ++cursor) {
        for (std::size_t i = 0; i < remaining_count;) {
            if (aliases_intersect(*affected[cursor], *remaining[i])) {
                affected[count++] = remaining[i];
                remaining[i] = remaining[--remaining_count];
            } else ++i;
        }
    }
    for (auto& [name, resource] : resources_) {
        (void)name;
        if (!resource.copy) continue;
        const auto source = resources_.find(std::string_view(resource.copy->source));
        if (std::find(affected.begin(), affected.begin() + count, &resource) != affected.begin() + count ||
            (source != resources_.end() && std::find(affected.begin(), affected.begin() + count,
                &source->second) != affected.begin() + count)) resource.copy = nullptr;
    }
}
void State::release_resource(std::string_view id) {
    invalidate(id);
    const auto found = resources_.find(id);
    if (found != resources_.end()) resources_.erase(found);
}
Decision State::process(Operation op) {
    if (operations_.contains(std::string_view(op.id))) throw Error(11, "Duplicate operation id.");
    if (operations_.size() == operation_limit) throw Error(11, "Operation limit reached; reconnect.", true);
    if (!op.frame) op.frame = current_frame_;
    auto source = resources_.find(std::string_view(op.source));
    auto target = resources_.find(std::string_view(op.target));
    const StoredOperation* retained = nullptr;
    Decision decision{0, true, 0, 0};
    if ((op.type == 1 || op.type == 4) && source != resources_.end() && target != resources_.end()) {
        const auto previous = target->second.copy;
        if (op.source == op.target) decision.opcode = 1;
        else if (aliases_intersect(source->second, target->second)) {
            decision.opcode = 3;
            retained = source->second.copy;
        } else if (previous && previous->source == std::string_view(op.source) &&
                   previous->bytes == op.bytes && previous->frame == op.frame && previous->queue == op.queue) {
            decision.opcode = 2;
            retained = previous;
        }
    } else if (op.type == 2) {
        const bool all_removed = !op.dependencies.empty() && std::all_of(op.dependencies.begin(), op.dependencies.end(),
            [this](const auto& id) {
                const auto found = operations_.find(std::string_view(id));
                return found != operations_.end() && found->second.removed;
            });
        if (all_removed) decision.opcode = 4;
        else if (!op.microseconds && op.dependencies.empty()) decision.opcode = 5;
    } else if (op.type == 3 && target != resources_.end()) {
        const auto previous = target->second.allocation;
        std::transform(op.reason.begin(), op.reason.end(), op.reason.begin(),
            [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
        const bool transient = op.reason.find("transient") != std::string::npos ||
            op.reason.find("scratch") != std::string::npos || op.reason.find("temporary") != std::string::npos ||
            op.reason.find("staging") != std::string::npos;
        if (previous && previous->bytes == op.bytes && previous->frame == op.frame && transient) {
            decision.opcode = 6;
            retained = previous;
        }
    }
    auto [inserted, unused] = operations_.try_emplace(std::pmr::string(op.id, &budget), op, &budget);
    (void)unused;
    auto& stored = inserted->second;
    stored.eliminated = decision.opcode != 0;
    auto append = [&stored](std::string_view id) {
        if (std::find(stored.replacements.begin(), stored.replacements.end(), id) == stored.replacements.end())
            stored.replacements.emplace_back(id);
    };
    if (retained) append(retained->id);
    for (const auto& dependency : op.dependencies) {
        if (!stored.eliminated) break;
        const auto found = operations_.find(std::string_view(dependency));
        if (found != operations_.end() && found != inserted && found->second.eliminated) {
            for (const auto& replacement : found->second.replacements) append(replacement);
        } else append(dependency);
    }
    if (stored.eliminated) {
        stored.removed = stored.replacements.empty();
        decision.saved_us = op.microseconds;
        if (op.type != 2) decision.saved_bytes = op.bytes;
    } else {
        if (op.type == 1 || op.type == 3 || op.type == 4 || op.type == 6 || op.type == 7) invalidate(op.target);
        if (target != resources_.end()) {
            if (op.type == 1 || op.type == 4) target->second.copy = &stored;
            if (op.type == 3) target->second.allocation = &stored;
        }
    }
    return decision;
}
}
