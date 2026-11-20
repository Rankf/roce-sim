#!/usr/bin/env python3
import csv
import re
import sys
from pathlib import Path

from check_dcqcn import load, packet_ticks, state_events, writes
from check_rocev2_pcap import read_pcap
from check_rx import final_rx_zero

RESULTS = Path("results")
SOURCES = ("svrsys", "cltsys0", "cltsys1")
S0_LINK = "etherswitch.interface2.outputFifo"
S1_SINK = "etherswitch1.interface1.outputFifo"
S1_LINK = "etherswitch1.interface2.outputFifo"


def flow_summary(data, count=50):
    assert len(re.findall(rf"DCQCN_FLOW_SUMMARY submitted={count} success={count} failure=0 outstanding=0", data["log"])) == 3


def pfc_frames(path):
    if path.stat().st_size == 0:
        return []
    return [packet for packet in read_pcap(path) if packet.get("pfc")]


def pfc_events(log, event, port):
    port = port.removesuffix(".outputFifo")
    pattern = rf"{event} port={re.escape(port)} tick=(\d+) ingress=(\d+) priority=3 occupancy=(\d+)"
    return [tuple(map(int, match.groups())) for match in re.finditer(pattern, log)]


def static_routes(log):
    expected = {
        ("etherswitch", 10): 0, ("etherswitch", 11): 1,
        ("etherswitch", 12): 2, ("etherswitch", 13): 2,
        ("etherswitch1", 10): 2, ("etherswitch1", 11): 2,
        ("etherswitch1", 12): 0, ("etherswitch1", 13): 1,
    }
    actual = {}
    for match in re.finditer(r"SWITCH_STATIC_ROUTE switch=(\S+) mac=(\d+) port=(\d+)", log):
        actual[(match.group(1), int(match.group(2)))] = int(match.group(3))
    assert actual == expected, actual


def link_stats(data):
    stats = {}
    for line in data["log"].splitlines():
        if not line.startswith("ETHER_LINK_EVENT "):
            continue
        fields = dict(re.findall(r"(\w+)=([^ ]+)", line))
        key = (fields["link"], int(fields["direction"]))
        stat = stats.setdefault(key, {"accepted_packets": 0, "accepted_bytes": 0,
                                      "delivered_packets": 0, "delivered_bytes": 0})
        action = fields["action"]
        assert action in ("accepted", "delivered")
        stat[f"{action}_packets"] += 1
        stat[f"{action}_bytes"] += int(fields["bytes"])
        stat["in_flight_packets"] = int(fields["in_flight_packets"])
        stat["in_flight_bytes"] = int(fields["in_flight_bytes"])
    assert len(stats) in (0, 2), stats
    for key, stat in stats.items():
        assert stat["accepted_packets"] == stat["delivered_packets"] + stat["in_flight_packets"], key
        assert stat["accepted_bytes"] == stat["delivered_bytes"] + stat["in_flight_bytes"], key
        assert stat["in_flight_packets"] == 0 and stat["in_flight_bytes"] == 0, key
    return stats


def resources(data, rx=True):
    static_routes(data["log"])
    assert len(data["ports"]) == 6
    links = link_stats(data)
    assert len(links) == 2
    if rx:
        final_rx_zero(data)
    return links


def queue_events(log, port):
    result = []
    for line in log.splitlines():
        if not line.startswith("SWITCH_QUEUE_EVENT ") or f"port={port} " not in line:
            continue
        fields = dict(re.findall(r"(\w+)=([^ ]+)", line))
        result.append({key: int(value) if value.isdigit() else value for key, value in fields.items()})
    return result


def pause_windows(log, port):
    port = port.removesuffix(".outputFifo")
    return [(int(match.group(1)), int(match.group(2))) for match in re.finditer(
        rf"PFC_SWITCH_RX port={re.escape(port)} tick=(\d+) priority=3 quantum=[1-9]\d* until=(\d+)", log)]


def during(tick, windows):
    return any(start <= tick < until for start, until in windows)


def check_ms01():
    for operation in ("write", "read", "send"):
        data = load(f"mspfc-01-basic-ipv4/{operation}")
        static_routes(data["log"])
        final_rx_zero(data)
        assert link_stats(data) == {}
        if operation == "send":
            assert len(re.findall(r"TX_CQE mode=41 status=0", data["log"])) == 2
            assert len(re.findall(r"RX_CQE mode=41 status=0", data["log"])) == 2
        else:
            assert len(re.findall(r"FIXED_SUMMARY submitted=16 success=16 failure=0 outstanding=0", data["log"])) == 2
    for version in (4, 6):
        data = load(f"mspfc-01-basic-ipv{version}/sustained")
        flow_summary(data, 8)
        resources(data)
        assert "PFC_XOFF" not in data["log"] and "PFC_RX" not in data["log"]
        assert "RX_XOFF" not in data["log"] and "RX_BUFFER_DROP" not in data["log"]
        for name in ("server", "client1", "client2", "client3"):
            packets = read_pcap(data["path"].parent / f"rocev2.{name}.pcap")
            assert packets and all(packet.get("ip_version") == version for packet in packets)
    print("PASS MS01 static local/cross-switch/reverse RC forwarding and dual-stack completion")


def check_ms02():
    data = load("mspfc-01-basic-ipv4/sustained")
    flow_summary(data, 8)
    links = resources(data)
    assert all(stat["accepted_packets"] and stat["delivered_packets"] for stat in links.values())
    assert "ETHER_LINK_EVENT" in data["log"] and "action=accepted" in data["log"] and "action=delivered" in data["log"]
    events = queue_events(data["log"], S0_LINK)
    assert any(event.get("src_mac") == 10 and event.get("dst_mac") == 13 for event in events)
    assert any(event.get("src_mac") == 11 and event.get("dst_mac") == 13 for event in events)
    print("PASS MS02 per-switch conservation, explicit link in-flight accounting and clean RX lease release")


def check_ms03():
    data = load("mspfc-03-link-ipv4/sustained")
    flow_summary(data)
    resources(data, rx=False)
    assert {ingress for _, ingress, _ in pfc_events(data["log"], "PFC_XOFF", S0_LINK)} == {0, 1}
    assert pfc_events(data["log"], "PFC_XON", S0_LINK)
    assert not re.search(r"PFC_XOFF port=etherswitch1\.", data["log"])
    for node in ("svrsys", "cltsys0"):
        assert re.search(rf"{node}\.platform[^\n]*PFC_RX priority 3 quantum [1-9]", data["log"])
    assert not re.search(r"cltsys1\.platform[^\n]*PFC_RX", data["log"])
    command = (data["path"].parent / "command.txt").read_text()
    assert "--dma-delay" not in command
    assert sum(int(port["drop_packets"]) for port in data["ports"].values()) == 0
    print("PASS MS03 inter-switch link bottleneck pauses only SW1 ingress A/B and recovers without RX pressure")


def check_ms04():
    control = load("mspfc-04-control-ipv4/sustained")
    assert len(re.findall(r"RING_SUMMARY submitted=320 completions=81 outstanding=0", control["log"])) == 3
    resources(control)
    assert "RX_XOFF" not in control["log"] and "RX_BUFFER_DROP" not in control["log"]
    control_command = (control["path"].parent / "command.txt").read_text()
    assert "--dma-delay 0t" in control_command
    data = load("mspfc-04-rx-ipv4/sustained")
    assert len(re.findall(r"RING_SUMMARY submitted=320 completions=81 outstanding=0", data["log"])) == 3
    resources(data)
    command = (data["path"].parent / "command.txt").read_text()
    assert "--dma-delay 500us" in command and "--dma-delay-node 3" in command
    assert "--retrans-timeout 100ms" in command
    assert all(item in data["log"] for item in ("RX_XOFF", "RX_XON", "RX_PFC_REFRESH"))
    assert re.search(r"cltsys2\.platform[^\n]*RX_XOFF priority=3", data["log"])
    assert not re.search(r"(?:svrsys|cltsys0|cltsys1)\.platform[^\n]*RX_XOFF", data["log"])
    assert re.search(r"PFC_SWITCH_RX port=etherswitch1.interface1[^\n]*quantum=10000", data["log"])
    assert re.search(r"PFC_SWITCH_RX port=etherswitch.interface2[^\n]*quantum=10000", data["log"])
    assert {ingress for _, ingress, _ in pfc_events(data["log"], "PFC_XOFF", S1_SINK)} == {0, 2}
    assert {ingress for _, ingress, _ in pfc_events(data["log"], "PFC_XOFF", S0_LINK)} == {0, 1}
    for node in SOURCES:
        assert re.search(rf"{node}\.platform[^\n]*PFC_RX priority 3 quantum [1-9]", data["log"]), node
    assert "RX_BUFFER_DROP" not in data["log"]
    print("PASS MS04 D-only DMA pressure propagates D→SW2→SW1→A/B with local C branch and normal-memory control")


def check_ms05():
    data = load("mspfc-05-recovery-ipv4/sustained")
    flow_summary(data)
    resources(data)
    assert "PFC_XON_DROP" in data["log"]
    assert "PFC_SWITCH_EXPIRE" in data["log"] or "PFC_EXPIRE" in data["log"]
    assert pfc_events(data["log"], "PFC_XOFF", S1_SINK) and pfc_events(data["log"], "PFC_XON", S1_SINK)
    assert pfc_events(data["log"], "PFC_XOFF", S0_LINK) and pfc_events(data["log"], "PFC_XON", S0_LINK)
    assert data["log"].rfind("RX_PFC_REFRESH") < data["log"].rfind("RX_XON")
    path = data["path"].parent
    assert not pfc_frames(path / "pfc-switch.switch0.port2.pcap")
    assert not pfc_frames(path / "pfc-switch.switch1.port1.pcap")
    frames = pfc_frames(path / "pfc-switch.switch1.port2.pcap")
    assert any(frame["times"][3] == 10000 for frame in frames)
    print("PASS MS05 independent local Xon, sustained refresh termination, lost-Xon expiry and no PFC forwarding")


def check_ms06():
    good = load("mspfc-04-rx-ipv4/sustained")
    assert sum(int(port["drop_packets"]) for port in good["ports"].values()) == 0
    bad = load("mspfc-06-insufficient-ipv4/sustained")
    flow_summary(bad)
    resources(bad)
    drops = {name: int(port["drop_packets"]) for name, port in bad["ports"].items() if port["drop_packets"]}
    assert drops and all(name.startswith("etherswitch1.") for name in drops), drops
    assert "RC_RETRANSMIT" in bad["log"] and "RX_BUFFER_DROP" not in bad["log"]
    print(f"PASS MS06 only SW2 headroom is reduced; localized drops={drops} with RC recovery")


def check_ms07():
    same = load("mspfc-07-same-ipv4/priority")
    isolated = load("mspfc-07-isolated-ipv4/priority")
    for data in (same, isolated):
        assert len(re.findall(r"RING_SUMMARY submitted=80 completions=21 outstanding=0", data["log"])) == 2
        resources(data)
    same_windows = pause_windows(same["log"], S0_LINK)
    isolated_windows = pause_windows(isolated["log"], S0_LINK)
    assert same_windows and isolated_windows
    same_events = queue_events(same["log"], S0_LINK)
    isolated_events = queue_events(isolated["log"], S0_LINK)
    assert any(event.get("src_mac") == 11 and event.get("dst_mac") == 12 and
               event["action"] == "sent" for event in same_events)
    assert not any(event["action"] == "sent" and event.get("src_mac") == 11 and
                   event.get("dst_mac") == 12 and during(event["tick"], same_windows)
                   for event in same_events)
    assert not any(event["action"] == "sent" and event["priority"] == 3 and
                   during(event["tick"], isolated_windows) for event in isolated_events)
    assert any(event["action"] == "sent" and event["priority"] == 0 and
               event.get("src_mac") == 11 and event.get("dst_mac") == 12 and
               during(event["tick"], isolated_windows) for event in isolated_events)
    print("PASS MS07 shared-link same-priority B→C stall and priority-0 progress during priority-3 pause")


def check_ms08():
    bidirectional = load("mspfc-08-bidirectional-ipv4/bidirectional")
    assert len(re.findall(r"\[SERVER: Server\d+-\d+\] FIXED_SUMMARY submitted=16 success=16 failure=0 outstanding=0", bidirectional["log"])) == 2
    assert len(re.findall(r"\[CLIENT: Client\d+-\d+\] CLT_FIXED_SUMMARY submitted=16 success=16 failure=0 outstanding=0", bidirectional["log"])) == 2
    links = resources(bidirectional)
    assert all(stat["accepted_packets"] for stat in links.values())
    read = load("mspfc-08-read-ipv4/read-response")
    flow_summary(read, 20)
    resources(read)
    assert any(event["opcode"] in (0x0d, 0x0e, 0x0f, 0x10) for event in read["tx"])
    send = load("mspfc-08-send-ipv4/send-recv")
    assert len(re.findall(r"SEND_BATCH_SUMMARY submitted=4 completed=4", send["log"])) == 2
    assert len(re.findall(r"RX_CQE mode=46 status=0", send["log"])) == 8
    resources(send)
    reset = load("mspfc-08-reset-ipv4/merge-reset")
    assert len(re.findall(r"QP_RESET_SUMMARY flushed=1 success=1", reset["log"])) == 2
    assert "PACER_QP_CLEAR" in reset["log"]
    resources(reset)
    print("PASS MS08 bidirectional Write, Read Response, SEND and Reset/late-DMA lifecycle across switches")


def check_ms09():
    data = load("mspfc-09-joint-ipv4/sustained")
    flow_summary(data)
    resources(data)
    assert "RX_XOFF" in data["log"] and "PFC_XOFF" in data["log"]
    assert re.search(r"SWITCH_ECN_EVENT port=etherswitch\.[^\n]*action=2", data["log"])
    assert re.search(r"SWITCH_ECN_EVENT port=etherswitch1\.[^\n]*action=3", data["log"])
    assert re.search(r"SWITCH_ECN_EVENT port=etherswitch1\.[^\n]*action=2", data["log"])
    assert sum(port["ecn_marked"] for name, port in data["ports"].items() if name.startswith("etherswitch.")) > 0
    assert sum(port["ecn_already"] for name, port in data["ports"].items() if name.startswith("etherswitch1.")) > 0
    for node in SOURCES:
        decreases = [event for event in state_events(data["log"], "DCQCN_DECREASE")
                     if event["node"] == node]
        assert decreases, node
        packets = writes(data, node)
        assert any(event["paced"] and event["rate"] < 100000000000 and
                   event["tick"] > decreases[0]["tick"] for event in packets), node
    paced = [event for event in data["tx"] if event["paced"]]
    for previous, current in zip(paced, paced[1:]):
        if previous["node"] == current["node"] and previous["qpn"] == current["qpn"]:
            assert current["tick"] - previous["tick"] >= packet_ticks(previous["bytes"], current["rate"])
    assert any(event["opcode"] == 0x81 and not event["paced"] for event in data["tx"])
    for name in ("server", "client1", "client2", "client3"):
        assert read_pcap(data["path"].parent / f"rocev2.{name}.pcap")
    print("PASS MS09 CE survives the second hop; CNP attribution, DCQCN recovery and pacing remain correct")


def check_ms10():
    for tag in ("10-rx", "10-joint"):
        data = load(f"mspfc-{tag}-ipv6/sustained")
        flow_summary(data)
        resources(data)
        assert "RX_XOFF" in data["log"] and "PFC_XOFF" in data["log"]
        for name in ("server", "client1", "client2", "client3"):
            packets = read_pcap(data["path"].parent / f"rocev2.{name}.pcap")
            assert packets and all(packet.get("ip_version") == 6 for packet in packets if not packet.get("pfc"))
    joint = load("mspfc-10-joint-ipv6/sustained")
    assert re.search(r"SWITCH_ECN_EVENT port=etherswitch1\.[^\n]*action=3", joint["log"])
    e01 = (RESULTS / "ecn-e01-e09-check.log").read_text()
    e10 = (RESULTS / "ecn-e10-check.log").read_text().splitlines()
    assert len(e10) == 144 and all(line.startswith("PASS") for line in e10) and "FAIL" not in e01
    for name in ("pfc-all.log", "rx-all.log"):
        lines = (RESULTS / name).read_text().splitlines()
        assert len(lines) == 10 and all(line.startswith("PASS") for line in lines)
    print("PASS MS10 IPv6 PFC/CE/DCQCN, independent pcap, final drain and frozen 144/10/10 regressions")


def export_evidence():
    data = load("mspfc-09-joint-ipv4/sustained")
    markers = ("RX_BUFFER_EVENT", "RX_BUFFER_DROP", "RX_XOFF", "RX_XON", "RX_PFC_REFRESH",
               "DMA write completed", "DMA read", "PFC_TX", "PFC_SWITCH_RX", "PFC_RX",
               "PFC_XOFF", "PFC_XON", "PACER_TX", "DCQCN_", "CNP_RX",
               "ETHER_LINK_EVENT", "SWITCH_QUEUE_EVENT", "SWITCH_ECN_EVENT")
    rows = []
    for line in data["log"].splitlines():
        event = next((name for name in markers if name in line), None)
        if not event:
            continue
        prefix = re.search(r"(\d+): (\w+)\.platform", line)
        fields = dict(re.findall(r"(\w+)=([^ ]+)", line))
        tick = int(prefix.group(1)) if prefix else int(fields.get("tick", 0))
        device = prefix.group(2) if prefix else fields.get("port", fields.get("link", "switch")).split(".")[0]
        priority = fields.get("priority", "")
        if not priority:
            match = re.search(r"priority[ =](\d+)", line)
            priority = match.group(1) if match else ""
        direction = fields.get("direction", "")
        if not direction:
            direction = "rx" if event in ("PFC_RX", "PFC_SWITCH_RX", "RX_XOFF", "RX_XON") else "tx"
        rows.append((tick, device, fields.get("port", fields.get("link", "")), direction,
                     priority, fields.get("src_mac", ""), fields.get("dst_mac", ""),
                     fields.get("ingress", ""), event, line))
    rows.sort(key=lambda row: (row[0], row[1], row[2], row[8]))
    with (RESULTS / "mspfc-joint-timeseries.csv").open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(("tick", "device", "port", "direction", "priority", "src_mac",
                         "dst_mac", "ingress", "event", "details"))
        writer.writerows(rows)

    summary = []
    cases = (("link", "03-link", "ipv4", 50), ("control", "04-control", "ipv4", 162),
             ("rx", "04-rx", "ipv4", 162), ("recovery", "05-recovery", "ipv4", 50),
             ("insufficient", "06-insufficient", "ipv4", 50),
             ("joint", "09-joint", "ipv4", 50), ("ipv6-rx", "10-rx", "ipv6", 50),
             ("ipv6-joint", "10-joint", "ipv6", 50))
    for mode, tag, version, count in cases:
        item = load(f"mspfc-{tag}-{version}/sustained")
        for node in SOURCES:
            packets = writes(item, node)
            unique = {event["psn"]: event for event in packets}
            assert len(unique) == count
            span = max(event["tick"] for event in packets) - min(event["tick"] for event in packets)
            summary.append({"mode": mode, "node": node, "unique_writes": len(unique),
                            "goodput_bps": len(unique) * 64 * 8 * 1000000000000 // max(1, span),
                            "sw1_drops": sum(int(port["drop_packets"]) for name, port in item["ports"].items()
                                             if name.startswith("etherswitch.")),
                            "sw2_drops": sum(int(port["drop_packets"]) for name, port in item["ports"].items()
                                             if name.startswith("etherswitch1.")),
                            "rx_drops": item["log"].count("RX_BUFFER_DROP"),
                            "rx_xoff": item["log"].count("RX_XOFF"),
                            "switch_xoff": item["log"].count("PFC_XOFF"),
                            "dcqcn_decreases": len([event for event in state_events(item["log"], "DCQCN_DECREASE")
                                                    if event["node"] == node])})
    with (RESULTS / "mspfc-summary.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(summary[0]))
        writer.writeheader()
        writer.writerows(summary)


CHECKS = {f"ms{i:02d}": value for i, value in enumerate(
    (check_ms01, check_ms02, check_ms03, check_ms04, check_ms05,
     check_ms06, check_ms07, check_ms08, check_ms09, check_ms10), 1)}

if __name__ == "__main__":
    selected = sys.argv[1:] or list(CHECKS)
    for name in selected:
        CHECKS[name.lower()]()
    if not selected or selected == list(CHECKS):
        export_evidence()
