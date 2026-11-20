#!/usr/bin/env python3
import re
from pathlib import Path

from check_rocev2_pcap import read_pcap


def statistics(log):
    ports = {}
    for line in log.splitlines():
        if not line.startswith("SWITCH_PORT_STAT "):
            continue
        fields = dict(re.findall(r"(\w+)=([^ ]+)", line))
        ports[fields["port"]] = {key: int(value) for key, value in fields.items() if key != "port"}
    assert len(ports) == 4
    for port, stat in ports.items():
        assert stat["enq_packets"] == stat["sent_packets"] + stat["drop_packets"] + stat["queued_packets"], port
        assert stat["enq_bytes"] == stat["sent_bytes"] + stat["drop_bytes"] + stat["queued_bytes"], port
        assert stat["queued_packets"] == 0 and stat["queued_bytes"] == 0, port
    return ports


def load(case, tag, version):
    result = Path(f"results/switch-{case}-ipv{version}") / tag
    log = (result / "simulation.log").read_text(errors="replace")
    assert "Exiting @ tick" in log and "simulate() limit reached" not in log
    assert not any(x in log for x in ("segmentation fault", "Program aborted", "panic:"))
    ports = statistics(log)
    for name in ("server", "client1", "client2", "client3"):
        packets = read_pcap(result / f"rocev2.{name}.pcap")
        assert all(packet["ip_version"] == version for packet in packets)
    return log, ports


def check(case, version):
    if case == "s01":
        for operation in ("write", "read", "send"):
            log, ports = load(case, operation, version)
            if operation == "send":
                assert len(re.findall(r"TX_CQE mode=41 status=0", log)) == 2
                assert len(re.findall(r"RX_CQE mode=41 status=0", log)) == 2
            else:
                assert len(re.findall(r"FIXED_SUMMARY submitted=16 success=16 failure=0 outstanding=0", log)) == 2
    elif case == "s02":
        log, ports = load(case, "parallel", version)
        assert len(re.findall(r"FIXED_SUMMARY submitted=16 success=16 failure=0 outstanding=0", log)) == 2
    elif case == "s03":
        log, ports = load(case, "bidirectional", version)
        assert len(re.findall(r"\[SERVER: Server\d+-\d+\] FIXED_SUMMARY submitted=16 success=16 failure=0 outstanding=0", log)) == 2
        assert len(re.findall(r"\[CLIENT: Client\d+-\d+\] CLT_FIXED_SUMMARY submitted=16 success=16 failure=0 outstanding=0", log)) == 2
    elif case == "s04":
        log, ports = load(case, "fanin", version)
        assert len(re.findall(r"FIXED_SUMMARY submitted=16 success=16 failure=0 outstanding=0", log)) == 3
    elif case == "s05":
        log, ports = load(case, "overflow", version)
        assert len(re.findall(r"RC_STATE_SUMMARY mode=31 submitted=8 success=8 failure=0 outstanding=0", log)) == 3
        assert "action=drop" in log and "RC_RETRANSMIT" in log
        assert sum(stat["drop_packets"] for stat in ports.values()) > 0
    elif case == "s06":
        log, ports = load(case, "busy", version)
        assert len(re.findall(r"RC_STATE_SUMMARY mode=31 submitted=8 success=8 failure=0 outstanding=0", log)) == 3
        assert sum(stat["drop_packets"] for stat in ports.values()) == 0
    elif case == "s07":
        log, ports = load(case, "timing", version)
        assert len(re.findall(r"FIXED_SUMMARY submitted=16 success=16 failure=0 outstanding=0", log)) == 2
        expected_bytes = 138 if version == 4 else 158
        assert f"action=sent bytes={expected_bytes}" in log and "queue_delay=5441" in log
    elif case == "s08":
        log, _ = load(case, "multipacket", version)
        assert len(re.findall(r"RC_STATE_SUMMARY mode=38 submitted=1 success=1 failure=0 outstanding=0", log)) == 2
        log, _ = load(case, "cross-page", version)
        assert len(re.findall(r"PROTECT_CQE mode=19 status=0", log)) == 2
        log, ports = load(case, "ring-stress", version)
        assert "RING_SUMMARY submitted=320 completions=81 outstanding=0" in log
    print(f"PASS {case} IPv{version} forwarding, queues, statistics and RC completion")


for version in (4, 6):
    for case in ("s01", "s02", "s03", "s04", "s05", "s06", "s07", "s08"):
        check(case, version)
