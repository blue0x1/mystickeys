"""Shared Linux hidraw access layer (pure stdlib, no hidapi).

Opens an MSI keyboard-lighting controller by USB VID/PID via sysfs and exposes
HID feature-report read/write through ioctl. Used by all backends.
"""

from __future__ import annotations

import contextlib
import fcntl
import glob
import os
import time
from typing import Dict, Iterable, List, Optional, Set, Tuple

# -- ioctl _IOC plumbing ----------------------------------------------------
_IOC_NRSHIFT = 0
_IOC_TYPESHIFT = 8
_IOC_SIZESHIFT = 16
_IOC_DIRSHIFT = 30
_IOC_WRITE = 1
_IOC_READ = 2


def _IOC(direction: int, type_: str, nr: int, size: int) -> int:
    return ((direction << _IOC_DIRSHIFT) | (ord(type_) << _IOC_TYPESHIFT)
            | (nr << _IOC_NRSHIFT) | (size << _IOC_SIZESHIFT))


def _HIDIOCSFEATURE(size: int) -> int:
    return _IOC(_IOC_WRITE | _IOC_READ, "H", 0x06, size)


def _HIDIOCGFEATURE(size: int) -> int:
    return _IOC(_IOC_WRITE | _IOC_READ, "H", 0x07, size)


class KeyboardError(Exception):
    """Base error for everything the user should see as a message."""


class HidrawError(KeyboardError):
    """The device could not be opened or rejected a request."""


def enumerate_devices() -> List[Tuple[str, int, int]]:
    """Return [(node, vid, pid)] for every hidraw device on the system."""
    out: List[Tuple[str, int, int]] = []
    for uevent in glob.glob("/sys/class/hidraw/hidraw*/device/uevent"):
        try:
            text = open(uevent).read()
        except OSError:
            continue
        hid_id = next((l.split("=", 1)[1] for l in text.splitlines()
                       if l.startswith("HID_ID=")), "")
        parts = hid_id.split(":")
        if len(parts) != 3:
            continue
        try:
            vid, pid = int(parts[1], 16), int(parts[2], 16)
        except ValueError:
            continue
        node = os.path.basename(os.path.dirname(os.path.dirname(uevent)))
        out.append(("/dev/" + node, vid, pid))
    return out


def device_name(node: str) -> str:
    """Return the HID_NAME of a /dev/hidrawN node ('' if unknown)."""
    uevent = f"/sys/class/hidraw/{os.path.basename(node)}/device/uevent"
    try:
        for line in open(uevent).read().splitlines():
            if line.startswith("HID_NAME="):
                return line.split("=", 1)[1].strip()
    except OSError:
        pass
    return ""


class Descriptor:
    """What a HID report descriptor declares, as far as backends need to know.

    ``reports[(kind, report_id)]`` is the report length in bytes *including*
    the report-id byte, where kind is "input", "output" or "feature".
    ``usage_pages`` holds every usage page that appears in the descriptor.
    """

    def __init__(self) -> None:
        self.reports: Dict[Tuple[str, int], int] = {}
        self.usage_pages: Set[int] = set()

    def feature_size(self, report_id: int) -> int:
        return self.reports.get(("feature", report_id), 0)

    @property
    def vendor_defined(self) -> bool:
        # MSI firmware writes the vendor page byte-swapped (0x00FF), so accept it
        return any(p >= 0xFF00 or p == 0x00FF for p in self.usage_pages)


def parse_descriptor(raw: bytes) -> Descriptor:
    """Parse a raw HID report descriptor (only the parts we need)."""
    desc = Descriptor()
    bits: Dict[Tuple[str, int], int] = {}
    g = {"page": 0, "size": 0, "count": 0, "id": 0}
    stack: List[Dict[str, int]] = []
    main_kinds = {0x8: "input", 0x9: "output", 0xB: "feature"}
    i = 0
    while i < len(raw):
        prefix = raw[i]
        if prefix == 0xFE:  # long item: skip it
            if i + 1 >= len(raw):
                break
            i += 3 + raw[i + 1]
            continue
        size = (0, 1, 2, 4)[prefix & 0x3]
        typ = (prefix >> 2) & 0x3
        tag = prefix >> 4
        value = int.from_bytes(raw[i + 1:i + 1 + size], "little")
        i += 1 + size
        if typ == 1:  # global
            if tag == 0x0:
                g["page"] = value
                desc.usage_pages.add(value)
            elif tag == 0x7:
                g["size"] = value
            elif tag == 0x8:
                g["id"] = value
            elif tag == 0x9:
                g["count"] = value
            elif tag == 0xA:
                stack.append(dict(g))
            elif tag == 0xB and stack:
                g = stack.pop()
        elif typ == 0 and tag in main_kinds:
            key = (main_kinds[tag], g["id"])
            bits[key] = bits.get(key, 0) + g["size"] * g["count"]
        elif typ == 2 and tag == 0x0 and size == 4:
            # 32-bit usage carries its own page in the high word
            desc.usage_pages.add(value >> 16)
    for (kind, rid), nbits in bits.items():
        desc.reports[(kind, rid)] = (nbits + 7) // 8 + (1 if rid else 0)
    return desc


def read_descriptor(node: str) -> Optional[Descriptor]:
    """Read and parse the report descriptor of /dev/hidrawN (no root needed)."""
    path = f"/sys/class/hidraw/{os.path.basename(node)}/device/report_descriptor"
    try:
        with open(path, "rb") as fh:
            return parse_descriptor(fh.read())
    except OSError:
        return None


def find_node(ids: Iterable[Tuple[int, int]]) -> Optional[Tuple[str, int, int]]:
    """Return the first (node, vid, pid) matching any (vid, pid) in `ids`."""
    wanted = {(int(v), int(p)) for v, p in ids}
    for node, vid, pid in enumerate_devices():
        if (vid, pid) in wanted:
            return (node, vid, pid)
    return None


class Hidraw:
    """Thin wrapper around a /dev/hidraw node for HID feature reports."""

    def __init__(self, path: str, settle: float = 0.01):
        self.path = path
        self.settle = settle
        self.fd: Optional[int] = None

    def __enter__(self) -> "Hidraw":
        self.open()
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def open(self) -> None:
        try:
            self.fd = os.open(self.path, os.O_RDWR)
        except PermissionError as e:
            raise HidrawError(
                f"Permission denied opening {self.path}. Run with sudo or "
                f"install the udev rule (sudo ./install.sh)."
            ) from e
        except OSError as e:
            raise HidrawError(f"Cannot open {self.path}: {e}") from e

    def close(self) -> None:
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None

    @contextlib.contextmanager
    def locked(self):
        """Hold the device exclusively across processes (e.g. a notification
        flash and a live effect). Yields how long we had to wait, in seconds."""
        if self.fd is None:
            raise HidrawError("device not open")
        t = time.monotonic()
        fcntl.flock(self.fd, fcntl.LOCK_EX)
        try:
            yield time.monotonic() - t
        finally:
            fcntl.flock(self.fd, fcntl.LOCK_UN)

    def send_feature(self, data: bytes) -> None:
        """Send a feature report. data[0] must be the HID report id."""
        if self.fd is None:
            raise HidrawError("device not open")
        buf = bytes(data)
        try:
            fcntl.ioctl(self.fd, _HIDIOCSFEATURE(len(buf)), buf)
        except OSError as e:
            raise HidrawError(f"{self.path} rejected the command: {e}") from e
        if self.settle:
            time.sleep(self.settle)

    def get_feature(self, report_id: int, length: int) -> bytes:
        if self.fd is None:
            raise HidrawError("device not open")
        buf = bytearray([report_id]) + bytearray(length - 1)
        try:
            fcntl.ioctl(self.fd, _HIDIOCGFEATURE(len(buf)), buf)
        except OSError:
            pass
        return bytes(buf)

    def write(self, data: bytes) -> None:
        """Send an output report (data[0] = report id, 0 if unnumbered)."""
        if self.fd is None:
            raise HidrawError("device not open")
        try:
            os.write(self.fd, bytes(data))
        except OSError as e:
            raise HidrawError(f"{self.path} rejected the write: {e}") from e
        if self.settle:
            time.sleep(self.settle)
