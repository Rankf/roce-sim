#!/usr/bin/env python3
import re
from pathlib import Path

from check_rocev2_pcap import WRITE_PAYLOAD, read_pcap


def load(name):
    result = Path("results") / name
    log = (result / "simulation.log").read_text(errors="replace")
    requests = [p for p in read_pcap(result / "rocev2.server.pcap")
                if p["opcode"] != 0x64]
    responses = [p for p in read_pcap(result / "rocev2.client1.pcap")
                 if p["opcode"] != 0x64]
    assert "Exiting @ tick" in log
    assert "simulate() limit reached" not in log
    assert not any(x in log for x in ("segmentation fault", "Program aborted", "panic:"))
    assert "guard=0x875ba9063dbf9103" in log
    return log, requests, responses


def check_basic():
    log, requests, responses = load("mw-bind")
    assert "MW01_SUMMARY invalidated_status=10" in log
    assert len(re.findall(r"ATOMIC_EXECUTED", log)) == 2
    assert "ATOMIC_TARGET index=32 value=0x2" in log
    assert len(re.findall(r"MW_RX_CQE status=0 .*rkey=0x100 flags=0x8", log)) == 1
    inv = [p for p in requests if p["opcode"] == 0x17]
    assert len(inv) == 1 and inv[0]["invalidated_rkey"] == 0x100
    assert inv[0]["payload"] == WRITE_PAYLOAD
    assert any(p["opcode"] == 0x0A for p in requests)
    assert any(p["opcode"] == 0x0C for p in requests)
    assert any(p["opcode"] == 0x13 for p in requests)
    assert any(p["opcode"] == 0x14 for p in requests)
    assert any(p["opcode"] == 0x12 for p in responses)
    print("PASS MW01 bind, Read/Write/CAS/FAA and remote invalidation")


def check_reject():
    log, _, _ = load("mw-reject")
    assert "MW02_SUMMARY denied=3 noop=0" in log
    assert len(re.findall(r"MW_CQE type=10 status=6", log)) == 3
    assert "MW_LOCAL_INV_NOOP" in log
    assert "ATOMIC_TARGET index=0 value=0x0" in log
    print("PASS MW02 bind rejection without partial authorization")


def check_rebind():
    log, _, _ = load("mw-rebind")
    assert "MW_LOCAL_INV_NOOP" in log
    assert "MW03_SUMMARY rebind_status=0 dealloc_status=10" in log
    assert len(re.findall(r"MW_CQE type=11 status=0", log)) >= 2
    print("PASS MW03 local invalidate, no-op repeat and rebind")


def check_send_inv():
    log, requests, responses = load("mw-send-inv")
    assert "MW04_SUMMARY remote_invalidated=2" in log
    assert len(re.findall(r"MW_RX_CQE status=0 .*rkey=0x100 flags=0x8", log)) == 2
    inv = [p for p in requests if p["opcode"] in {0x16, 0x17}]
    first = [p for p in requests if p["opcode"] == 0x00]
    assert len(inv) == 2 and len(first) == 1
    assert inv[0]["opcode"] == 0x17 and not inv[0]["payload"]
    assert inv[0]["invalidated_rkey"] == inv[1]["invalidated_rkey"] == 0x100
    assert inv[1]["opcode"] == 0x16 and not any(inv[1]["payload"])
    assert first[0]["payload"] == WRITE_PAYLOAD + bytes(4096 - len(WRITE_PAYLOAD))
    assert len([p for p in responses if p["opcode"] == 0x11]) == 3
    print("PASS MW04 zero/multipacket SEND_WITH_INV and receive completion")


def check_rnr():
    log, requests, responses = load("mw-rnr")
    assert "MW05_SUMMARY rnr_recovered=1" in log
    assert "RC_RNR_NAK" in log and "RC_DUPLICATE request" in log
    assert len(re.findall(r"MW_RX_CQE status=0 .*rkey=0x100 flags=0x8", log)) == 1
    assert any(p["opcode"] == 0x11 and p.get("syndrome") == 0x20 for p in responses)
    print("PASS MW05 RNR, duplicate and ACK-loss recovery with one receive completion")


def check_timing():
    log, _, _ = load("mw-timing")
    assert "MW06_SUMMARY retired_rebound=1" in log
    assert len(re.findall(r"ATOMIC_EXECUTED", log)) == 4
    assert "ATOMIC_TARGET index=0 value=0x4" in log
    assert len(re.findall(r"rejects .* retries remain", log)) >= 4
    invalidate = log.index("MW_LOCAL_INV rkey 0x100 refs 3")
    retired = log.index("MW_RELEASE rkey 0x100 refs 0 state 3")
    completed = log.index("MW_TARGET_LOCAL_INV rkey=0x100 status=0")
    assert invalidate < retired < completed
    assert len(re.findall(r"MW_CQE type=4 status=10", log)) == 1
    assert len(re.findall(r"MW_CQE type=4 status=0", log)) == 1
    print("PASS MW06 Timing retirement, backpressure and rebind")


def check_lifecycle():
    log, _, _ = load("mw-lifecycle")
    assert "MW07_SUMMARY qpn_mismatch=10 mr_invalid_status=10 dealloc_status=10" in log
    assert "QP_STATE qpn 1 state 6" in log and "QP_STATE qpn 1 state 0" in log
    assert "PROTECT deny reason=mw-qpn-pd" in log
    assert "PROTECT deny reason=invalid-mr" in log
    assert len(re.findall(r"MW_DEALLOC rkey 0x100", log)) >= 2
    assert len(re.findall(r"MW_CQE type=4 status=0", log)) == 1
    assert len(re.findall(r"MW_CQE type=4 status=10", log)) == 3
    print("PASS MW07 RESET, QPN isolation, MR invalidation and deallocation")


def check_reuse():
    log, requests, _ = load("mw-reuse")
    assert "MW08_SUMMARY reuse=16 key_wrap=1 independent=1" in log
    assert len(re.findall(r"MW_TARGET_LOCAL_INV", log)) == 21
    assert len(re.findall(r"MW_LOCAL_INV", log)) >= 21
    assert len(re.findall(r"MW_BIND|MW_REBIND", log)) >= 40
    handle_pattern = (r"MW_REBIND rkey old 0x[0-9a-f]+ new 0x[0-9a-f]+ "
        r"handle (0x[0-9a-f]+) index 0x1 ")
    server_handles = set(re.findall(r"svrsys.*" + handle_pattern, log))
    client_handles = set(re.findall(r"cltsys.*" + handle_pattern, log))
    assert len(server_handles) == 1 and len(client_handles) == 1
    for rkey in (0x1FE, 0x1FF, 0x100, 0x101):
        assert f"MW_BIND rkey 0x{rkey:x} " in log
        assert any(p["opcode"] == 0x0C and p["reth"][1] == rkey for p in requests)
    assert len(re.findall(r"MW_CQE type=4 status=0", log)) == 5
    assert len(re.findall(r"MW_CQE type=4 status=10", log)) == 4
    print("PASS MW08 same-MW index preservation and 8-bit tag wrap")


check_basic()
check_reject()
check_rebind()
check_send_inv()
check_rnr()
check_timing()
check_lifecycle()
check_reuse()
