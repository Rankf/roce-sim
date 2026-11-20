#!/usr/bin/env python3
import re
from pathlib import Path

from check_rocev2_pcap import read_pcap

CASES = [
    "fixed-write", "fixed-read", "send", "send-multipacket", "send-imm",
    "write-imm", "rnr-recovery", "atomic-basic", "atomic-replay",
    "multipacket-write", "multipacket-read", "bad-rkey",
    "duplicate-write-request", "drop-read-response", "psn-wrap-write",
    "mw-bind", "mw-send-inv",
]

for name in CASES:
    result = Path("results") / f"ipv6-{name}"
    log = (result / "simulation.log").read_text(errors="replace")
    run = (result / "run.yaml").read_text()
    assert re.search(r"^roce_ip_version=6$", run, re.MULTILINE)
    assert "Exiting @ tick" in log and "simulate() limit reached" not in log
    assert not any(x in log for x in ("segmentation fault", "Program aborted", "panic:"))
    packets = read_pcap(result / "rocev2.server.pcap") + read_pcap(result / "rocev2.client1.pcap")
    assert all(packet["ip_version"] == 6 for packet in packets)
    assert "guard=0x875ba9063dbf9103" in log

    if name in {"fixed-write", "fixed-read"}:
        assert "FIXED_SUMMARY submitted=16 success=16 failure=0 outstanding=0" in log
    elif name in {"send", "send-multipacket", "send-imm", "write-imm"}:
        assert re.search(r"TX_CQE mode=\d+ status=0", log)
        assert re.search(r"RX_CQE mode=\d+ status=0", log)
    elif name == "rnr-recovery":
        assert "RC_RNR_NAK" in log and "RNR_RECV_POSTED" in log
        assert "TX_CQE mode=48 status=0" in log and "RX_CQE mode=48 status=0" in log
    elif name == "atomic-basic":
        assert "ATOMIC_BASIC_SUMMARY completed=5" in log
        assert len(re.findall(r"ATOMIC_EXECUTED", log)) == 5
        assert "ATOMIC_TARGET index=0 value=0x0" in log
    elif name == "atomic-replay":
        assert "ATOMIC_DUPLICATE_SUMMARY mode=62 executed=1 target=1" in log
        assert len(re.findall(r"ATOMIC_EXECUTED", log)) == 1
    elif name in {"multipacket-write", "multipacket-read"}:
        mode = 20 if name.endswith("write") else 21
        assert f"PROTECT_CQE mode={mode} status=0 byte_cnt=8192" in log
    elif name == "bad-rkey":
        assert "PROTECT_CQE mode=1 status=10 byte_cnt=0" in log
        assert "PROTECT deny reason=key" in log
    elif name == "duplicate-write-request":
        assert "RC_DUPLICATE request" in log and "RC_FAULT duplicate opcode 0xa" in log
        assert len(re.findall(r"PROTECT_CQE mode=24 status=0", log)) == 1
    elif name == "drop-read-response":
        assert "RC_FAULT drop opcode 0x10" in log and "RC_RETRANSMIT" in log
        assert len(re.findall(r"PROTECT_CQE mode=26 status=0", log)) == 1
    elif name == "psn-wrap-write":
        assert "RC_STATE_SUMMARY mode=29 submitted=4 success=4 failure=0 outstanding=0" in log
        psns = [p["psn"] for p in read_pcap(result / "rocev2.server.pcap")
                if p["opcode"] == 0x0A]
        assert psns == [0xFFFFFE, 0xFFFFFF, 0, 1]
    elif name == "mw-bind":
        assert "MW01_SUMMARY invalidated_status=10" in log
        assert len(re.findall(r"ATOMIC_EXECUTED", log)) == 2
    elif name == "mw-send-inv":
        assert "MW04_SUMMARY remote_invalidated=2" in log
        assert len(re.findall(r"MW_RX_CQE status=0 .*flags=0x8", log)) == 2
    print(f"PASS IPv6 {name} protocol, operation and Timing checks")
