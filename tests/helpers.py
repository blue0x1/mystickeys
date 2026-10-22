"""Shared test helpers: a fake keyboard device that records packets."""

import contextlib
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mystickeys.backends import MysticLightBackend  # noqa: E402

# Report descriptor of a real MSI Katana 15 keyboard (MS-1565, 1462:1601)
MS1565_DESCRIPTOR = bytes.fromhex(
    "06ff000901a10185010901150025017508953fb18285010901918285020902150025"
    "017508953fb18285030903150025017508953f9182850309038182850409041500250175"
    "089501b18285040904918285050905150025017501818209057501b182750781838505"
    "7507b18385060906150025017501818209067501b1827507818385067507b183850709"
    "07150026ff007508818285070907b182150026ff007508953f85080908b10285080908"
    "9102850809088102c0")


class FakeDevice:
    """Stands in for Hidraw: records every feature report sent."""

    def __init__(self):
        self.sent = []
        self.settle = 0.0
        self.fd = 3

    def open(self):
        pass

    def close(self):
        pass

    def send_feature(self, data):
        assert len(data) == 64, "MysticLight packets are 64 bytes"
        self.sent.append(bytes(data))

    def get_feature(self, report_id, length):
        return bytes(length)

    @contextlib.contextmanager
    def locked(self):
        yield 0.0

    def packets(self, packet_id):
        return [p for p in self.sent if p[1] == packet_id]


def fake_mysticlight():
    kb = MysticLightBackend("/dev/null", 0x1462, 0x1601)
    kb.dev = FakeDevice()
    return kb


def keyframes_of(packet):
    """Decode (time, (r, g, b)) keyframes from an effect packet."""
    frames = []
    for off in range(10, 64, 4):
        t, r, g, b = packet[off:off + 4]
        if off > 10 and (t, r, g, b) == (0, 0, 0, 0):
            break
        frames.append((t, (r, g, b)))
    return frames
