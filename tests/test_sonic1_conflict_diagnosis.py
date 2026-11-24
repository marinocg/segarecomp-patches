"""The independent RAM model of tools/sonic1_conflict_diagnosis.py on a SYNTHETIC work RAM (arbitrary deterministic bytes in the layout shape the tool reads; no game data): two lines of one plane-cell row whose
nearest-alias world origins differ by 512 px ask one plane cell with different words; equal origins do not conflict; only off-picture pixels are asked."""
import importlib.util, pathlib, sys, unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
spec = importlib.util.spec_from_file_location("sonic1_conflict_diagnosis", ROOT / "tools" / "sonic1_conflict_diagnosis.py")
diag = importlib.util.module_from_spec(spec)
spec.loader.exec_module(diag)


def synthetic_ram(ram_b_by_line, bgx=2300):
    r = bytearray(65536)

    def w16(a, v):
        r[a] = (v >> 8) & 0xFF
        r[a + 1] = v & 0xFF
    for i in range(64):
        r[0xA400 + 0x40 + i] = 1 + (i % 4)                         # background layout row 0: chunk 1..4
    for chunk in range(1, 5):
        for j in range(256):
            w16((chunk - 1) * 0x200 + j * 2, (chunk * 16 + j) & 0x3FF)   # chunk table: block numbers
    for block in range(0x400):
        for j in range(4):
            w16(0xB000 + block * 8 + j * 2, (block * 4 + j + 1) & 0x7FF)   # block table: name words
    w16(0xF70C, 0)        # background y camera
    w16(0xF708, bgx)      # background camera x (the alias reference of the upper region)
    w16(0xF710, bgx)      # second background camera
    w16(0xF7F0, 0xFFFF)   # split: every line uses the first camera
    for line in range(224):
        v = ram_b_by_line(line)
        w16(0xCC00 + line * 4 + 2, v & 0xFFFF)
    return bytes(r)


class Model(unittest.TestCase):
    def test_alias_flip_between_adjacent_lines_conflicts(self):
        ram = synthetic_ram(lambda l: 0 if l < 5 else 8)           # lines 0-4 scroll 0, lines 5.. scroll 8: same plane-cell row 0, nearest aliases 2048 vs 2552
        m = diag.model_conflicts(ram, 238)
        self.assertTrue(m["origin_ok"])
        self.assertEqual(sorted(m["rows"]), [0])
        row = m["rows"][0]
        self.assertGreater(m["cells"], 0)
        self.assertEqual(abs(row["ka"] - row["kb"]), 64)             # 64 plane cells = 512 pixels
        self.assertNotEqual(row["example"]["word_a"], row["example"]["word_b"])
        self.assertEqual(abs(row["example"]["world_cell_a"] - row["example"]["world_cell_b"]), 64)

    def test_equal_origins_do_not_conflict(self):
        self.assertEqual(diag.model_conflicts(synthetic_ram(lambda l: 0), 238)["cells"], 0)
        self.assertEqual(diag.model_conflicts(synthetic_ram(lambda l: 16 * (l // 8)), 238)["cells"], 0)   # one origin per cell row: no pair shares a row

    def test_only_off_picture_pixels_are_asked(self):
        # at side 0 the host asks nothing outside the picture, so even the flipping lines cannot conflict
        self.assertEqual(diag.model_conflicts(synthetic_ram(lambda l: 0 if l < 5 else 8), 0)["cells"], 0)

    def test_log_parsing_and_helpers(self):
        lines = [{"line": "S f=10 side=238 plane=1 n=5 rows=1 rmin=24"}, {"line": "R f=10 p=1 r=25 A=1-2 B=3-4 kA=0 kB=64 hA=1 hB=2 c=-3..4 n=5 xA=0..8 xB=1..9 LL=2 RR=3 LR=0"}, {"line": "unrelated"}]
        p = diag.parse_log(lines)
        self.assertEqual(p[10]["S"]["n"], 5)
        self.assertEqual(p[10]["R"][0]["kB"], "64")
        self.assertEqual(diag.s10(0x3A0), -96)
        self.assertEqual(diag.unwrap(300, 2000, 512), 1836)

    def test_the_instrumented_copy_is_a_pure_addition(self):
        src = (ROOT / "patches/genesis/sonic-1/native-widescreen-abi2/src/provider.c").read_text()
        probe = diag.probe_edit(src)
        self.assertIn("g_host->log", probe)
        for needle in ("if (g_nconf != 0U) return 2;", "world_cell(ram, plane, c + k_[l], wrow)"):
            self.assertIn(needle, probe)
        self.assertEqual(diag.probe_manifest('[capabilities]\nrequired = ["frame.vdp"]\n').count("host.log"), 1)


if __name__ == "__main__":
    unittest.main()
