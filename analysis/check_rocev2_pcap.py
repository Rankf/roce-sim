#!/usr/bin/env python3
import argparse
import ipaddress
import re
import struct
from collections import Counter
from pathlib import Path

WRITE_PAYLOAD = b"Hello World!  Hello RDMA Write! Hello World!  Hello RDMA Write!\0"
READ_PAYLOAD = b"Hello World!  Hello RDMA Read ! Hello World!  Hello RDMA Read !\0"
RETH_OPS = {0x06, 0x0A, 0x0B, 0x0C}
AETH_OPS = {0x0D, 0x0F, 0x10, 0x11}
IMM_OPS = {0x03, 0x05, 0x09, 0x0B}
ATOMIC_REQUEST_OPS = {0x13, 0x14}
ATOMIC_ACK_OPS = {0x12}
IETH_OPS = {0x16, 0x17}


def be16(data, offset):
    return struct.unpack_from("!H", data, offset)[0]


def be32(data, offset):
    return struct.unpack_from("!I", data, offset)[0]


def be64(data, offset):
    return struct.unpack_from("!Q", data, offset)[0]


def ipv4_checksum(header):
    total = sum(be16(header, offset) for offset in range(0, 20, 2))
    while total >> 16:
        total = (total & 0xFFFF) + (total >> 16)
    return (~total) & 0xFFFF


def invariant_crc(packet):
    ipv6 = be16(packet, 12) == 0x86DD
    udp = 54 if ipv6 else 34
    variant = {21, udp + 6, udp + 7} if ipv6 else {15, 22, 24, 25, udp + 6, udp + 7}
    if ipv6:
        variant.update({15, 16, 17, 18})
    crc = 0xFFFFFFFF
    for index in range(14, len(packet) - 4):
        byte = 0xFF if index in variant else packet[index]
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ (0xEDB88320 if crc & 1 else 0)
    return crc ^ 0xFFFFFFFF


def udp_checksum(packet):
    udp = 54 if be16(packet, 12) == 0x86DD else 34
    total = 17 + be16(packet, udp + 4)
    for offset in range(22, 54, 2):
        total += be16(packet, offset)
    for offset in range(udp, len(packet), 2):
        total += be16(packet, offset)
    while total >> 16:
        total = (total & 0xFFFF) + (total >> 16)
    return (~total) & 0xFFFF


def parse_packet(packet):
    ether_type = be16(packet, 12)
    if ether_type == 0x8808:
        assert len(packet) == 60, "PFC must be a 60-byte frame without Ethernet FCS"
        assert packet[:6] == bytes.fromhex("0180c2000001"), "bad PFC destination MAC"
        assert be16(packet, 14) == 0x0101, "bad PFC MAC Control opcode"
        enable = be16(packet, 16)
        assert enable & 0xFF00 == 0, "PFC upper enable bits must be zero"
        assert packet[34:] == bytes(26), "PFC padding must be zero"
        return {
            "pfc": True,
            "opcode": 0x0101,
            "enable": enable,
            "times": [be16(packet, 18 + 2 * index) for index in range(8)],
            "src_mac": ":".join(f"{byte:02x}" for byte in packet[6:12]),
        }
    ipv6 = ether_type == 0x86DD
    assert ipv6 or ether_type == 0x0800, "unsupported IP address family"
    ip_size = 40 if ipv6 else 20
    udp = 14 + ip_size
    bth = udp + 8
    assert len(packet) >= bth + 16, "truncated Ethernet/IP/UDP/BTH/ICRC packet"
    if ipv6:
        assert packet[14] >> 4 == 6, "bad IPv6 version"
        assert be16(packet, 18) == len(packet) - 14 - 40, "bad IPv6 payload length"
        assert packet[20] == 17 and packet[21] == 64, "bad IPv6 next header or hop limit"
        checksum = be16(packet, udp + 6)
        assert checksum == 0 or udp_checksum(packet) == 0, "bad IPv6 UDP checksum"
        src_ip = str(ipaddress.IPv6Address(bytes(packet[22:38])))
        dst_ip = str(ipaddress.IPv6Address(bytes(packet[38:54])))
    else:
        assert packet[14] == 0x45, "not a 20-byte IPv4 header"
        assert be16(packet, 16) == len(packet) - 14, "bad IPv4 total length"
        assert packet[22] == 64 and packet[23] == 17, "bad TTL or non-UDP protocol"
        assert ipv4_checksum(packet[14:34]) == 0, "bad IPv4 header checksum"
        assert be16(packet, udp + 6) == 0, "IPv4 UDP checksum must be zero in this model"
        src_ip = ".".join(str(x) for x in packet[26:30])
        dst_ip = ".".join(str(x) for x in packet[30:34])
    assert be16(packet, udp + 2) == 4791, "not RoCEv2 UDP destination port 4791"
    assert be16(packet, udp + 4) == len(packet) - udp, "bad UDP length"

    opcode = packet[bth]
    traffic_class = (((packet[14] & 0x0F) << 4) | (packet[15] >> 4)) if ipv6 else packet[15]
    dscp = traffic_class >> 2
    assert be16(packet, bth + 2) == 0xFFFF, "unexpected BTH P_Key"
    assert be32(packet, len(packet) - 4) == invariant_crc(packet), "bad ICRC"
    extension = ((16 if opcode in RETH_OPS else 0) +
                 (4 if opcode in AETH_OPS else 0) +
                 (4 if opcode in IMM_OPS else 0) +
                 (28 if opcode in ATOMIC_REQUEST_OPS else 0) +
                 (8 if opcode in ATOMIC_ACK_OPS else 0) +
                 (4 if opcode in IETH_OPS else 0) +
                 (16 if opcode == 0x81 else 0))
    transport = bth + 12
    payload_offset = transport + extension
    assert payload_offset + 4 <= len(packet), "truncated transport extension"
    result = {
        "opcode": opcode,
        "qpn": be32(packet, bth + 4) & 0xFFFFFF,
        "psn": be32(packet, bth + 8) & 0xFFFFFF,
        "ack_request": bool(packet[bth + 8] & 0x80),
        "payload": packet[payload_offset:-4],
        "src_ip": src_ip,
        "dst_ip": dst_ip,
        "ip_version": 6 if ipv6 else 4,
        "ecn": ((packet[15] >> 4) & 3) if ipv6 else (packet[15] & 3),
        "dscp": dscp,
        "priority": dscp >> 3,
    }
    if opcode == 0x81:
        assert result["psn"] == 0 and not result["ack_request"]
        assert packet[transport:transport + 16] == bytes(16)
    if opcode in RETH_OPS:
        result["reth"] = (be64(packet, transport), be32(packet, transport + 8),
                          be32(packet, transport + 12))
    if opcode in ATOMIC_REQUEST_OPS:
        result["atomic"] = (be64(packet, transport), be32(packet, transport + 8),
                            be64(packet, transport + 12), be64(packet, transport + 20))
    if opcode in ATOMIC_ACK_OPS:
        result["original"] = be64(packet, transport)
    if opcode in IETH_OPS:
        result["invalidated_rkey"] = be32(packet, transport)
    if opcode in AETH_OPS:
        result["syndrome"] = packet[transport]
        result["credit"] = packet[transport + 1] & 0x1F
    if opcode in IMM_OPS:
        result["immediate"] = be32(packet, transport +
            (16 if opcode in RETH_OPS else 0) + (4 if opcode in AETH_OPS else 0))
    return result


def read_pcap(path):
    data = path.read_bytes()
    assert len(data) >= 24, f"{path}: missing pcap header"
    if data[:4] == b"\xd4\xc3\xb2\xa1":
        endian = "<"
    elif data[:4] == b"\xa1\xb2\xc3\xd4":
        endian = ">"
    else:
        raise AssertionError(f"{path}: unsupported pcap magic")
    magic, major, minor, zone, sigfigs, snaplen, network = struct.unpack_from(
        endian + "IHHIIII", data, 0)
    assert magic == 0xA1B2C3D4 and (major, minor) == (2, 1), f"{path}: bad pcap version"
    assert network == 1 and snaplen >= 65535, f"{path}: not Ethernet pcap"
    offset = 24
    packets = []
    while offset < len(data):
        assert offset + 16 <= len(data), f"{path}: truncated record header"
        seconds, micros, captured, original = struct.unpack_from(endian + "IIII", data, offset)
        offset += 16
        assert captured == original and offset + captured <= len(data), f"{path}: truncated record"
        packets.append(parse_packet(data[offset:offset + captured]))
        offset += captured
    assert packets, f"{path}: no packets"
    return packets


def check_direction_and_payload(result, captures):
    run = (result / "run.yaml").read_text()
    operation = re.search(r"^operation=(write|read)$", run, re.MULTILINE).group(1)
    mode = int(re.search(r"^protect_mode=(\d+)$", run, re.MULTILINE).group(1))
    server = captures["server"]
    client = captures["client1"]
    version = int(re.search(r"^roce_ip_version=(\d+)$", run, re.MULTILINE).group(1))
    server_ip = "fd00::a" if version == 6 else "10.0.0.10"
    client_ip = "fd00::b" if version == 6 else "10.0.0.11"
    for packet in server:
        assert packet["ip_version"] == version
        assert packet["src_ip"] == server_ip and packet["dst_ip"] == client_ip
    for packet in client:
        assert packet["ip_version"] == version
        assert packet["src_ip"] == client_ip and packet["dst_ip"] == server_ip
    if mode in {8, 9, 10, 36} or 40 <= mode <= 100:
        return
    if operation == "write":
        writes = [p for p in server if p["opcode"] in {0x06, 0x07, 0x08, 0x0A}]
        assert writes and any(p["opcode"] == 0x11 for p in client), "Write/ACK sequence missing"
        expected_ops = [0x08, 0x06, 0x08] if mode == 38 else ([0x06, 0x08] if mode == 20 else [0x0A])
        assert [p["opcode"] for p in writes[:len(expected_ops)]] == expected_ops
        for index, packet in enumerate(writes[:len(expected_ops)]):
            if mode == 38:
                expected = WRITE_PAYLOAD + bytes(4096 - len(WRITE_PAYLOAD)) if packet["psn"] == 0 else bytes(4096)
            elif mode == 20:
                expected = WRITE_PAYLOAD + bytes(4096 - len(WRITE_PAYLOAD)) if index == 0 else bytes(4096)
            elif mode in {29, 31, 33, 35, 37}:
                continue
            else:
                expected = WRITE_PAYLOAD
            assert packet["payload"] == expected, "Write payload differs from reference"
            if packet["opcode"] in RETH_OPS:
                assert packet["reth"][2] == (8192 if mode in {20, 38} else 64)
    else:
        requests = [p for p in server if p["opcode"] == 0x0C]
        responses = [p for p in client if p["opcode"] in {0x0D, 0x0E, 0x0F, 0x10}]
        assert requests, "Read Request missing"
        if not responses:
            assert mode == 4 and any(p["opcode"] == 0x11 and p["syndrome"] != 0 for p in client), "Read NAK missing"
            return
        expected_length = 12288 if mode == 39 else (8192 if mode == 21 else 64)
        assert requests[0]["reth"][2] == expected_length
        expected_ops = [0x0D, 0x0E, 0x0F] if mode == 39 else ([0x0D, 0x0F] if mode == 21 else [0x10])
        assert [p["opcode"] for p in responses[:len(expected_ops)]] == expected_ops
        for index, packet in enumerate(responses[:len(expected_ops)]):
            if mode in {30, 32, 34}:
                continue
            if mode in {21, 39}:
                expected = READ_PAYLOAD + bytes(4096 - len(READ_PAYLOAD)) if index == 0 else bytes(4096)
            else:
                expected = READ_PAYLOAD
            assert packet["payload"] == expected, "Read payload differs from reference"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("results", nargs="+", type=Path)
    args = parser.parse_args()
    for result in args.results:
        if not result.is_dir():
            continue
        paths = sorted(result.glob("rocev2.*.pcap"))
        assert len(paths) == 2, f"{result}: expected server and client pcap files"
        captures = {path.stem.split(".")[1]: read_pcap(path) for path in paths}
        check_direction_and_payload(result, captures)
        counts = Counter(packet["opcode"] for packets in captures.values() for packet in packets)
        summary = ",".join(f"0x{opcode:02x}:{count}" for opcode, count in sorted(counts.items()))
        version = captures["server"][0]["ip_version"]
        print(f"PASS {result} independent IPv{version}/UDP4791/BTH/ICRC/payload checks; {summary}")


if __name__ == "__main__":
    main()
