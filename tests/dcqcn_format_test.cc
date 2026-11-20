#include <cassert>
#include <cmath>
#include <cstdint>
#include <iostream>

#include "../model/csrna/src/dev/rdma/dcqcn.hh"

static DCQCN::Params
params()
{
    DCQCN::Params p;
    p.maxRate = 100000000000ULL;
    p.minRate = 1000000000ULL;
    p.rateAI = 1000000000ULL;
    p.rateHAI = 5000000000ULL;
    p.alphaInterval = 55000000;
    p.decreaseInterval = 4000000;
    p.recoveryInterval = 10000000;
    p.fastRecoveryTimes = 5;
    return p;
}

static void
test_packet_ticks()
{
    assert(DCQCN::packetTicks(128, 100000000000ULL) == 10240);
    assert(DCQCN::packetTicks(128, 50000000000ULL) == 20480);
    assert(DCQCN::packetTicks(4096, 100000000000ULL) == 327680);
    assert(DCQCN::packetTicks(65, 10000000000ULL) == 52000);
    std::cout << "PASS D01 charged-byte pacing arithmetic and tick rounding\n";
}

static void
test_first_cnp_and_period_boundaries()
{
    DCQCN::Params p = params();
    DCQCN::State state;
    DCQCN::initialize(state, p);
    const uint64_t first = 1000000;
    DCQCN::onCnp(state, p, first);
    assert(state.currentRate == p.maxRate && state.targetRate == p.maxRate);
    assert(state.alpha == 1.0 && !state.alphaCnpArrived);
    assert(state.decreaseCnpArrived && state.firstCnp == false);
    assert(state.alphaDeadline == first + p.alphaInterval);
    assert(state.decreaseDeadline == first + p.decreaseInterval + 1000);

    DCQCN::onCnp(state, p, first);
    DCQCN::onCnp(state, p, first + 1000000);
    assert(state.cnpCount == 3 && state.currentRate == p.maxRate);
    assert(DCQCN::checkRateDecrease(state, p, state.decreaseDeadline));
    assert(state.currentRate == 50000000000ULL);
    assert(state.targetRate == p.maxRate && state.decreaseCount == 1);
    assert(state.recoveryDeadline == first + p.decreaseInterval + 1000 + p.recoveryInterval);
    assert(!DCQCN::checkRateDecrease(state, p, state.decreaseDeadline));
    assert(state.decreaseCount == 1 && state.currentRate == 50000000000ULL);
    std::cout << "PASS D02 first CNP state, timers and monitored rate decrease\n";
    std::cout << "PASS D03 same-tick and cross-period CNP coalescing\n";
}

static void
test_alpha_and_recovery()
{
    DCQCN::Params p = params();
    DCQCN::State state;
    DCQCN::initialize(state, p);
    DCQCN::onCnp(state, p, 0);
    DCQCN::updateAlpha(state, p, state.alphaDeadline);
    assert(std::fabs(state.alpha - 15.0 / 16) < 1e-12);
    DCQCN::onCnp(state, p, state.alphaDeadline + 1);
    assert(DCQCN::checkRateDecrease(state, p, state.decreaseDeadline));
    assert(state.currentRate == 53125000000ULL);
    assert(std::fabs(state.alpha - 15.0 / 16) < 1e-12);

    uint64_t now = state.recoveryDeadline;
    for (uint32_t stage = 0; stage < p.fastRecoveryTimes; ++stage) {
        uint64_t target = state.targetRate;
        uint64_t expected = state.currentRate / 2 + target / 2;
        assert(DCQCN::increaseRate(state, p, now) == stage);
        assert(state.currentRate == expected && state.targetRate == target);
        now = state.recoveryDeadline;
    }
    uint64_t target = std::min(p.maxRate, state.targetRate + p.rateAI);
    uint64_t expected = state.currentRate / 2 + target / 2;
    assert(DCQCN::increaseRate(state, p, now) == p.fastRecoveryTimes);
    assert(state.targetRate == target && state.currentRate == expected);

    now = state.recoveryDeadline;
    target = std::min(p.maxRate, state.targetRate + p.rateHAI);
    expected = state.currentRate / 2 + target / 2;
    assert(DCQCN::increaseRate(state, p, now) == p.fastRecoveryTimes + 1);
    assert(state.targetRate == target && state.currentRate == expected);

    for (int index = 0; index < 1000; ++index) {
        now = state.recoveryDeadline;
        DCQCN::increaseRate(state, p, now);
        assert(state.currentRate <= p.maxRate && state.targetRate <= p.maxRate);
    }
    assert(state.currentRate >= p.maxRate - 1 && state.targetRate == p.maxRate);
    std::cout << "PASS D04 alpha precision, FR/AI/HAI recovery and maximum-rate clamp\n";
}

static void
test_dual_byte_accounting()
{
    DCQCN::Params p = params();
    p.dualTrigger = true;
    p.byteRecoveryBytes = 1000;
    p.fastRecoveryTimes = 2;
    DCQCN::State state;
    DCQCN::initialize(state, p);
    assert(DCQCN::onSentBytes(state, p, 5000, 0) == 0);
    assert(state.byteRemainder == 0 && state.byteRecoveryCount == 0);

    DCQCN::onCnp(state, p, 0);
    assert(DCQCN::checkRateDecrease(state, p, state.decreaseDeadline));
    uint64_t deadline = state.recoveryDeadline;
    assert(DCQCN::onSentBytes(state, p, 999, deadline) == 0);
    assert(state.byteRemainder == 999 && state.byteRecoveryCount == 0);
    assert(DCQCN::onSentBytes(state, p, 1, deadline) == 1);
    assert(state.byteRemainder == 0 && state.byteRecoveryCount == 1);
    assert(state.timeRecoveryCount == 0 && state.recoveryPhase == 0);
    assert(state.recoveryDeadline == deadline);
    assert(DCQCN::onSentBytes(state, p, 1500, deadline) == 1);
    assert(state.byteRemainder == 500 && state.byteRecoveryCount == 2);
    assert(state.recoveryPhase == 1);
    assert(DCQCN::onSentBytes(state, p, 2500, deadline) == 3);
    assert(state.byteRemainder == 0 && state.byteRecoveryCount == 5);
    std::cout << "PASS BR02 byte accounting is restricted to post-send calls and recovery-active state\n";
    std::cout << "PASS BR03 byte threshold below/equal/above, multi-trigger and residual preservation\n";
}

static void
test_dual_counters_and_reset()
{
    DCQCN::Params p = params();
    p.dualTrigger = true;
    p.byteRecoveryBytes = 100;
    p.fastRecoveryTimes = 2;
    DCQCN::State state;
    DCQCN::initialize(state, p);
    DCQCN::onCnp(state, p, 0);
    assert(DCQCN::checkRateDecrease(state, p, state.decreaseDeadline));
    uint64_t deadline = state.recoveryDeadline;
    assert(DCQCN::increaseRate(state, p, deadline, DCQCN::TIME_TRIGGER) == 0);
    assert(state.timeRecoveryCount == 1 && state.byteRecoveryCount == 0);
    assert(state.recoveryPhase == 0);
    uint64_t timeDeadline = state.recoveryDeadline;
    assert(DCQCN::onSentBytes(state, p, 100, deadline) == 1);
    assert(state.timeRecoveryCount == 1 && state.byteRecoveryCount == 1);
    assert(state.recoveryPhase == 0);
    assert(state.recoveryDeadline == timeDeadline);
    DCQCN::increaseRate(state, p, deadline + p.recoveryInterval, DCQCN::TIME_TRIGGER);
    assert(state.timeRecoveryCount == 2 && state.byteRecoveryCount == 1);
    assert(state.recoveryPhase == 1);
    DCQCN::increaseRate(state, p, deadline + 2 * p.recoveryInterval, DCQCN::TIME_TRIGGER);
    assert(DCQCN::onSentBytes(state, p, 100, deadline) == 1);
    assert(state.timeRecoveryCount == 3 && state.byteRecoveryCount == 2);
    assert(state.recoveryPhase == 1);
    assert(DCQCN::onSentBytes(state, p, 100, deadline) == 1);
    assert(state.timeRecoveryCount == 3 && state.byteRecoveryCount == 3);
    assert(state.recoveryPhase == 2);
    std::cout << "PASS BR04 independent T/BC progression and Figure 7 FR/AI/HAI boundaries\n";

    DCQCN::onCnp(state, p, deadline + 1);
    assert(DCQCN::checkRateDecrease(state, p, state.decreaseDeadline));
    assert(state.recoveryStage == 0 && state.timeRecoveryCount == 0 &&
        state.byteRecoveryCount == 0 && state.byteRemainder == 0);
    assert(state.currentRate >= p.minRate && state.targetRate <= p.maxRate);
    std::cout << "PASS BR05 congestion decrease resets both counters, residue and stage with rate bounds\n";
}

static void
test_dual_same_tick_order()
{
    DCQCN::Params p = params();
    p.dualTrigger = true;
    p.byteRecoveryBytes = 100;
    DCQCN::State first, second;
    for (DCQCN::State *state : {&first, &second}) {
        DCQCN::initialize(*state, p);
        DCQCN::onCnp(*state, p, 0);
        assert(DCQCN::checkRateDecrease(*state, p, state->decreaseDeadline));
    }
    uint64_t now = first.recoveryDeadline;
    DCQCN::increaseRate(first, p, now, DCQCN::TIME_TRIGGER);
    assert(DCQCN::onSentBytes(first, p, 100, now) == 1);
    assert(DCQCN::onSentBytes(second, p, 100, now) == 1);
    DCQCN::increaseRate(second, p, now, DCQCN::TIME_TRIGGER);
    assert(first.currentRate == second.currentRate && first.targetRate == second.targetRate);
    assert(first.timeRecoveryCount == second.timeRecoveryCount &&
        first.byteRecoveryCount == second.byteRecoveryCount);
    uint64_t deadline = first.recoveryDeadline;
    assert(DCQCN::onSentBytes(first, p, 0, now) == 0);
    assert(first.recoveryDeadline == deadline);
    DCQCN::initialize(first, p);
    assert(first.recoveryStage == 0 && first.timeRecoveryCount == 0 &&
        first.byteRecoveryCount == 0 && first.byteRemainder == 0);
    std::cout << "PASS BR06 same-tick time/byte ordering, zero-byte repeat and clean reinitialization\n";
}

static void
test_scheduler()
{
    std::vector<DCQCN::ScheduleEntry> entries = {
        {1, false, true}, {2, false, true}, {3, false, false}
    };
    assert(DCQCN::selectEntry(entries, 0) == 0);
    assert(DCQCN::selectEntry(entries, 2) == 1);
    assert(DCQCN::selectEntry(entries, 3) == 0);
    for (int repeat = 0; repeat < 100; ++repeat) {
        assert(DCQCN::selectEntry(entries, 2) == 1);
    }
    entries.push_back({4, true, true});
    assert(DCQCN::selectEntry(entries, 0) == 3);
    entries[0].eligible = false;
    entries[1].eligible = false;
    entries[3].control = false;
    entries[3].eligible = false;
    assert(DCQCN::selectEntry(entries, 0) == entries.size());
    std::cout << "PASS D07 same-tick control priority, round-robin wrap and repeatability\n";
}

int
main()
{
    test_packet_ticks();
    test_first_cnp_and_period_boundaries();
    test_alpha_and_recovery();
    test_dual_byte_accounting();
    test_dual_counters_and_reset();
    test_dual_same_tick_order();
    test_scheduler();
    return 0;
}
