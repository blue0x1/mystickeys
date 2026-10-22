"""Color-wave presets, live effects and saved settings."""

import os
import tempfile
import threading
import unittest
from unittest import mock

from helpers import fake_mysticlight, keyframes_of

from mystickeys import effects, live, notify


class Presets(unittest.TestCase):
    def test_every_preset_sends_a_valid_effect(self):
        for e in effects.EFFECTS:
            with self.subTest(e.key):
                kb = fake_mysticlight()
                effects.apply(kb, e, save=False)
                p = kb.dev.packets(2)[0]
                frames = keyframes_of(p)
                self.assertEqual(frames[0][0], 0)
                self.assertEqual(frames[-1][0], 100)
                self.assertLessEqual(len(frames), 10)
                self.assertEqual(int.from_bytes(p[3:5], "little"),
                                 round(e.speed * 100))

    def test_speed_and_brightness(self):
        kb = fake_mysticlight()
        effects.apply(kb, effects.get("neon"), brightness=50, speed=9, save=False)
        p = kb.dev.packets(2)[0]
        self.assertEqual(int.from_bytes(p[3:5], "little"), 900)
        self.assertEqual(keyframes_of(p)[0][1], (127, 127, 0))  # yellow at 50%

    def test_unknown(self):
        with self.assertRaises(ValueError):
            effects.get("cyberpunk")


class LiveMath(unittest.TestCase):
    def test_bar(self):
        white = lambda t: (200, 200, 200)
        self.assertEqual(live._bar(0.0, 4, white), [(0, 0, 0)] * 4)
        self.assertEqual(live._bar(1.0, 4, white), [(200, 200, 200)] * 4)
        half = live._bar(0.5, 4, white)
        self.assertEqual(half[:2], [(200, 200, 200)] * 2)
        self.assertEqual(half[2:], [(0, 0, 0)] * 2)

    def test_battery(self):
        with tempfile.TemporaryDirectory() as d:
            for name, value in (("capacity", "50"), ("status", "Discharging")):
                with open(os.path.join(d, name), "w") as fh:
                    fh.write(value)
            b = live.Battery.__new__(live.Battery)
            b.n, b.path, b._read_at = 4, d, -10
            b.level, b.charging = 1.0, False
            out = b.frame(0.0)
            self.assertEqual(b.level, 0.5)
            self.assertNotEqual(out[1], (0, 0, 0))
            self.assertEqual(out[3], (0, 0, 0))

    def test_typing_zones(self):
        t = live.Typing.__new__(live.Typing)
        t.n = 4
        zone = {name: t._zone_of(code) for name, code in
                (("Esc", 1), ("Q", 16), ("A", 30), ("H", 35), ("O", 24),
                 ("Enter", 28), ("Right", 106), ("KP1", 79))}
        self.assertEqual(zone["Esc"], 0)
        self.assertEqual(zone["Q"], 0)
        self.assertEqual(zone["A"], 0)
        self.assertEqual(zone["H"], 1)
        self.assertEqual(zone["O"], 2)
        self.assertEqual(zone["Enter"], 3)
        self.assertEqual(zone["Right"], 3)
        self.assertEqual(zone["KP1"], 3)

    def test_generated_effects_stay_in_range(self):
        for cls in (live.Fire, live.Thunder, live.LavaLamp):
            with self.subTest(cls.__name__):
                e = cls(4)
                for k in range(300):
                    frame = e.frame(k / 30)
                    self.assertEqual(len(frame), 4)
                    for c in frame:
                        self.assertTrue(all(0 <= v <= 255 for v in c), c)

    def test_run_sends_zones_and_restores(self):
        kb = fake_mysticlight()
        stop = threading.Event()

        class Two(live.LiveEffect):
            fps = 200

            def frame(self, now):
                stop.set()  # one frame is enough
                return [(10, 20, 30)] * 4

        live.run(kb, Two(4), stop)
        self.assertEqual(len(kb.dev.packets(1)), 4)          # one select per zone
        self.assertEqual(kb.dev.packets(0xA0), [])           # never saves flash
        self.assertEqual(kb.dev.sent[-1][:2], bytes([2, 0xB0]))  # restored


class Settings(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(os.environ, {"HOME": self.home.name},
                                   clear=False)
        self.env.start()
        os.environ.pop("SUDO_USER", None)

    def tearDown(self):
        self.env.stop()
        self.home.cleanup()

    def test_live_state_round_trip(self):
        live.save_state(effect="fire", brightness=40)
        live.save_state(brightness=60)
        self.assertEqual(live.load_state(), {"effect": "fire", "brightness": 60})

    def test_notify_settings_defaults_and_save(self):
        self.assertEqual(notify.load_settings()["color"], [255, 255, 255])
        notify.save_settings(color=[1, 2, 3], ignore=["Spotify"])
        s = notify.load_settings()
        self.assertEqual(s["color"], [1, 2, 3])
        self.assertEqual(s["ignore"], ["Spotify"])

    def test_old_alias(self):
        self.assertEqual(live.ALIASES["lightning"], "thunder")


if __name__ == "__main__":
    unittest.main()
