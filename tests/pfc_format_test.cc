#include <array>
#include <cassert>
#include <cstdint>
#include <iostream>

#include "../model/csrna/src/dev/net/pfc.hh"
#include "../model/csrna/src/dev/rdma/rocev2.hh"

static void
test_classification()
{
    uint8_t packet[256] = {};
    RoCEv2::setIpVersion(packet, 4);
    RoCEv2::writeHeaders(packet, RoCEv2::BthSize + RoCEv2::IcrcSize, 10, 11);
    assert(PFC::dscp(packet) == 24 && PFC::priority(PFC::dscp(packet)) == 3);
    RoCEv2::applyEcn(packet, 100, 0);
    assert(PFC::dscp(packet) == 24 && PFC::priority(PFC::dscp(packet)) == 3);
    RoCEv2::setIpVersion(packet, 6);
    RoCEv2::writeHeaders(packet, RoCEv2::BthSize + RoCEv2::IcrcSize, 10, 11);
    assert(PFC::dscp(packet) == 24 && PFC::priority(PFC::dscp(packet)) == 3);
    RoCEv2::applyEcn(packet, 100, 0);
    assert(PFC::dscp(packet) == 24 && PFC::priority(PFC::dscp(packet)) == 3);
    RoCEv2::writeHeaders(packet, RoCEv2::BthSize + RoCEv2::IcrcSize, 10, 11, 0);
    assert(PFC::priority(PFC::dscp(packet)) == 0);
    std::cout << "PASS P01 IPv4/IPv6 DSCP classification and CE priority preservation\n";
}

static void
test_frame()
{
    uint8_t frame[PFC::FrameSize];
    std::array<uint16_t, 8> times{};
    times[3] = 0x1234;
    PFC::writeFrame(frame, 0x020000000100ULL, 1U << 3, times);
    assert(PFC::isPfc(frame, sizeof(frame)));
    assert(PFC::read16(frame + 12) == 0x8808 && PFC::read16(frame + 14) == 0x0101);
    assert(PFC::enableVector(frame) == 8 && PFC::pauseTime(frame, 3) == 0x1234);
    for (size_t i = 34; i < sizeof(frame); ++i) assert(frame[i] == 0);
    std::cout << "PASS P02 60-byte MAC Control PFC fields and zero padding\n";
}

static void
test_timers()
{
    std::array<uint64_t, 8> pause{};
    std::array<uint16_t, 8> times{};
    times[3] = 10;
    uint8_t frame[PFC::FrameSize];
    PFC::writeFrame(frame, 1, 0, times);
    PFC::apply(frame, pause, 1000, 10.0);
    assert(pause[3] == 0);
    PFC::writeFrame(frame, 1, 8, times);
    PFC::apply(frame, pause, 1000, 10.0);
    assert(pause[3] == 1000 + 10 * 64 * 10);
    times[3] = 20;
    PFC::writeFrame(frame, 1, 8, times);
    PFC::apply(frame, pause, 2000, 10.0);
    assert(pause[3] == 2000 + 20 * 64 * 10);
    times[3] = 5;
    PFC::writeFrame(frame, 1, 8, times);
    PFC::apply(frame, pause, 3000, 10.0);
    assert(pause[3] == 3000 + 5 * 64 * 10);
    times[3] = 0;
    PFC::writeFrame(frame, 1, 8, times);
    PFC::apply(frame, pause, 4000, 10.0);
    assert(pause[3] == 0);
    times[3] = 1;
    PFC::writeFrame(frame, 1, 8, times);
    PFC::apply(frame, pause, 5000, 10.0);
    assert(pause[3] == 5640 && pause[3] > 5000 && pause[3] <= 5640);
    std::cout << "PASS P05 mask, longer/shorter refresh, Xon, quantum and natural expiry\n";
}

int
main()
{
    test_classification();
    test_frame();
    test_timers();
    return 0;
}
