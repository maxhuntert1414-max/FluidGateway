#pragma once
#include "core.hpp"
#include <array>
#include <span>

namespace fluidgateway {
using Bytes = std::vector<std::uint8_t>;
using Identity = std::array<std::uint8_t, 16>;
inline constexpr std::size_t header_size = 56, max_payload = 65535;
inline constexpr std::string_view native_version = "0.69.0";
inline constexpr std::string_view base_hash =
    "0d24d96aec32d74e123f9e198e51adde74ddf190e8c40b0ac18bddf5c4108b2f";
inline constexpr std::string_view batch_hash =
    "bf8727c22ac878ceff6dd0f462d6db5e81174737e839ecdf2e263a6f55268542";
struct Frame {
    std::uint8_t kind = 1, opcode = 0, subject = 0, decision = 0, flags = 0;
    std::uint64_t sequence = 1;
    Identity message{}, session{};
    Bytes payload;
};
std::string hex(std::span<const std::uint8_t> bytes);
Bytes unhex(std::string_view text);
Frame decode_frame(std::span<const std::uint8_t> bytes);
Bytes encode_frame(const Frame& frame);
std::size_t encode_frame_into(const Frame& frame, std::span<std::uint8_t> destination);
std::uint32_t payload_size(std::span<const std::uint8_t> header);
class ProtocolSession {
public:
    explicit ProtocolSession(Identity id) : identity_(id) {}
    Frame process(const Frame& request);
    bool closed = false;
    State state;

private:
    Identity identity_;
    bool negotiated_ = false, batch_ = false;
    std::uint64_t sequence_ = 1, capabilities_ = 0;
    Frame respond(const Frame& request,
                  std::uint8_t opcode,
                  Bytes payload,
                  std::uint8_t decision = 0,
                  bool ok = true) const;
    Frame handle(const Frame& request);
    Decision event(std::uint8_t subject, std::span<const std::uint8_t> payload);
};
} // namespace fluidgateway
