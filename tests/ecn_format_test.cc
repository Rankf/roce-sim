#include <cassert>
#include <cstdint>
#include <cstdio>
#include <vector>

#include "../model/csrna/src/dev/rdma/rocev2.hh"

std::vector<uint8_t> makePacket(bool ipv6) {
    std::size_t bth = ipv6 ? 62 : 42;
    std::vector<uint8_t> packet(bth + RoCEv2::BthSize + 16 + RoCEv2::IcrcSize);
    if (ipv6) {
        RoCEv2::setIpVersion(packet.data(), 6);
    }
    RoCEv2::writeHeaders(packet.data(), RoCEv2::BthSize + 16 + RoCEv2::IcrcSize, 10, 11);
    if (ipv6) {
        packet[14] = (packet[14] & 0xf0) | 0x05;
        packet[15] = (packet[15] & 0x30) | 0x4a;
        packet[16] = 0xbc;
        packet[17] = 0xde;
    }
    RoCEv2::writeBth(packet.data(), 0x81, 1, 0, false);
    RoCEv2::finishPacket(packet.data(), packet.size() - RoCEv2::IcrcSize);
    return packet;
}

void setEcn(std::vector<uint8_t> &packet, uint8_t value) {
    bool ipv6 = RoCEv2::readBe16(packet.data() + 12) == RoCEv2::EtherTypeIpv6;
    if (ipv6) {
        packet[15] = (packet[15] & 0xcf) | ((value & 3) << 4);
    } else {
        packet[15] = (packet[15] & 0xfc) | (value & 3);
    }
}

void checkMetadata(const std::vector<uint8_t> &packet, bool ipv6,
        uint32_t flowLabel, uint8_t dscp) {
    if (!ipv6) {
        return;
    }
    assert((RoCEv2::readBe32(packet.data() + 14) & 0xfffff) == flowLabel);
    uint8_t trafficClass = ((packet[14] & 0x0f) << 4) | (packet[15] >> 4);
    assert((trafficClass >> 2) == dscp);
}

void checkMarked(std::vector<uint8_t> &packet, bool ipv6,
        uint32_t flowLabel, uint8_t dscp) {
    uint32_t originalCrc = RoCEv2::readBe32(packet.data() + packet.size() - 4);
    assert(RoCEv2::applyEcn(packet.data(), 512, 512) == RoCEv2::ECN_MARKED);
    assert(RoCEv2::ecn(packet.data()) == 3);
    assert(RoCEv2::validPacket(packet.data(), packet.size()));
    assert(RoCEv2::readBe32(packet.data() + packet.size() - 4) == originalCrc);
    checkMetadata(packet, ipv6, flowLabel, dscp);
    assert(RoCEv2::applyEcn(packet.data(), 1024, 512) == RoCEv2::ECN_ALREADY_MARKED);
}

void check(bool ipv6) {
    auto packet = makePacket(ipv6);
    uint32_t flowLabel = ipv6 ? 0xabcde : 0;
    uint8_t dscp = ipv6 ? 0x15 : 0;
    assert(RoCEv2::validPacket(packet.data(), packet.size()));
    assert(RoCEv2::ecn(packet.data()) == 2);
    checkMetadata(packet, ipv6, flowLabel, dscp);
    assert(RoCEv2::applyEcn(packet.data(), 511, 512) == RoCEv2::ECN_BELOW_THRESHOLD);
    assert(RoCEv2::ecn(packet.data()) == 2);

    setEcn(packet, 0);
    assert(RoCEv2::applyEcn(packet.data(), 512, 512) == RoCEv2::ECN_NOT_ECT);
    assert(RoCEv2::ecn(packet.data()) == 0);
    checkMetadata(packet, ipv6, flowLabel, dscp);

    packet = makePacket(ipv6);
    checkMarked(packet, ipv6, flowLabel, dscp);

    packet = makePacket(ipv6);
    setEcn(packet, 1);
    assert(RoCEv2::ecn(packet.data()) == 1);
    checkMarked(packet, ipv6, flowLabel, dscp);

    if (ipv6) {
        RoCEv2::writeBe16(packet.data() + RoCEv2::udpOffset(packet.data()) + 6, 0);
        assert(RoCEv2::validPacket(packet.data(), packet.size()));
    }
    packet[packet.size() - 1] ^= 1;
    assert(!RoCEv2::validPacket(packet.data(), packet.size()));
}

int main() {
    check(false);
    check(true);
    std::puts("PASS ECN codepoints, threshold, CNP format, DSCP/Flow Label preservation and ICRC invariance");
}
