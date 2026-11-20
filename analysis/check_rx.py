#!/usr/bin/env python3
import csv
import re
import sys
from pathlib import Path

from check_dcqcn import load, writes
from check_rocev2_pcap import read_pcap

RESULTS = Path("results")
SOURCES = ("svrsys", "cltsys0", "cltsys1")


def flow_summary(data, count):
    assert len(re.findall(rf"DCQCN_FLOW_SUMMARY submitted={count} success={count} failure=0 outstanding=0", data["log"])) == 3


def final_rx_zero(data):
    last = {}
    for match in re.finditer(r"\d+: (\w+)\.platform[^\n]*RX_BUFFER_EVENT action=(?:acquire|release)[^\n]*occupied=(\d+) priority_bytes=(\d+) packets=(\d+)", data["log"]):
        last[match.group(1)] = tuple(map(int, match.groups()[1:]))
    assert last and all(value == (0, 0, 0) for value in last.values()), last
    return last


def read_text(path):
    text = (RESULTS / path / "simulation.log").read_text(errors="replace")
    assert "Exiting @ tick" in text and "simulate() limit reached" not in text
    assert not any(item in text for item in ("panic:", "Program aborted", "segmentation fault"))
    return text


def check_rx01():
    data = load("rx-01-account-ipv4/sustained")
    flow_summary(data, 8)
    final_rx_zero(data)
    assert "RX_XOFF" not in data["log"] and "RX_BUFFER_DROP" not in data["log"]
    print("PASS RX01 finite accounting, zero-copy Write/Read baseline and final release")


def check_rx02():
    data = load("rx-02-overflow-ipv4/sustained")
    flow_summary(data, 8)
    final_rx_zero(data)
    assert "RX_BUFFER_DROP" in data["log"] and "RC_RETRANSMIT" in data["log"]
    assert "RX_XOFF" not in data["log"]
    print("PASS RX02 real finite-buffer overflow, distinct drop accounting and RC recovery")


def check_rx03():
    data = load("rx-03-auto-ipv4/sustained")
    flow_summary(data, 50)
    final_rx_zero(data)
    assert all(item in data["log"] for item in ("RX_XOFF", "RX_XON", "RX_PFC_REFRESH", "PFC_SWITCH_RX"))
    xoff = re.search(r"(\d+): \w+\.platform[^\n]*RX_XOFF priority=3", data["log"])
    assert xoff
    following = data["log"][xoff.end():]
    assert "PFC_SWITCH_RX" in following and "RX_XON" in following
    assert following.index("PFC_SWITCH_RX") < following.index("RX_XON")
    assert "RX_BUFFER_DROP" not in data["log"]
    print("PASS RX03 DMA-pressure RX Xoff, switch pause, refresh, release-driven Xon and drain")


def check_rx04():
    data = load("rx-04-propagation-ipv4/sustained")
    flow_summary(data, 50)
    final_rx_zero(data)
    assert "RX_XOFF" in data["log"] and "PFC_XOFF" in data["log"]
    assert "PFC_XON" in data["log"] and "PFC_RX" in data["log"]
    print("PASS RX04 RNIC pressure propagates through switch buffer to upstream senders")


def check_rx05():
    good = load("rx-03-auto-ipv4/sustained")
    bad = load("rx-05-insufficient-ipv4/sustained")
    assert "RX_BUFFER_DROP" not in good["log"]
    flow_summary(bad, 50)
    final_rx_zero(bad)
    assert "RX_BUFFER_DROP" in bad["log"] and "RC_RETRANSMIT" in bad["log"]
    print("PASS RX05 provisioned and insufficient RX headroom with real overflow/recovery")


def check_rx06():
    read = load("rx-06-read-ipv4/read-response")
    flow_summary(read, 50)
    final_rx_zero(read)
    operations = load("rx-06-operations-ipv4/send-recv")
    assert len(re.findall(r"SEND_BATCH_SUMMARY submitted=4 completed=4", operations["log"])) == 2
    assert len(re.findall(r"RX_CQE mode=46 status=0", operations["log"])) == 8
    final_rx_zero(operations)
    credit = load("rx-06-operations-ipv4/read-credit")
    assert len(re.findall(r"READ_CREDIT_SUMMARY completed=4 outstanding=0", credit["log"])) == 2
    multi = load("rx-06-multipacket-ipv4/multipacket")
    assert len(re.findall(r"RC_STATE_SUMMARY mode=38 submitted=1 success=1 failure=0 outstanding=0", multi["log"])) == 2
    final_rx_zero(multi)
    print("PASS RX06 Write, Read Response, SEND/RECV, read credit and multipacket lifetime")


def check_rx07():
    data = load("rx-07-multiqp-ipv4/multi-qp")
    assert len(re.findall(r"RING_SUMMARY submitted=320 completions=81 outstanding=0", data["log"])) == 2
    final_rx_zero(data)
    assert "RX_XOFF" in data["log"] and "RX_XON" in data["log"]
    print("PASS RX07 multi-QP shared RX capacity with independent QP completion and clean release")


def check_rx08():
    data = load("rx-08-reset-ipv4/merge-reset")
    assert len(re.findall(r"QP_RESET_SUMMARY flushed=1 success=1", data["log"])) == 2
    assert "PACER_QP_CLEAR" in data["log"]
    final_rx_zero(data)
    print("PASS RX08 ERR/RESET/rebuild with in-flight DMA leases and no stale double release")


def check_rx09():
    log = read_text("rx09-rnr")
    assert "RC_RNR_NAK" in log and "RNR_RECV_POSTED" in log and "RC_RNR_RETRY" in log
    assert "RX_XOFF" not in log and "RX_BUFFER_DROP" not in log
    auto = load("rx-03-auto-ipv4/sustained")
    assert "RX_PFC_REFRESH" in auto["log"]
    print("PASS RX09 RNR remains distinct from buffer PFC; sustained Xoff refresh verified")


def check_rx10():
    data = load("rx-10-auto-ipv6/sustained")
    flow_summary(data, 50)
    final_rx_zero(data)
    for name in ("server", "client1", "client2", "client3"):
        packets = read_pcap(data["path"].parent / f"rocev2.{name}.pcap")
        assert all(packet.get("ip_version") == 6 for packet in packets if not packet.get("pfc"))
    e10 = (RESULTS / "ecn-e10-check.log").read_text().splitlines()
    assert len(e10) == 144 and all(line.startswith("PASS") for line in e10)
    print("PASS RX10 IPv6 automatic PFC, existing regression, pcap and final drain")


def export_evidence():
    data = load("rx-04-propagation-ipv4/sustained")
    markers = ("RX_BUFFER_EVENT", "RX_BUFFER_DROP", "RX_XOFF", "RX_XON", "RX_PFC_REFRESH",
               "DMA write completed", "DMA read", "retry", "PFC_TX", "PFC_SWITCH_RX", "PFC_RX",
               "PFC_XOFF", "PFC_XON", "PACER_TX", "SWITCH_QUEUE_EVENT")
    rows = []
    for line in data["log"].splitlines():
        event = next((name for name in markers if name in line), None)
        if not event: continue
        prefix = re.search(r"(\d+): (\w+)\.platform", line)
        fields = dict(re.findall(r"(\w+)=([^ ]+)", line))
        tick = int(prefix.group(1)) if prefix else int(fields.get("tick", 0))
        node = prefix.group(2) if prefix else fields.get("port", "switch")
        rows.append((tick, node, event, line))
    rows.sort(key=lambda row: (row[0], row[1], row[2]))
    with (RESULTS / "rx-joint-timeseries.csv").open("w", newline="") as stream:
        writer = csv.writer(stream); writer.writerow(("tick", "node", "event", "details")); writer.writerows(rows)
    summary = []
    for tag, subdir in (("accounting", "01-account"), ("overflow", "02-overflow"),
                        ("auto", "03-auto"), ("propagation", "04-propagation"),
                        ("insufficient", "05-insufficient")):
        data = load(f"rx-{subdir}-ipv4/sustained")
        for node in SOURCES:
            packets = writes(data, node)
            unique = {event["psn"]: event for event in packets}
            span = max((e["tick"] for e in packets), default=0) - min((e["tick"] for e in packets), default=0)
            summary.append({"mode": tag, "node": node, "unique_writes": len(unique),
                            "goodput_bps": len(unique) * 64 * 8 * 1000000000000 // max(1, span),
                            "rx_drops": data["log"].count("RX_BUFFER_DROP"),
                            "rx_xoff": data["log"].count("RX_XOFF"),
                            "rx_xon": data["log"].count("RX_XON")})
    with (RESULTS / "rx-summary.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(summary[0])); writer.writeheader(); writer.writerows(summary)


CHECKS = {f"rx{i:02d}": value for i, value in enumerate(
    (check_rx01, check_rx02, check_rx03, check_rx04, check_rx05,
     check_rx06, check_rx07, check_rx08, check_rx09, check_rx10), 1)}

if __name__ == "__main__":
    selected = sys.argv[1:] or list(CHECKS)
    for name in selected:
        CHECKS[name.lower()]()
    if not selected or selected == list(CHECKS):
        export_evidence()
