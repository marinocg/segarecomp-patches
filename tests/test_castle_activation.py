"""Castle of Illusion early object activation projects (SEG-143-T009 / W04): static, synthetic checks; no commercial data and no ROM.

The two projects are GAMEPLAY-CHANGING variants kept separate from the presentation-only package `castle-of-illusion`. They share its provider byte for byte; the 21:9 one adds a bounded
guest-asm retry. What is checked here is what the repository itself promises: the shared provider, layout, the declared edit sites, and the retry code's RAM extent.
With SEGARECOMP_CLI (and SEGARECOMP_SDK_DIR / SEGARECOMP_CC) the product's `mod check` is run on both projects too."""
import os, pathlib, re, subprocess, sys, unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import lint_layout

GAME = ROOT / "patches" / "genesis"
MAIN = GAME / "castle-of-illusion"
P16, P21 = GAME / "castle-of-illusion-activation-16x9", GAME / "castle-of-illusion-activation-21x9"
CLI = os.environ.get("SEGARECOMP_CLI")


def edits(p):
    return [ln.split() for ln in (p / "edits/activation.edits").read_text().splitlines() if ln.strip() and not ln.startswith("#")]


class Activation(unittest.TestCase):
    def test_provider_is_the_presentation_package_provider(self):
        for p in (P16, P21):
            self.assertEqual((p / "src/provider.c").read_bytes(), (MAIN / "src/provider.c").read_bytes(), p.name)

    def test_layout_lint_accepts_both_projects(self):
        errs = []
        lint_layout.lint(ROOT, errs)
        self.assertEqual(errs, [])

    def test_16x9_is_the_two_necessary_typed_edits_and_no_guest_code(self):
        e = {x[2]: (x[3], x[4]) for x in edits(P16)}
        self.assertEqual(e, {"0x0006d5cc": ("0x0180", "0x0200"), "0x0006d788": ("0x0280", "0x0300")})     # right lookahead and the initial-fill bound
        self.assertFalse((P16 / "src/retry.asm").exists())

    def test_21x9_window_edits_and_hooks(self):
        e = {x[2]: (x[3], x[4]) for x in edits(P21)}
        self.assertEqual(e["0x0006d5cc"], ("0x0180", "0x0280"))      # right column lookahead
        self.assertEqual(e["0x0006d5d2"], ("0x0071", "0x0100"))      # left column lookahead
        self.assertEqual(e["0x0006d788"], ("0x0280", "0x0480"))      # initial-fill bound (it runs the LEFT branch, so it moves with both lookaheads)
        self.assertEqual(e["0x00001b14"], ("0x0280", "0x0380"))      # right off-screen deletion limit
        self.assertEqual(e["0x0006d59d"], ("0x04", "0x06"))          # row-loader span
        # five six-byte hooks, each one an absolute jump into the injected block
        for site, old, new in (("0x0006d612", "48e725207600", "4ef900060c80"), ("0x0006d676", "51cefff6602a", "4ef900060cc0"), ("0x0006d536", "4df8fa806114", "4ef900060e00"),
                               ("0x0000963c", "4eb90006d6b4", "4eb900061000"), ("0x00001b1a", "4a446b000176", "4ef900061060")):
            self.assertEqual(e[site], (old, new))

    def test_retry_state_stays_inside_its_extent(self):
        asm = (P21 / "src/retry.asm").read_text()
        addrs = {int(a, 16) for a in re.findall(r"0x(ff[0-9a-f]{4})\b", asm) if a.startswith("fffc")}
        self.assertTrue(addrs and all(0xFFFC00 <= a <= 0xFFFC2F for a in addrs), sorted(hex(a) for a in addrs))
        self.assertNotRegex(asm, r"\b(trap|stop|reset|rte)\b")
        self.assertEqual(asm.count("jmp @"), 7)                       # every exit returns to an original continuation
        self.assertIn("addi.w #0x280,d2", asm); self.assertIn("subi.w #0x100,d2", asm)   # the retry window equals the lookaheads

    def test_asm_lives_under_src_and_is_declared(self):
        self.assertIn('kind = "guest-asm"', (P21 / "mod.toml").read_text())
        self.assertNotIn("guest-asm", (P16 / "mod.toml").read_text())

    @unittest.skipUnless(CLI, "set SEGARECOMP_CLI to run the product's `mod check`")
    def test_product_mod_check(self):
        for p in (P16, P21):
            r = subprocess.run([CLI, "mod", "check", str(p)], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()
