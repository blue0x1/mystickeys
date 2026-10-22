"""Colors, HID descriptor parsing, detection and the bytes sent to the keyboard."""

import unittest
from unittest import mock

from helpers import MYSTICLIGHT_DESCRIPTOR, fake_mysticlight, keyframes_of

from mystickeys import backends
from mystickeys.backends import KeyboardError, MysticLightBackend
from mystickeys.colors import parse_color, scale
from mystickeys.hidraw import parse_descriptor


class Colors(unittest.TestCase):
    def test_formats(self):
        self.assertEqual(parse_color("red"), (255, 0, 0))
        self.assertEqual(parse_color("#00ff88"), (0, 255, 136))
        self.assertEqual(parse_color("00FF88"), (0, 255, 136))
        self.assertEqual(parse_color("#f80"), (255, 136, 0))
        self.assertEqual(parse_color("255, 136, 0"), (255, 136, 0))

    def test_bad_input(self):
        for bad in ("nope", "#12345", "1,2", "300,0,0", "#gggggg"):
            with self.assertRaises(ValueError, msg=bad):
                parse_color(bad)

    def test_scale(self):
        self.assertEqual(scale((200, 100, 50), 50), (100, 50, 25))
        self.assertEqual(scale((200, 100, 50), 150), (200, 100, 50))  # capped
        self.assertEqual(scale((200, 100, 50), -5), (0, 0, 0))


class Descriptor(unittest.TestCase):
    def test_mysticlight_keyboard(self):
        d = parse_descriptor(MYSTICLIGHT_DESCRIPTOR)
        self.assertEqual(d.feature_size(1), 64)
        self.assertEqual(d.feature_size(2), 64)
        self.assertTrue(d.vendor_defined)  # MSI writes the page byte-swapped

    def test_mouse_is_not_vendor(self):
        mouse = bytes.fromhex("05010902a10185010901a1000509190129031500250195"
                              "0375018102c0c0")
        d = parse_descriptor(mouse)
        self.assertFalse(d.vendor_defined)
        self.assertEqual(d.feature_size(2), 0)


class Detection(unittest.TestCase):
    def detect(self, devices, descriptors):
        with mock.patch.object(backends, "enumerate_devices", return_value=devices), \
             mock.patch.object(backends, "read_descriptor",
                               side_effect=lambda n: descriptors.get(n)), \
             mock.patch.object(backends, "device_name", return_value=""):
            return backends.detect_info()

    def test_known_id(self):
        hit = self.detect([("/dev/hidraw1", 0x1462, 0x1601)], {})
        self.assertIs(hit[0], MysticLightBackend)
        self.assertEqual(hit[4], "known USB ID")

    def test_unlisted_laptop_matched_by_descriptor(self):
        desc = parse_descriptor(MYSTICLIGHT_DESCRIPTOR)
        hit = self.detect([("/dev/hidraw5", 0x1462, 0x1599)], {"/dev/hidraw5": desc})
        self.assertIs(hit[0], MysticLightBackend)
        self.assertEqual(hit[4], "matched by HID descriptor")

    def test_motherboard_never_matched(self):
        desc = parse_descriptor(MYSTICLIGHT_DESCRIPTOR)
        hit = self.detect([("/dev/hidraw5", 0x1462, 0x7C37)], {"/dev/hidraw5": desc})
        self.assertIsNone(hit)

    def test_other_vendor_never_matched(self):
        desc = parse_descriptor(MYSTICLIGHT_DESCRIPTOR)
        hit = self.detect([("/dev/hidraw5", 0x1234, 0x1601)], {"/dev/hidraw5": desc})
        self.assertIsNone(hit)


class Packets(unittest.TestCase):
    def test_steady_color_bytes(self):
        kb = fake_mysticlight()
        kb.set_color((255, 0, 0), zone="1", save=True)
        select, effect, save = kb.dev.sent
        self.assertEqual(select[:3], bytes([2, 1, 0b0001]))
        self.assertEqual(effect[:10], bytes([2, 2, 1, 0x2C, 0x01, 0, 0, 15, 1, 1]))
        self.assertEqual(keyframes_of(effect), [(0, (255, 0, 0)), (100, (255, 0, 0))])
        self.assertEqual(save[:2], bytes([2, 0xA0]))

    def test_no_save(self):
        kb = fake_mysticlight()
        kb.set_color((1, 2, 3), save=False)
        self.assertEqual(kb.dev.packets(0xA0), [])

    def test_wave_direction_and_speed(self):
        kb = fake_mysticlight()
        kb.set_wave([(255, 0, 0), (0, 0, 255)], speed=2.5, direction=0, save=False)
        p = kb.dev.packets(2)[0]
        self.assertEqual(p[2], 4)                             # wave mode
        self.assertEqual(int.from_bytes(p[3:5], "little"), 250)
        self.assertEqual(p[9], 0)                             # right to left

    def test_restore_reloads_flash(self):
        kb = fake_mysticlight()
        kb.restore()
        self.assertEqual(kb.dev.sent[0][:2], bytes([2, 0xB0]))

    def test_bad_zone(self):
        with self.assertRaises(KeyboardError):
            fake_mysticlight().set_color((1, 1, 1), zone="9")


class Keyframes(unittest.TestCase):
    K = staticmethod(MysticLightBackend._keyframes)

    def test_loops_back_to_first_color(self):
        frames = self.K([(1, 1, 1), (2, 2, 2), (3, 3, 3)])
        self.assertEqual([t for t, _ in frames], [0, 33, 67, 100])
        self.assertEqual(frames[-1][1], frames[0][1])

    def test_hold(self):
        red, blue = (255, 0, 0), (0, 0, 255)
        self.assertEqual(self.K([red, blue], hold=0.8),
                         [(0, red), (40, red), (50, blue), (90, blue), (100, red)])

    def test_limits(self):
        self.assertEqual(len(self.K([(1, 1, 1)] * 9)), 10)  # MCU maximum
        with self.assertRaises(KeyboardError):
            self.K([(1, 1, 1)] * 10)
        with self.assertRaises(KeyboardError):
            self.K([(1, 1, 1)] * 5, hold=0.5)  # holds use two frames per color

    def test_speed_range(self):
        kb = fake_mysticlight()
        for bad in (0, 700):
            with self.assertRaises(KeyboardError):
                kb.set_breath([(1, 1, 1)], speed=bad)


if __name__ == "__main__":
    unittest.main()
