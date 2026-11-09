"""Runs the ROM-free synthetic fixture. Needs the product's pinned segapatch.py: SEGAPATCH=<path> (CI downloads it)."""
import os, pathlib, subprocess, sys, unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import synthetic_fixture


@unittest.skipUnless(os.environ.get("SEGAPATCH"), "SEGAPATCH not set (CI downloads the pinned segapatch.py)")
class Synthetic(unittest.TestCase):
    def test_matches_expectations(self):
        self.assertEqual(synthetic_fixture.main(["--segapatch", os.environ["SEGAPATCH"], "--provider", str(ROOT / "examples/synthetic/provider.c")]), 0)


class Fabricated(unittest.TestCase):
    def test_deterministic_and_distinct(self):
        a, b = synthetic_fixture.fabricate(), synthetic_fixture.fabricate()
        self.assertEqual(a, b); self.assertNotEqual(a[0], a[1]); self.assertEqual(len(a[0]), 8192)

    def test_tampered_expectation_fails(self):
        if not os.environ.get("SEGAPATCH"): self.skipTest("SEGAPATCH not set")
        got = synthetic_fixture.build(pathlib.Path(os.environ["SEGAPATCH"]), None)
        self.assertEqual(got["wrong_image_refused"], True)


if __name__ == "__main__":
    unittest.main()
