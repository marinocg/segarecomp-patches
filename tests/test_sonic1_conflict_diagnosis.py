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

    def port_record(self, m, tuples=None):
        """What the instrumented port logs for the conflicts of model `m` (fabricated here from the model itself)."""
        some = sorted(m["tuples"])[:6] if tuples is None else tuples
        return {"S": {"n": m["cells"], "rows": len(m["rows"]), "h": m["hsum"], "x": m["hxor"]}, "R": [{"r": str(r)} for r in sorted(m["rows"])], "T": some}

    def test_exact_compare_accepts_identical_conflict_data(self):
        m = diag.model_conflicts(synthetic_ram(lambda l: 0 if l < 5 else 8), 238)
        self.assertGreater(len(m["tuples"]), 6)
        self.assertEqual(diag.exact_compare(self.port_record(m), m), [])
        self.assertEqual(diag.exact_compare(None, diag.model_conflicts(synthetic_ram(lambda l: 0), 238)), [])

    def test_exact_compare_rejects_every_kind_of_disagreement(self):
        m = diag.model_conflicts(synthetic_ram(lambda l: 0 if l < 5 else 8), 238)
        good = self.port_record(m)
        bad_word = dict(good, T=[(r, c, wa, wb ^ 1) for r, c, wa, wb in good["T"]])                       # one printed word differs
        self.assertTrue(any("printed tuples" in p for p in diag.exact_compare(bad_word, m)))
        bad_digest = dict(good, S=dict(good["S"], h="0" * 16))                                              # one tuple of the full set differs
        self.assertTrue(any("digest" in p for p in diag.exact_compare(bad_digest, m)))
        bad_count = dict(good, S=dict(good["S"], n=good["S"]["n"] + 1))
        self.assertTrue(any("cells" in p for p in diag.exact_compare(bad_count, m)))
        bad_rows = dict(good, R=[{"r": str(int(r["r"]) + 1)} for r in good["R"]])
        self.assertTrue(any("plane row identities" in p for p in diag.exact_compare(bad_rows, m)))
        self.assertTrue(any("logged none" in p for p in diag.exact_compare(None, m)))                       # the model finds conflicts the port did not log
        self.assertTrue(any("no explicit tuples" in p for p in diag.exact_compare(dict(good, T=[]), m)))

    def test_row_checks_are_unconditional(self):
        m = diag.model_conflicts(synthetic_ram(lambda l: 0 if l < 5 else 8), 238)
        good = self.port_record(m)
        self.assertEqual(diag.exact_compare(good, m), [])
        self.assertTrue(any("incomplete or malformed" in p for p in diag.exact_compare(dict(good, R=[]), m)))                       # no row lines at all
        self.assertTrue(any("incomplete or malformed" in p for p in diag.exact_compare(dict(good, R=good["R"] + good["R"]), m)))    # duplicated row lines
        self.assertTrue(any("row count" in p for p in diag.exact_compare(dict(good, S=dict(good["S"], rows=good["S"]["rows"] + 1)), m)))
        self.assertTrue(any("identities" in p for p in diag.exact_compare(dict(good, R=[{"r": "999"}]), m)))

    def test_control_captures_get_every_lag_including_the_previous_onset(self):
        quiet = synthetic_ram(lambda l: 0)
        samples = diag.model_samples([quiet, quiet, quiet], 238, None)
        self.assertEqual([x["ram_lag"] for x in samples], [0, 1, 2])
        entry = {"name": "control", "aspect": "wide", "requested_guest_frame": 5, "same_frame_identity": True, "independent_model": samples}
        self.assertEqual(diag.manifest_failures([entry]), [])                                          # a valid control capture passes
        flip = synthetic_ram(lambda l: 0 if l < 5 else 8)
        bad = dict(entry, independent_model=diag.model_samples([quiet, flip, quiet], 238, None))      # a conflict at the previous onset that the port did not log
        self.assertTrue(diag.manifest_failures([bad]))

    def test_digest_mirrors_the_port_and_ignores_order(self):
        self.assertEqual(diag.fnv4(1, 2, 3, 4), diag.fnv4(1, 2, 3, 4))
        self.assertNotEqual(diag.fnv4(1, 2, 3, 4), diag.fnv4(1, 2, 4, 3))
        self.assertEqual(diag.fnv4(-1, 0, 0, 0), diag.fnv4(0xFFFFFFFF, 0, 0, 0))                              # negative values as 32-bit two's complement, as in C
        src = diag.probe_edit((ROOT / "patches/genesis/sonic-1/native-widescreen-abi2/src/provider.c").read_text())
        for needle in ("fnv4(rho, c, (int)*o, word)", "g_hsum += hh; g_hxor ^= hh", "1469598103934665603ULL", "1099511628211ULL"):
            self.assertIn(needle, src)

    def test_a_model_disagreement_or_wrong_identity_is_a_hard_failure(self):
        ok = {"name": "a", "aspect": "wide", "requested_guest_frame": 10, "same_frame_identity": True, "independent_model": [{"ram_lag": 0, "equals_instrumented_log": False}, {"ram_lag": 1, "equals_instrumented_log": True}]}
        self.assertEqual(diag.manifest_failures([ok]), [])
        disagree = dict(ok, independent_model=[{"ram_lag": 1, "equals_instrumented_log": False, "disagreements": ["digest"]}])
        self.assertTrue(diag.manifest_failures([disagree]))
        self.assertTrue(diag.manifest_failures([dict(ok, independent_model=[{"ram_lag": 0, "equals_instrumented_log": True}])]))   # no lag-1 check at all
        self.assertTrue(diag.manifest_failures([dict(ok, same_frame_identity=False)]))
        self.assertEqual(diag.manifest_failures([dict(ok, independent_model=None)]), [])                                         # exact 4:3: nothing to model

    def test_log_parsing_and_helpers(self):
        lines = [{"line": "T f=10 t=25:-3:1:2,25:-2:3:4"}, {"line": "S f=10 side=238 plane=1 n=5 rows=1 rmin=24 h=00ff x=0f"}, {"line": "R f=10 p=1 r=25 A=1-2 B=3-4 kA=0 kB=64 hA=1 hB=2 c=-3..4 n=5 xA=0..8 xB=1..9 LL=2 RR=3 LR=0"}, {"line": "unrelated"}]
        p = diag.parse_log(lines)
        self.assertEqual(p[10]["S"]["n"], 5)
        self.assertEqual(p[10]["R"][0]["kB"], "64")
        self.assertEqual(p[10]["T"], [(25, -3, 1, 2), (25, -2, 3, 4)])
        self.assertEqual((p[10]["S"]["h"], p[10]["S"]["x"]), ("00ff", "0f"))
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
