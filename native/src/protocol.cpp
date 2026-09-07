#include "protocol.hpp"
#include <algorithm>
#include <limits>

namespace fluidgateway {
namespace {
bool whitespace(std::uint32_t c) {
    return (c >= 9 && c <= 13) || (c >= 28 && c <= 32) || c == 0x85 || c == 0xa0 || c == 0x1680 ||
           (c >= 0x2000 && c <= 0x200a) || c == 0x2028 || c == 0x2029 || c == 0x202f ||
           c == 0x205f || c == 0x3000;
}
std::string_view trimmed_utf8(std::string_view text) {
    std::size_t first = text.size(), last = 0;
    for (std::size_t offset = 0; offset < text.size();) {
        const auto start = offset;
        const auto lead = static_cast<unsigned char>(text[offset++]);
        std::uint32_t cp = lead, minimum = 0;
        unsigned count = 0;
        if (lead >= 0xc2 && lead <= 0xdf) {
            cp &= 31;
            count = 1;
            minimum = 0x80;
        } else if (lead >= 0xe0 && lead <= 0xef) {
            cp &= 15;
            count = 2;
            minimum = 0x800;
        } else if (lead >= 0xf0 && lead <= 0xf4) {
            cp &= 7;
            count = 3;
            minimum = 0x10000;
        } else if (lead > 0x7f)
            throw Error(10, "Invalid UTF-8.");
        while (count--) {
            if (offset == text.size())
                throw Error(10, "Truncated UTF-8.");
            const auto next = static_cast<unsigned char>(text[offset++]);
            if ((next & 0xc0) != 0x80)
                throw Error(10, "Invalid UTF-8 continuation.");
            cp = (cp << 6) | (next & 63);
        }
        if (cp < minimum || cp > 0x10ffff || (cp >= 0xd800 && cp <= 0xdfff))
            throw Error(10, "Invalid UTF-8 scalar.");
        if (!whitespace(cp)) {
            first = std::min(first, start);
            last = offset;
        }
    }
    return last ? text.substr(first, last - first) : std::string_view{};
}
class Reader {
public:
    explicit Reader(std::span<const std::uint8_t> data) : data_(data) {}
    std::span<const std::uint8_t> take(std::size_t n) {
        if (n > data_.size())
            throw Error(10, "Truncated payload.");
        const auto result = data_.first(n);
        data_ = data_.subspan(n);
        return result;
    }
    std::uint64_t integer(std::size_t n) {
        const auto bytes = take(n);
        std::uint64_t result = 0;
        for (std::size_t i = 0; i < n; ++i)
            result |= std::uint64_t(bytes[i]) << (8 * i);
        return result;
    }
    std::uint8_t u8() {
        return static_cast<std::uint8_t>(integer(1));
    }
    std::uint16_t u16() {
        return static_cast<std::uint16_t>(integer(2));
    }
    std::uint32_t u32() {
        return static_cast<std::uint32_t>(integer(4));
    }
    std::uint64_t u64() {
        return integer(8);
    }
    std::uint8_t choice(std::uint8_t low, std::uint8_t high) {
        const auto value = u8();
        if (value < low || value > high)
            throw Error(10, "Invalid enum.");
        return value;
    }
    std::uint8_t mask(std::uint8_t allowed) {
        const auto value = u8();
        if (value & ~allowed)
            throw Error(10, "Invalid presence mask.");
        return value;
    }
    std::string
    text(std::size_t length_bytes, std::size_t maximum, bool empty = false, bool trim = false) {
        const auto n = static_cast<std::size_t>(integer(length_bytes));
        if (n > maximum)
            throw Error(10, "Text exceeds its limit.");
        const auto bytes = take(n);
        const std::string value(bytes.begin(), bytes.end());
        const auto stripped = trimmed_utf8(value);
        if (!empty && stripped.empty())
            throw Error(10, "Blank text.");
        return trim ? std::string(stripped) : value;
    }
    void finish() {
        if (!data_.empty())
            throw Error(10, "Trailing payload bytes.");
    }

private:
    std::span<const std::uint8_t> data_;
};
class Writer {
public:
    Bytes data;
    void integer(std::uint64_t value, std::size_t n) {
        for (std::size_t i = 0; i < n; ++i)
            data.push_back(static_cast<std::uint8_t>(value >> (8 * i)));
    }
    void raw(std::span<const std::uint8_t> value) {
        data.insert(data.end(), value.begin(), value.end());
    }
    void text(std::string_view value, std::size_t n) {
        integer(value.size(), n);
        data.insert(data.end(), value.begin(), value.end());
    }
    void decision(const Decision& result) {
        integer(result.operation ? (result.opcode ? 3 : 7) : 1, 1);
        integer(result.saved_us, 8);
        integer(result.saved_bytes, 8);
    }
};
bool nonzero(std::span<const std::uint8_t> data) {
    return std::any_of(data.begin(), data.end(), [](auto c) { return c != 0; });
}
Operation operation(Reader& reader, bool batch = false) {
    Operation op;
    op.type = reader.choice(1, 7);
    op.queue = reader.choice(0, 5);
    const auto presence = reader.mask(15);
    if (!batch)
        op.id = reader.text(2, 256, false, true);
    if (presence & 1)
        op.source = reader.text(2, 256, false, true);
    if (presence & 2)
        op.target = reader.text(2, 256, false, true);
    if (presence & 4)
        op.reason = reader.text(2, 512);
    op.microseconds = reader.u32();
    op.bytes = reader.u64();
    if (presence & 8)
        op.frame = reader.u64();
    const auto count = reader.choice(0, 32);
    for (unsigned i = 0; i < count; ++i)
        op.dependencies.push_back(reader.text(2, 256));
    reader.finish();
    return op;
}
} // namespace
std::string hex(std::span<const std::uint8_t> bytes) {
    std::string result;
    result.reserve(bytes.size() * 2);
    for (const auto c : bytes) {
        result += "0123456789abcdef"[c >> 4];
        result += "0123456789abcdef"[c & 15];
    }
    return result;
}
Bytes unhex(std::string_view text) {
    if (text.size() % 2)
        throw Error(10, "Odd hex length.");
    Bytes result;
    auto nibble = [](char c) -> unsigned {
        if (c >= '0' && c <= '9')
            return static_cast<unsigned>(c - '0');
        if (c >= 'a' && c <= 'f')
            return static_cast<unsigned>(c - 'a' + 10);
        if (c >= 'A' && c <= 'F')
            return static_cast<unsigned>(c - 'A' + 10);
        throw Error(10, "Invalid hex.");
    };
    for (std::size_t i = 0; i < text.size(); i += 2)
        result.push_back(static_cast<std::uint8_t>((nibble(text[i]) << 4) | nibble(text[i + 1])));
    return result;
}
std::uint32_t payload_size(std::span<const std::uint8_t> header) {
    if (header.size() != header_size)
        throw Error(1, "Invalid header length.");
    Reader r(header.subspan(52));
    const auto size = r.u32();
    if (size > max_payload)
        throw Error(1, "Payload limit exceeded.");
    return size;
}
Frame decode_frame(std::span<const std::uint8_t> bytes) {
    if (bytes.size() < header_size)
        throw Error(1, "Truncated header.");
    const auto size = payload_size(bytes.first(header_size));
    if (bytes.size() != header_size + size)
        throw Error(1, "Invalid frame length.");
    Reader r(bytes);
    const auto magic = r.take(4);
    if (std::string_view(reinterpret_cast<const char*>(magic.data()), 4) != "FLNK" || r.u8() != 2)
        throw Error(1, "Only FluidLink v2 is supported.");
    Frame f;
    f.kind = r.choice(1, 2);
    f.opcode = r.u8();
    f.subject = r.u8();
    f.decision = r.u8();
    f.flags = r.mask(3);
    if (r.u16())
        throw Error(1, "Reserved bits are set.");
    f.sequence = r.u64();
    const auto message = r.take(16);
    std::copy(message.begin(), message.end(), f.message.begin());
    const auto session = r.take(16);
    std::copy(session.begin(), session.end(), f.session.begin());
    (void)r.u32();
    if (!f.sequence || !nonzero(f.message) || bool(f.flags & 2) != nonzero(f.session) ||
        (f.kind == 1 && (f.flags & 1)))
        throw Error(1, "Invalid frame identity or flags.");
    const auto payload = r.take(size);
    f.payload.assign(payload.begin(), payload.end());
    return f;
}
Bytes encode_frame(const Frame& f) {
    if (f.payload.size() > max_payload)
        throw Error(1, "Payload limit exceeded.");
    Writer w;
    w.raw(std::array<std::uint8_t, 4>{'F', 'L', 'N', 'K'});
    w.integer(2, 1);
    w.integer(f.kind, 1);
    w.integer(f.opcode, 1);
    w.integer(f.subject, 1);
    w.integer(f.decision, 1);
    w.integer(f.flags, 1);
    w.integer(0, 2);
    w.integer(f.sequence, 8);
    w.raw(f.message);
    w.raw(f.session);
    w.integer(f.payload.size(), 4);
    w.raw(f.payload);
    return w.data;
}
Frame ProtocolSession::respond(const Frame& request,
                               std::uint8_t opcode,
                               Bytes payload,
                               std::uint8_t decision,
                               bool ok) const {
    Frame result;
    result.kind = 2;
    result.opcode = opcode;
    result.subject = (opcode == 11 || opcode == 255) ? request.subject : 0;
    result.decision = decision;
    result.sequence = request.sequence;
    result.message = request.message;
    result.flags = static_cast<std::uint8_t>((ok ? 1 : 0) | (negotiated_ ? 2 : 0));
    if (negotiated_)
        result.session = identity_;
    result.payload = std::move(payload);
    return result;
}
Frame ProtocolSession::process(const Frame& request) {
    try {
        return handle(request);
    } catch (const Error& e) {
        closed = closed || e.fatal;
        Writer w;
        w.integer(e.code, 2);
        w.text(e.what(), 2);
        return respond(request, 255, std::move(w.data), 255, false);
    } catch (const std::bad_alloc&) {
        closed = true;
        Writer w;
        w.integer(11, 2);
        w.text("Allocation failed; reconnect.", 2);
        return respond(request, 255, std::move(w.data), 255, false);
    }
}
Frame ProtocolSession::handle(const Frame& request) {
    if (request.kind != 1)
        throw Error(1, "Requests only.");
    if (request.sequence != sequence_)
        throw Error(6, "Sequence mismatch.");
    if (negotiated_ && request.session != identity_)
        throw Error(7, "Session mismatch.");
    if (closed)
        throw Error(12, "Session closed.");
    if (sequence_ == std::numeric_limits<std::uint64_t>::max())
        throw Error(6, "Sequence exhausted.", true);
    ++sequence_;
    Reader r(request.payload);
    if (!negotiated_) {
        if (request.opcode != 1)
            throw Error(2, "Handshake required.");
        if ((request.flags & 2) || request.subject || request.decision)
            throw Error(1, "Invalid hello header.");
        const auto digest = r.take(32);
        const auto digest_hex = hex(digest);
        const auto requested = r.u64(), required = r.u64();
        if ((requested | required) & ~std::uint64_t{255})
            throw Error(10, "Unknown capabilities.");
        (void)r.text(1, 128);
        (void)r.text(1, 64);
        r.finish();
        if (digest_hex != base_hash && digest_hex != batch_hash)
            throw Error(3, "Contract mismatch.");
        batch_ = digest_hex == batch_hash;
        if (batch_ && !(required & 128))
            throw Error(10, "Batch capability must be required.");
        const std::uint64_t available = batch_ ? 255 : 127;
        if (required & ~available)
            throw Error(4, "Required capability unavailable.");
        capabilities_ = (requested | required) & available;
        negotiated_ = true;
        Writer w;
        w.raw(digest);
        w.integer(available, 8);
        w.integer(capabilities_, 8);
        w.integer(max_payload, 4);
        w.text("fluidgateway", 1);
        w.text(native_version, 1);
        return respond(request, 2, std::move(w.data));
    }
    if (request.decision)
        throw Error(1, "Request decision must be zero.");
    if (request.opcode == 10) {
        if ((capabilities_ & 27) != 27)
            throw Error(5, "Runtime capabilities not negotiated.");
        if (request.subject == 105) {
            if (!batch_ || !(capabilities_ & 128))
                throw Error(5, "Batch not negotiated.");
            const auto id = r.take(16);
            if (!nonzero(id))
                throw Error(10, "Zero batch identity.");
            const auto count = r.u16();
            if (!count || count > 256)
                throw Error(10, "Invalid batch count.");
            auto op = operation(r, true);
            Writer w;
            w.raw(id);
            w.integer(count, 2);
            try {
                const auto prefix = "batch-" + hex(id) + "-";
                for (unsigned i = 0; i < count; ++i) {
                    auto number = std::to_string(i);
                    op.id = prefix + std::string(3 - number.size(), '0') + number;
                    const auto result = state.process(op);
                    w.integer(result.opcode, 1);
                    w.decision(result);
                }
            } catch (...) {
                closed = true;
                throw;
            }
            return respond(request, 11, std::move(w.data), 7);
        }
        const auto result = event(request.subject, request.payload);
        Writer w;
        w.decision(result);
        return respond(request, 11, std::move(w.data), result.opcode);
    }
    if (request.subject)
        throw Error(1, "Invalid subject opcode.");
    if (request.opcode == 20) {
        if (!(capabilities_ & 4))
            throw Error(5, "Heartbeat not negotiated.");
        const auto nonce = r.text(1, 128);
        r.finish();
        Writer w;
        w.text(nonce, 1);
        return respond(request, 21, std::move(w.data));
    }
    if (request.opcode == 30) {
        r.finish();
        closed = true;
        return respond(request, 30, {});
    }
    throw Error(8, "Unsupported opcode.");
}
Decision ProtocolSession::event(std::uint8_t subject, std::span<const std::uint8_t> payload) {
    Reader r(payload);
    if (subject == 100) {
        const auto action = r.choice(1, 2), presence = r.mask(63);
        if (action == 2 && presence)
            throw Error(10, "End cannot carry budgets.");
        (void)r.text(2, 256, action == 2);
        if (presence & 1)
            (void)r.u32();
        for (unsigned bit = 1; bit < 6; ++bit)
            if (presence & (1 << bit))
                (void)r.u64();
        r.finish();
        if (action == 2)
            state.end_session();
    } else if (subject == 101) {
        const auto action = r.choice(1, 2), presence = r.mask(1);
        if (action == 2 && presence)
            throw Error(10, "End cannot carry frame budget.");
        const auto frame = r.u64();
        if (presence)
            (void)r.u32();
        r.finish();
        if (action == 1)
            state.begin_frame(frame);
        else
            state.end_frame(frame);
    } else if (subject == 102) {
        const auto action = r.choice(1, 2);
        const auto id = r.text(2, 256, false, true);
        if (action == 2) {
            r.finish();
            state.release_resource(id);
        } else {
            (void)r.choice(0, 4);
            const auto layer = r.choice(1, 6);
            (void)r.choice(0, 4);
            (void)r.u64();
            const auto count = r.choice(0, 32);
            std::vector<std::string> aliases;
            for (unsigned i = 0; i < count; ++i)
                aliases.push_back(r.text(2, 256));
            r.finish();
            state.register_resource(id, layer, aliases);
        }
    } else if (subject == 103)
        return state.process(operation(r));
    else if (subject == 104) {
        (void)r.choice(1, 1);
        r.finish();
    } else
        throw Error(9, "Unsupported event opcode.");
    return {};
}
} // namespace fluidgateway
