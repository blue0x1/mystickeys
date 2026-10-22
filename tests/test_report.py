"""The hardware report: scripted answers against a fake keyboard."""

import unittest

from helpers import fake_mysticlight

from mystickeys import report


def scripted(*answers):
    it = iter(answers)
    return lambda prompt: next(it)


class Report(unittest.TestCase):
    def test_all_ok(self):
        kb = fake_mysticlight()
        # red, green, blue, orange, zones 1-4, breathing, wave
        results = dict(report.run_tests(
            kb, scripted("r", "g", "b", "y", "1", "2", "3", "4", "y", "l")))
        self.assertEqual(set(results.values()), {"ok"})
        self.assertEqual(kb.dev.packets(0xA0), [])  # never saved to the keyboard

    def test_problems_are_reported(self):
        kb = fake_mysticlight()
        results = dict(report.run_tests(
            kb, scripted("b", "g", "r", "g", "a", "2", "x", "s", "4", "n", "r")))
        self.assertEqual(results["Whole keyboard red"], "saw blue")
        self.assertEqual(results["Orange (255,128,0)"], "looks yellow/green")
        self.assertEqual(results["Zone 1 alone"], "whole keyboard lit")
        self.assertEqual(results["Zone 3 alone"], "skipped")  # 'x' re-asked, then s
        self.assertEqual(results["Breathing"], "no")
        self.assertEqual(results["Wave"], "moves right-to-left (reversed)")

    def test_build_restores_keyboard(self):
        kb = fake_mysticlight()
        text = report.build(ask=scripted("r", "g", "b", "y", "1", "2", "3", "4",
                                         "y", "l"),
                            open_kb=lambda: kb)
        self.assertIn("### Visual tests", text)
        self.assertEqual(kb.dev.sent[-1][:2], bytes([2, 0xB0]))  # restored

    def test_stopping_early(self):
        kb = fake_mysticlight()

        def stop(_prompt):
            raise KeyboardInterrupt
        text = report.build(ask=stop, open_kb=lambda: kb)
        self.assertIn("stopped early", text)
        self.assertEqual(kb.dev.sent[-1][:2], bytes([2, 0xB0]))


if __name__ == "__main__":
    unittest.main()
