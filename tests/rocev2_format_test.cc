#include <cassert>
#include <cstdint>
#include <cstdio>
#include <vector>

#include "../model/csrna/src/dev/rdma/rocev2.hh"

int main() {
    constexpr std::size_t payloadSize = 64;
    constexpr std::size_t packetSize = RoCEv2::BthOffset + RoCEv2::BthSize +
        RoCEv2::RethSize + payloadSize + RoCEv2::IcrcSize;
    std::vector<uint8_t> packet(packetSize);

    RoCEv2::writeHeaders(packet.data(), packetSize - RoCEv2::BthOffset, 10, 11);
    RoCEv2::writeBth(packet.data(), RoCEv2::RcWriteOnly, 0x123456, 0x654321);
    RoCEv2::writeReth(packet.data(), 0x0123456789abcdef, 0x11223344, payloadSize);
    for (std::size_t i = 0; i < payloadSize; ++i) {
        packet[RoCEv2::BthOffset + RoCEv2::BthSize + RoCEv2::RethSize + i] = i;
    }
    RoCEv2::finishPacket(packet.data(), packetSize - RoCEv2::IcrcSize);

    static_assert(sizeof(RoCEv2::Bth) == 12, "BTH size");
    static_assert(sizeof(RoCEv2::Reth) == 16, "RETH size");
    assert(RoCEv2::validPacket(packet.data(), packet.size()));
    assert(RoCEv2::opcode(packet.data()) == 0x0a);
    assert(RoCEv2::destQpn(packet.data()) == 0x123456);
    assert(RoCEv2::psn(packet.data()) == 0x654321);
    assert(RoCEv2::rethAddr(packet.data()) == 0x0123456789abcdef);
    assert(RoCEv2::rethKey(packet.data()) == 0x11223344);
    assert(RoCEv2::rethLength(packet.data()) == payloadSize);
    assert(RoCEv2::readBe16(packet.data() + RoCEv2::UdpOffset + 2) == 4791);
    assert(RoCEv2::readBe16(packet.data() + RoCEv2::Ipv4Offset + 2) == packetSize - 14);
    assert(RoCEv2::psnAdd(0xffffff, 1) == 0);
    assert(RoCEv2::psnCompare(0, 0xffffff) > 0);
    assert(RoCEv2::psnCompare(0xffffff, 0) < 0);
    assert(RoCEv2::psnCompare(1, 0xffffff) > 0);
    assert(RoCEv2::psnCompare(0x7fffff, 0) > 0);
    assert(RoCEv2::psnCompare(0x800000, 0) < 0);

    packet[RoCEv2::BthOffset + RoCEv2::BthSize + RoCEv2::RethSize] ^= 1;
    assert(!RoCEv2::validPacket(packet.data(), packet.size()));

    std::vector<uint8_t> ipv6(packetSize + 20);
    RoCEv2::setIpVersion(ipv6.data(), 6);
    std::size_t bth = RoCEv2::bthOffset(ipv6.data());
    RoCEv2::writeHeaders(ipv6.data(), ipv6.size() - bth, 10, 11);
    RoCEv2::writeBth(ipv6.data(), RoCEv2::RcWriteOnly, 1, 0);
    RoCEv2::writeReth(ipv6.data(), 0x1000, 4, payloadSize);
    RoCEv2::finishPacket(ipv6.data(), ipv6.size() - RoCEv2::IcrcSize);
    assert(RoCEv2::validPacket(ipv6.data(), ipv6.size()));
    uint32_t icrc = RoCEv2::readBe32(ipv6.data() + ipv6.size() - RoCEv2::IcrcSize);
    RoCEv2::writeBe16(ipv6.data() + RoCEv2::udpOffset(ipv6.data()) + 6, 0);
    assert(RoCEv2::validPacket(ipv6.data(), ipv6.size()));
    assert(RoCEv2::readBe32(ipv6.data() + ipv6.size() - RoCEv2::IcrcSize) == icrc);
    ipv6[ipv6.size() - 1] ^= 1;
    assert(!RoCEv2::validPacket(ipv6.data(), ipv6.size()));

    std::puts("PASS RoCEv2 format, byte order, lengths, ICRC and zero/nonzero IPv6 UDP checksum");
}
