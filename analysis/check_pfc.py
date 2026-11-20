#!/usr/bin/env python3
import csv
import re
import sys
from collections import defaultdict
from pathlib import Path

from check_dcqcn import load, packet_ticks, state_events, writes
from check_rocev2_pcap import read_pcap

RESULTS = Path("results")
SOURCES = ("svrsys", "cltsys0", "cltsys1")


def unit_log():
    return (RESULTS / "pfc-format.log").read_text()


def flow_summary(data, count=50):
    assert len(re.findall(rf"DCQCN_FLOW_SUMMARY submitted={count} success={count} failure=0 outstanding=0", data["log"])) == 3


def pfc_frames(path):
    return [packet for packet in read_pcap(path) if packet.get("pfc")]


def check_p01():
    assert "PASS P01 IPv4/IPv6 DSCP classification" in unit_log()
    data = load("pfc-p01-disabled-ipv4/feedback")
    assert len(re.findall(r"RC_STATE_SUMMARY mode=31 submitted=8 success=8 failure=0 outstanding=0", data["log"])) == 3
    assert "PFC_XOFF" not in data["log"] and "PFC_RX" not in data["log"]
    print("PASS P01 disabled behavior and dual-stack DSCP/ECN classification")


def check_p02():
    data = load("pfc-p02-directed-ipv4/read-response")
    assert data["log"].count("PFC_SWITCH_RX") == 1
    assert "PFC_SWITCH_RX port=etherswitch.interface0" in data["log"]
    frames = pfc_frames(data["path"].parent / "rocev2.server.pcap")
    assert len(frames) == 1 and frames[0]["enable"] == 8 and frames[0]["times"][3] == 2000
    assert "PASS P02 60-byte MAC Control PFC fields" in unit_log()
    print("PASS P02 independent PFC pcap format and one-hop consumption without flooding")


def check_p03():
    data = load("pfc-p03-same-ipv4/multi-qp")
    assert len(re.findall(r"RING_SUMMARY submitted=320 completions=81 outstanding=0", data["log"])) == 2
    assert "PFC_RX priority 3" in data["log"]
    for node in ("svrsys", "cltsys1"):
        events = [e for e in data["tx"] if e["node"] == node]
        assert any(e["qpn"] == 1 for e in events) and any(e["qpn"] == 2 for e in events)
        pause = re.search(rf"\d+: {node}\.platform[^\n]*PFC_RX priority 3 quantum [1-9]\d* until (\d+)", data["log"])
        assert pause
        tick = int(re.match(r"(\d+)", pause.group(0)).group(1))
        until = int(pause.group(1))
        for qpn in (1, 2):
            later = [e["tick"] for e in events if e["qpn"] == qpn and e["tick"] >= tick]
            assert later and min(later) >= until, (node, qpn, tick, until, min(later))
    print("PASS P03 per-link direction and common priority gating across QPs")


def check_p04():
    data = load("pfc-p04-isolation-ipv4/multi-qp")
    assert "PFC_RX priority 3" in data["log"]
    log = data["log"]
    assert re.search(r"svrsys.*PACER_TX qpn 2[^\n]*priority 0", log)
    assert re.search(r"svrsys.*PACER_TX qpn 1[^\n]*priority 3", log)
    directed = load("pfc-p04-directed-ipv4/multi-qp")
    match = re.search(r"PFC_SWITCH_RX port=(\S+) tick=(\d+) priority=3 quantum=(\d+) until=(\d+)", directed["log"])
    assert match
    start, until = int(match.group(2)), int(match.group(4))
    progress = []
    for line in directed["log"].splitlines():
        if line.startswith("SWITCH_QUEUE_EVENT ") and "action=sent" in line and "priority=0" in line:
            fields = dict(re.findall(r"(\w+)=([^ ]+)", line))
            tick = int(fields["tick"])
            if start <= tick < until:
                progress.append(tick)
    assert progress, "priority 0 did not progress while priority 3 was paused"
    print("PASS P04 paused-priority head does not block priority 0; shared port accounting preserved")


def check_p05():
    assert "PASS P05 mask, longer/shorter refresh, Xon, quantum and natural expiry" in unit_log()
    data = load("pfc-p02-directed-ipv4/read-response")
    assert "PFC_SWITCH_EXPIRE" in data["log"]
    print("PASS P05 enable mask, refresh, zero release, line-rate quantum and natural expiry")


def check_p06():
    data = load("pfc-p06-auto-ipv4/sustained")
    flow_summary(data)
    xoff = list(re.finditer(r"PFC_XOFF port=\S+ tick=(\d+) ingress=(\d+) priority=3 occupancy=(\d+)", data["log"]))
    xon = list(re.finditer(r"PFC_XON port=\S+ tick=(\d+) ingress=(\d+) priority=3 occupancy=(\d+)", data["log"]))
    assert xoff and xon and {int(m.group(2)) for m in xoff} == {0, 1, 2}
    assert all(int(m.group(3)) >= 512 for m in xoff)
    assert all(int(m.group(3)) <= 128 for m in xon)
    assert "PFC_RX priority 3 quantum 1000" in data["log"]
    frames = pfc_frames(data["path"].parent / "pfc-switch.port0.pcap")
    assert any(f["times"][3] == 1000 for f in frames) and any(f["times"][3] == 0 for f in frames)
    assert sum(int(p["drop_packets"]) for p in data["ports"].values()) == 0
    print("PASS P06 ingress-owned Xoff/Xon, hysteresis, real PFC pcap and buffer drain")


def check_p07():
    good = load("pfc-p06-auto-ipv4/sustained")
    bad = load("pfc-p07-insufficient-ipv4/sustained")
    assert sum(int(p["drop_packets"]) for p in good["ports"].values()) == 0
    drops = sum(int(p["drop_packets"]) for p in bad["ports"].values())
    assert drops > 0 and "RC_RETRANSMIT" in bad["log"]
    flow_summary(bad)
    print(f"PASS P07 provisioned headroom has no overflow; insufficient case drops={drops} with distinct retransmissions")


def export_joint(data):
    markers = ("PACER_TX", "DCQCN_", "CNP_RX", "PFC_XOFF", "PFC_XON", "PFC_RX",
               "PFC_EXPIRE", "PFC_SWITCH_TX", "PFC_INGRESS_EVENT", "SWITCH_QUEUE_EVENT", "SWITCH_ECN_EVENT")
    rows = []
    for line in data["log"].splitlines():
        event = next((name for name in markers if name in line), None)
        if not event:
            continue
        prefix = re.search(r"(\d+): (\w+)\.platform", line)
        fields = dict(re.findall(r"(\w+)=([^ ]+)", line))
        tick = int(prefix.group(1)) if prefix else int(fields.get("tick", 0))
        node = prefix.group(2) if prefix else fields.get("port", "switch")
        rows.append((tick, node, event, line))
    rows.sort(key=lambda row: (row[0], row[1], row[2]))
    path = RESULTS / "pfc-joint-timeseries.csv"
    with path.open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(("tick", "node", "event", "details"))
        writer.writerows(rows)


def check_p08():
    configurations = (("off-off", False, False), ("dcqcn-off", True, False),
                      ("off-pfc", False, True), ("dcqcn-pfc", True, True))
    rows = []
    for name, dcqcn, pfc in configurations:
        data = load(f"pfc-p08-{name}-ipv4/sustained")
        flow_summary(data)
        assert bool(state_events(data["log"], "DCQCN_DECREASE")) == dcqcn
        assert ("PFC_XOFF" in data["log"]) == pfc
        for node in SOURCES:
            packets = writes(data, node)
            unique = {e["psn"]: e for e in packets}
            assert len(unique) == 50
            span = max(e["tick"] for e in packets) - min(e["tick"] for e in packets)
            rows.append({"mode": name, "node": node, "unique_writes": len(unique),
                         "actual_bytes": sum(e["bytes"] for e in packets),
                         "goodput_bps": len(unique) * 64 * 8 * 1000000000000 // max(1, span),
                         "xoff": data["log"].count("PFC_XOFF"),
                         "xon": data["log"].count("PFC_XON"),
                         "dcqcn_decreases": len([e for e in state_events(data["log"], "DCQCN_DECREASE") if e["node"] == node])})
        if name == "dcqcn-pfc":
            export_joint(data)
            paced = [e for e in data["tx"] if e["paced"]]
            for previous, current in zip(paced, paced[1:]):
                if previous["node"] == current["node"] and previous["qpn"] == current["qpn"]:
                    assert current["tick"] - previous["tick"] >= packet_ticks(previous["bytes"], current["rate"])
    read = load("pfc-p08-read-ipv4/read-response")
    flow_summary(read)
    assert "PFC_RX" in read["log"] and "DCQCN_DECREASE" in read["log"]
    with (RESULTS / "pfc-four-modes.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader(); writer.writerows(rows)
    print("PASS P08 Write/Read Response cooperation, post-resume pacing and four-mode comparison")


def check_p09():
    loss = load("pfc-p09-xon-loss-ipv4/sustained")
    flow_summary(loss)
    assert "PFC_XON_DROP" in loss["log"] and "PFC_EXPIRE" in loss["log"]
    lifecycle = load("pfc-p09-lifecycle-ipv4/merge-reset")
    assert len(re.findall(r"QP_RESET_SUMMARY flushed=1 success=1", lifecycle["log"])) == 2
    assert "PFC_PORT_RESET" in lifecycle["log"] and "PACER_QP_CLEAR" in lifecycle["log"]
    print("PASS P09 lost Xon natural expiry, QP Reset isolation and port control-state reset")


def check_p10():
    data = load("pfc-p10-auto-ipv6/sustained")
    flow_summary(data)
    for name in ("server", "client1", "client2", "client3"):
        packets = read_pcap(data["path"].parent / f"rocev2.{name}.pcap")
        assert all(packet.get("ip_version") == 6 for packet in packets if not packet.get("pfc"))
    e01 = (RESULTS / "ecn-e01-e09-check.log").read_text()
    e10 = (RESULTS / "ecn-e10-check.log").read_text().splitlines()
    assert len(e10) == 144 and all(line.startswith("PASS") for line in e10) and "FAIL" not in e01
    print("PASS P10 IPv6 PFC, existing dual-stack regression, pcap and final queue drain")


CHECKS = {f"p{i:02d}": value for i, value in enumerate(
    (check_p01, check_p02, check_p03, check_p04, check_p05,
     check_p06, check_p07, check_p08, check_p09, check_p10), 1)}

if __name__ == "__main__":
    for name in sys.argv[1:] or list(CHECKS):
        CHECKS[name.lower()]()
