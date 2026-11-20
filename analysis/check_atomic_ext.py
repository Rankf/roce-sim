#!/usr/bin/env python3
import re
from collections import defaultdict
from pathlib import Path

from check_rocev2_pcap import READ_PAYLOAD, read_pcap


def load(name):
    result = Path("results") / name
    log = (result / "simulation.log").read_text(errors="replace")
    requests = [p for p in read_pcap(result / "rocev2.server.pcap")
                if p["opcode"] in {0x0A, 0x0C, 0x13, 0x14}]
    responses = [p for p in read_pcap(result / "rocev2.client1.pcap")
                 if p["opcode"] in {0x10, 0x11, 0x12}]
    assert "Exiting @ tick" in log
    assert not any(x in log for x in ("segmentation fault", "Program aborted", "panic:"))
    assert "guard=0x875ba9063dbf9103" in log
    return result, log, requests, responses


def check_protection():
    _, log, requests, responses = load("qp-atomic-protect")
    assert "ATOMIC_PROTECT_SUMMARY denied=3 submit_rejected=1" in log
    assert len(re.findall(r"ATOMIC_CQE type=9 status=10", log)) == 3
    for reason in ("permission", "key", "range"):
        assert f"PROTECT deny reason={reason}" in log
    assert "ATOMIC_EXECUTED" not in log
    assert "ATOMIC_TARGET index=0 value=0x0" in log
    assert len(requests) == 3 and all(p["opcode"] == 0x14 for p in requests)
    errors = [p for p in responses if p["opcode"] == 0x11 and p.get("syndrome") != 0]
    assert len(errors) == 3
    print("PASS Atomic permission, key, full range and alignment rejection")


def check_contend():
    _, log, requests, responses = load("qp-atomic-contend")
    assert "ATOMIC_COMPETE_SUMMARY completed=64 unique_old=64" in log
    assert "ATOMIC_TARGET index=0 value=0x40" in log
    assert len(re.findall(r"ATOMIC_EXECUTED", log)) == 64
    old = [int(x, 16) for x in re.findall(r"ATOMIC_COMPETE_CQE wr_id=0x[0-9a-f]+ status=0 old=0x([0-9a-f]+)", log)]
    assert sorted(old) == list(range(64))
    atomic_acks = [p["original"] for p in responses if p["opcode"] == 0x12]
    assert sorted(atomic_acks) == list(range(64))
    by_qp = defaultdict(list)
    for packet in requests:
        assert packet["opcode"] == 0x14
        by_qp[packet["qpn"]].append(packet["psn"])
    assert set(by_qp) == {1, 2}
    for psns in by_qp.values():
        assert psns == list(range(32))
    print("PASS two-QP atomicity with final count and unique old-value set")


def check_duplicate():
    _, log, requests, responses = load("qp-atomic-duplicate")
    assert "ATOMIC_DUPLICATE_SUMMARY mode=61 executed=1 target=1" in log
    assert len(re.findall(r"ATOMIC_EXECUTED", log)) == 1
    assert "ATOMIC_DUPLICATE_PENDING" in log or "ATOMIC_DUPLICATE_REPLAY" in log
    assert len(re.findall(r"ATOMIC_CQE type=9 status=0", log)) == 1
    assert len(re.findall(r"ATOMIC_RESPONSE", log)) == 1
    assert "ATOMIC_TARGET index=0 value=0x1" in log
    assert len(requests) == 2
    assert responses and all(p["original"] == 0 for p in responses if p["opcode"] == 0x12)
    print("PASS in-flight duplicate suppression with one execution and one completion")


def check_replay():
    _, log, requests, responses = load("qp-atomic-replay")
    assert "ATOMIC_DUPLICATE_SUMMARY mode=62 executed=1 target=1" in log
    assert len(re.findall(r"ATOMIC_EXECUTED", log)) == 1
    assert "ATOMIC_DUPLICATE_REPLAY" in log
    assert len(re.findall(r"ATOMIC_CQE type=9 status=0", log)) == 1
    assert "ATOMIC_TARGET index=0 value=0x1" in log
    assert len(requests) == 2
    acks = [p for p in responses if p["opcode"] == 0x12]
    assert len(acks) == 1 and acks[0]["original"] == 0
    print("PASS completed Atomic ACK replay with first old value and one execution")


def check_credit_fence():
    _, log, requests, responses = load("qp-atomic-credit-fence")
    assert "READ_CREDIT_WAIT" in log and "FENCE_WAIT" in log
    assert "ATOMIC_CREDIT_SUMMARY completed=4 old0=0 old1=1" in log
    assert "ATOMIC_TARGET index=16 value=0x2" in log
    acks = sorted(p["original"] for p in responses if p["opcode"] == 0x12)
    assert acks == [0, 1]
    writes = [p for p in requests if p["opcode"] == 0x0A]
    assert len(writes) == 1 and writes[0]["payload"] == READ_PAYLOAD
    assert len([p for p in requests if p["opcode"] == 0x0C]) == 1
    assert len([p for p in requests if p["opcode"] == 0x14]) == 2
    print("PASS shared Read/Atomic credits and fenced Write data visibility")


def check_retry():
    _, log, requests, responses = load("qp-atomic-retry")
    assert len(re.findall(r"ATOMIC_EXECUTED", log)) == 2
    assert "ATOMIC_RETRY_SUMMARY executed=2 target0=1 target1=1" in log
    assert "ATOMIC_TARGET index=0 value=0x1" in log
    assert "ATOMIC_TARGET index=8 value=0x1" in log
    statuses = re.findall(r"ATOMIC_RETRY_CQE type=\d+ status=(\d+)", log)
    assert statuses == ["12", "5"], statuses
    assert len(requests) >= 3
    assert not any(p["opcode"] == 0x12 for p in responses)
    print("PASS retry exhaustion preserves one remote update and distinct WC errors")


def check_reset():
    _, log, requests, responses = load("qp-atomic-reset")
    assert "ATOMIC_RESET_FLUSH status=5" in log
    assert "ATOMIC_RESET_SUMMARY flushed=1 success=1 target=2" in log
    assert "ATOMIC_TARGET index=0 value=0x2" in log
    assert "ATOMIC_CQE type=9 status=0" in log and "old=0x1" in log
    assert len(re.findall(r"ATOMIC_EXECUTED", log)) == 2
    acks = [p for p in responses if p["opcode"] == 0x12]
    assert len(acks) == 1 and acks[0]["original"] == 1
    assert len(requests) == 2
    print("PASS Atomic ERR/RESET flush, preserved update and successful reinitialization")


check_protection()
check_contend()
check_duplicate()
check_replay()
check_credit_fence()
check_retry()
check_reset()
