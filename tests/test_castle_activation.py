"""Castle of Illusion early object activation projects (SEG-143-T009 / W04): static, synthetic checks; no commercial data and no ROM.

The two projects are GAMEPLAY-CHANGING variants kept separate from the presentation-only package `castle-of-illusion`. They share its provider byte for byte; the 21:9 one adds a bounded
guest-asm retry. What is checked here is what the repository itself promises: the shared provider, layout, the declared edit sites, and the retry code's RAM extent.
With SEGARECOMP_CLI (and SEGARECOMP_SDK_DIR / SEGARECOMP_CC) the product's `mod check` is run on both projects too."""
import os, pathlib, re, subprocess, sys, unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import lint_layout, gen_castle_retry

GAME = ROOT / "patches" / "genesis" / "castle-of-illusion"
MAIN = GAME / "widescreen-practice"
P16, P21, P32 = GAME / "activation-16x9", GAME / "activation-21x9", GAME / "activation-32x9"
CLI = os.environ.get("SEGARECOMP_CLI")


def edits(p):
    return [ln.split() for ln in (p / "edits/activation.edits").read_text().splitlines() if ln.strip() and not ln.startswith("#")]


class Activation(unittest.TestCase):
    def test_provider_is_the_presentation_package_provider(self):
        for p in (P16, P21, P32):
            self.assertEqual((p / "src/provider.c").read_bytes(), (MAIN / "src/provider.c").read_bytes(), p.name)

    def test_layout_lint_accepts_both_projects(self):
        errs = []
        lint_layout.lint(ROOT, errs)
        self.assertEqual(errs, [])

    def test_16x9_uses_the_common_guest_code_with_its_own_lookaheads(self):
        # The earlier two-edit 16:9 package lost original layout objects (measured: 13 of 254 identities over 26 stages on a deterministic route; 0 with the common code): the right deletion limit stayed at the original 0x280 while columns were
        # loaded at 0x200, so edge objects were deleted on creation and never requested again. 16:9 therefore shares the 21:9/32:9 code and edits, with right 0x200 / left 0x100.
        e = {x[2]: (x[3], x[4]) for x in edits(P16)}
        self.assertEqual(e["0x0006d5cc"], ("0x0180", "0x0200")); self.assertEqual(e["0x0006d5d2"], ("0x0071", "0x0100")); self.assertEqual(e["0x0006d788"], ("0x0280", "0x0400"))
        self.assertTrue((P16 / "src/retry.asm").exists()); self.assertIn('kind = "guest-asm"', (P16 / "mod.toml").read_text()); self.assertIn('aspect_max = "16:9"', (P16 / "mod.toml").read_text())

    def test_21x9_window_edits_and_hooks(self):
        e = {x[2]: (x[3], x[4]) for x in edits(P21)}
        self.assertEqual(e["0x0006d5cc"], ("0x0180", "0x0280"))      # right column lookahead
        self.assertEqual(e["0x0006d5d2"], ("0x0071", "0x0100"))      # left column lookahead
        self.assertEqual(e["0x0006d788"], ("0x0280", "0x0480"))      # initial-fill bound (it runs the LEFT branch, so it moves with both lookaheads)
        self.assertNotIn("0x00001b14", e)                             # the right deletion limit lives in the left_cull hook (one signed window test), not as a constant edit
        self.assertEqual(e["0x0006d59d"], ("0x04", "0x06"))          # row-loader span
        # five six-byte hooks, each one an absolute jump into the injected block
        self.assertEqual(e["0x00001b12"], ("0c4402806400017c", "4ef9000612604e71"))   # CMPI #$280,D4 / BCC.W (an UNSIGNED test that deleted every object left of the camera) -> jump to the signed window test
        for site, old, new in (("0x0006d612", "48e725207600", "4ef900060c80"), ("0x0006d676", "51cefff6602a", "4ef900060d40"), ("0x0006d536", "4df8fa806114", "4ef900060f00"),
                               ("0x0000963c", "4eb90006d6b4", "4eb900061200")):
            self.assertEqual(e[site], (old, new))

    def test_32x9_window_edits_hooks_and_deferral_constants(self):
        e = {x[2]: (x[3], x[4]) for x in edits(P32)}
        self.assertEqual(e["0x0006d5cc"], ("0x0180", "0x02c0")); self.assertEqual(e["0x0006d5d2"], ("0x0071", "0x0180")); self.assertEqual(e["0x0006d788"], ("0x0280", "0x04c0")); self.assertEqual(e["0x0006d59d"], ("0x04", "0x06"))
        self.assertEqual(e["0x0006d676"], ("51cefff6602a", "4ef900060d40"))          # the fail hook moved to make room for the deferral in the entry hook
        asm = (P32 / "src/retry.asm").read_text()
        self.assertIn("lea 0x42c0(a1),a1", asm); self.assertIn("lea 0x3e80(a1),a1", asm)          # the retry window equals the lookaheads
        self.assertIn('aspect_max = "32:9"', (P32 / "mod.toml").read_text())
        for blk in re.findall(r"^org usa-europe (0x[0-9a-f]+)", asm, flags=re.M): self.assertTrue(0x60c80 <= int(blk, 16) < 0x61600, blk)   # inside the blank area the project frees

    def test_retry_state_and_diagnostics_stay_inside_their_extent(self):
        for p in (P16, P21, P32):
            asm = (p / "src/retry.asm").read_text()
            addrs = {int(a, 16) for a in re.findall(r"0x(ff[0-9a-f]{4})\b", asm) if a.startswith("fffc")}
            self.assertTrue(addrs and all(0xFFFC00 <= a <= 0xFFFCB5 for a in addrs), (p.name, sorted(hex(a) for a in addrs)))
            self.assertNotRegex(re.sub(r"(?m)^;.*$", "", asm), r"\b(trap|stop|reset|rte)\b")
            self.assertEqual(asm.count("jmp @"), 7, "every exit returns to an original continuation")
            self.assertIn("cmpi.w #20,d3", asm); self.assertIn("cmpi.w #12,d3", asm)       # deferral threshold; speculative cap (16 slots, 4 reserved for genuine failures)
        self.assertIn("lea 0x4280(a1),a1", (P21 / "src/retry.asm").read_text()); self.assertIn("lea 0x3f00(a1),a1", (P21 / "src/retry.asm").read_text())

    def test_the_retry_asm_of_both_variants_is_generated_from_one_template(self):
        import gen_castle_retry
        for name, p in (("16x9", P16), ("21x9", P21), ("32x9", P32)): self.assertEqual((p / "src/retry.asm").read_text(), gen_castle_retry.generate(name), name + ": run scripts/gen_castle_retry.py")

    def test_asm_lives_under_src_and_is_declared(self):
        [self.assertIn('kind = "guest-asm"', (p / "mod.toml").read_text()) for p in (P16, P21, P32)]

    @unittest.skipUnless(CLI, "set SEGARECOMP_CLI to run the product's `mod check`")
    def test_product_mod_check(self):
        for p in (P16, P21, P32):
            r = subprocess.run([CLI, "mod", "check", str(p)], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()
