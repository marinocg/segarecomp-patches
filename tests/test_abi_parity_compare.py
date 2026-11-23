"""The pure helpers of tools/abi_parity_compare.py (SEG-152-T009/T010): pad-script construction and the comparison verdict logic. The tool itself needs a legally held image, a product checkout and a compiler and is
local-only; nothing here touches any of them (a fabricated trace stands in for a run)."""
import importlib.util, pathlib, sys, unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("abi_parity_compare", ROOT / "tools" / "abi_parity_compare.py")
tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tool)


def run(verdicts, bmp=b"p", ram=b"r", coverage=None):
    cov = coverage or {c: {"offered": 1, "accepted": 1, "presented": 1, "rejected": 0} for c in ("scenery", "hud")}
    trace = {f: {"f": f, "status": v[0], "side": v[1], "shift": v[2], "acc": v[3], "reason": v[4], "auth": v[5]} for f, v in verdicts.items()}
    return {"trace": trace, "events": [], "bmp": bmp, "ram": ram, "coverage": cov, "summary": {"faulted": False}}


class Helpers(unittest.TestCase):
    def test_level_pad_is_ordered_and_bounded(self):
        pad = tool.level_pad([400, 700], 900, 2000)
        polls = [int(line.split()[0]) for line in pad]
        self.assertEqual(polls[0], 0)
        self.assertEqual(polls, sorted(polls))
        self.assertIn("400 S", pad)
        self.assertTrue(all(line.split()[1] in {"-", "S", "R", "RA"} for line in pad))

    def test_merge_pad_inserts_hotkeys_in_order_and_ends(self):
        pad = tool.level_pad([400], 900, 3000) + ["3100 Q"]
        merged = tool.merge_pad(pad, ["1900 M", "1901 -"], 2700)
        polls = [int(line.split()[0]) for line in merged]
        self.assertEqual(polls, sorted(polls))
        self.assertEqual(merged[-1], "2700 Q")
        self.assertEqual(sum(1 for line in merged if line.endswith(" Q")), 1)
        self.assertIn("1900 M", merged)
        self.assertTrue(max(polls) == 2700 and all(p <= 2700 for p in polls))


class Verdict(unittest.TestCase):
    def comparer(self):
        c = object.__new__(tool.Cmp)
        c.failures, c.report = [], {}
        return c

    BASE = {f: (2, 238, 0, 3, 0, 1) for f in range(1, 40)}

    def test_equal_runs_differ_in_nothing(self):
        names, counts = self.comparer().compare("k", run(self.BASE), run(self.BASE))
        self.assertEqual(names, set())
        self.assertEqual(counts["frames_differing"], 0)

    def test_each_mechanism_is_named(self):
        c = self.comparer()
        for idx, name in ((3, "accepted-components"), (4, "reason"), (5, "authored"), (1, "side")):
            other = dict(self.BASE)
            other[7] = tuple(x + 1 if i == idx else x for i, x in enumerate(self.BASE[7]))
            names, counts = c.compare("k", run(self.BASE), run(other))
            self.assertIn(name, names)
            self.assertEqual(counts["frames_differing"], 1)

    def test_picture_ram_and_accounting_and_frame_identity(self):
        c = self.comparer()
        self.assertIn("picture", c.compare("k", run(self.BASE), run(self.BASE, bmp=b"q"))[0])
        self.assertIn("guest-ram", c.compare("k", run(self.BASE), run(self.BASE, ram=b"q"))[0])
        bad = {x: {"offered": 1, "accepted": 0, "presented": 0, "rejected": 1} for x in ("scenery", "hud")}
        self.assertIn("coverage-accounting", c.compare("k", run(self.BASE), run(self.BASE, coverage=bad))[0])
        short = {f: v for f, v in self.BASE.items() if f != 9}
        self.assertIn("frame-identity", c.compare("k", run(self.BASE), run(short))[0])

    def test_equal_requires_enough_frames_and_a_healthy_provider(self):
        c = self.comparer()
        tiny = {f: (2, 238, 0, 3, 0, 1) for f in range(1, 5)}
        self.assertFalse(c.equal("tiny", run(tiny), run(tiny)))   # fewer frames than the minimum: not evidence
        self.assertTrue(c.equal("ok", run(self.BASE), run(self.BASE)))
        sick = run(self.BASE)
        sick["summary"] = {"faulted": True}
        self.assertFalse(c.equal("sick", run(self.BASE), sick))


if __name__ == "__main__":
    unittest.main()
