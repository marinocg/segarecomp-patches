"""The input-recorder package (patches/genesis/castle-of-illusion-input-recorder) and its tools (tools/record_to_pad_script.py, tools/summarize_capture.py). The provider runs on the same mock ABI 2 host as the Castle provider tests (declared ranges, pad, log
recorded); the tools are pure Python on fabricated logs. No ROM and no game data. Provider tests need SEGARECOMP_SDK_DIR (CI requires them)."""
import json, os, pathlib, subprocess, sys, tempfile, unittest
try: import tomllib
except ImportError: tomllib = None

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import test_castle_provider as P
ROOT = P.ROOT
sys.path.insert(0, str(ROOT / "tools"))
import record_to_pad_script as R, summarize_capture as S
PROJECT = ROOT / "patches/genesis/castle-of-illusion-input-recorder"
SDK, CC = P.SDK, P.CC
if os.environ.get("SEGARECOMP_REQUIRE_EXEC") == "1" and (not SDK or tomllib is None):
    raise RuntimeError("SEGARECOMP_REQUIRE_EXEC=1 but SEGARECOMP_SDK_DIR is not set or Python lacks tomllib: the recorder tests would be skipped")


@unittest.skipUnless(SDK, "set SEGARECOMP_SDK_DIR to the product's platforms directory")
class Recorder(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = pathlib.Path(tempfile.mkdtemp()); (cls.tmp / "harness.c").write_text(P.HARNESS)
        inc = ["-I", str(pathlib.Path(SDK) / "genesis/sdk"), "-I", str(pathlib.Path(SDK) / "sdk")]
        r = subprocess.run([CC, "-std=c11", "-Wall", "-Wextra", "-pedantic", "-Werror", "-DSEGA_MOD_TARGET_PLATFORM=1", "-DSEGA_MOD_TARGET_ABI_MAJOR=2U", *inc, "-c", "-o", str(cls.tmp / "p.o"), str(PROJECT / "src/provider.c")], capture_output=True, text=True)
        if r.returncode != 0: raise AssertionError(r.stderr)
        r = subprocess.run([CC, "-std=c11", "-DSEGA_MOD_TARGET_PLATFORM=1", "-DSEGA_MOD_TARGET_ABI_MAJOR=2U", *inc, "-o", str(cls.tmp / "t"), str(cls.tmp / "harness.c"), str(cls.tmp / "p.o")], capture_output=True, text=True)
        if r.returncode != 0: raise AssertionError(r.stderr)

    @classmethod
    def tearDownClass(cls):
        import shutil; shutil.rmtree(cls.tmp, ignore_errors=True)

    def run_script(self, lines):
        r = subprocess.run([str(self.tmp / "t")], input="\n".join(lines) + "\n", capture_output=True, text=True, timeout=60); self.assertEqual(r.returncode, 0, r.stderr); return r.stdout.splitlines()

    def test_it_logs_start_changes_ticks_and_the_explicit_end_and_touches_nothing(self):
        lines = ["init"]
        for frame, pad in ((7, 0), (8, 0), (9, 0x08), (10, 0x08), (11, 0x48), (12, 0x00), (400, 0x80)): lines += ["pad %x" % pad, "frame %d" % frame, "phase input", "phase post-input", "phase frame-end"]
        out = [l for l in self.run_script(lines) if l.startswith("log ")]
        self.assertEqual(out[:5], ["log START 7", "log REC 7 00 00", "log REC 9 08 00", "log REC 11 48 00", "log REC 12 00 00"])
        self.assertIn("log TICK 400", out); self.assertIn("log REC 400 80 00", out)
        self.assertEqual(self.writes(lines), [], "it reads the pad and logs: no write, no pad override, no fault")

    def writes(self, lines): return [l for l in self.run_script(lines) if l.startswith(("write", "setpad", "FAULT"))]

    def test_player_two_start_ends_the_recording_and_nothing_is_logged_after_it(self):
        lines = ["init", "pad 0", "frame 10", "phase input"]
        lines += ["pad2 80", "frame 50", "phase input", "pad2 0", "frame 60", "phase input", "pad 08", "frame 70", "phase input"]
        out = [l for l in self.run_script(lines) if l.startswith("log ")]
        self.assertEqual(out, ["log START 10", "log REC 10 00 00", "log END 50"])

    def test_a_state_load_invalidates_the_recording_explicitly(self):
        lines = ["init", "pad 0", "frame 10", "phase input", "pad 08", "frame 20", "phase input", "load", "pad 04", "frame 12", "phase input", "frame 400", "phase input"]
        out = [l for l in self.run_script(lines) if l.startswith("log ")]
        self.assertEqual(out, ["log START 10", "log REC 10 00 00", "log REC 20 08 00", "log LOAD 20"])
        self.assertEqual(R.parse(''.join('"line":"%s"\n' % l[4:] for l in out)).__len__(), 4)
        with self.assertRaises(R.Refused) as c: R.convert(R.parse(''.join('"line":"%s"\n' % l[4:] for l in out + ["log END 400"])))
        self.assertIn("loaded", str(c.exception))

    def test_manifest_is_read_and_log_only(self):
        m = tomllib.loads((PROJECT / "mod.toml").read_text())
        self.assertEqual(sorted(m["capabilities"]["required"]), ["host.log", "input.read"]); self.assertNotIn("memory", m); self.assertEqual([s["kind"] for s in m["source"]], ["native-c11"])


class Tools(unittest.TestCase):
    def log(self, *rows): return "".join('MOD_LOG {"line":"%s"}\n' % r for r in rows)
    GOOD = ("START 0", "REC 0 00 00", "REC 422 80 00", "REC 426 00 00", "REC 2502 28 00", "TICK 300", "REC 2504 08 c0", "TICK 2800", "END 2900")
    GOOD = ("START 0", "REC 0 00 00", "REC 100 80 00", "REC 104 00 00", "TICK 300", "REC 500 28 00", "TICK 600", "REC 700 08 c0", "TICK 900", "END 1000")

    def conv(self, *rows): return R.convert(R.parse(self.log(*rows)))

    def refused(self, *rows):
        with self.assertRaises(R.Refused) as c: self.conv(*rows)
        return str(c.exception)

    def test_a_complete_recording_gives_exact_headless_entries_duration_and_released_final_buttons(self):
        start, end, v, h = self.conv(*self.GOOD)
        self.assertEqual((start, end), (0, 1000))
        self.assertEqual(h, ["0:1:0x00", "0:2:0x00", "100:1:0x80", "104:1:0x00", "500:1:0x28", "700:1:0x08", "700:2:0x40", "1000:1:0x00", "1000:2:0x00"])   # P2 Start stripped; both ports; held buttons released at END
        self.assertEqual(v, ["0 -", "100 S", "104 -", "500 RC", "700 R", "1000 -", "1000 Q"])

    def test_the_duration_includes_unchanged_input_after_the_last_change(self):
        _, end, _, _ = self.conv("START 0", "REC 0 00 00", "TICK 300", "TICK 600", "END 800")
        self.assertEqual(end, 800)

    def test_incomplete_and_malformed_recordings_are_refused(self):
        self.assertIn("no END", self.refused("START 0", "REC 0 00 00", "TICK 300"))
        self.assertIn("no START", self.refused("REC 0 00 00", "END 10"))
        self.assertIn("more than one START", self.refused("START 0", "REC 0 00 00", "START 5", "END 10"))
        self.assertIn("backwards", self.refused("START 0", "REC 0 00 00", "REC 90 08 00", "REC 80 00 00", "END 100"))        # quick-load / rewind
        self.assertIn("duplicated frame", self.refused("START 0", "REC 0 00 00", "REC 5 08 00", "REC 5 00 00", "END 10"))
        self.assertIn("follow END", self.refused("START 0", "REC 0 00 00", "END 10", "REC 12 08 00"))
        self.assertIn("lost lines", self.refused("START 0", "REC 0 00 00", "TICK 300", "END 2000"))
        with self.assertRaises(R.Refused): self.conv()
        self.assertIn("initial controller sample", self.refused("START 0", "REC 4 08 00", "END 10"))
        self.assertIn("initial controller sample", self.refused("START 0", "TICK 0", "END 10"))
        self.assertIn("a state was loaded", self.refused("START 0", "REC 0 00 00", "LOAD 5", "END 10"))
        for bad in ('REC 5 8 00', 'REC 5 zz 00', 'END', 'TICK x', 'START 0 1'):
            with self.assertRaises(R.Refused): R.parse('"line":"%s"\n' % bad)

    def route(self, changes, two_ports=False):
        rows, f = ["START 0", "REC 0 00 00"], 0
        for i in range(changes):
            f += 2; rows.append("REC %d %02x %02x" % (f, 0x08 if i % 2 == 0 else 0x04, (0x40 if i % 2 == 0 else 0x20) if two_ports else 0))
            if f % 300 == 0: rows.append("TICK %d" % f)
        return rows, f + 2

    def test_scripts_over_the_runtime_capacity_are_refused_not_truncated(self):
        rows, end = self.route(1024)                        # 1,024 changes (+ the end lines) overflow the viewer's 1,024-line script
        self.assertIn("viewer", self.refused(*rows, "END %d" % end))
        rows, end = self.route(1020)                        # fits both
        self.conv(*rows, "END %d" % end)
        rows, end = self.route(2100, two_ports=True)        # 2 entries per change: over the headless 4,096; the viewer limit is hit first, so test the headless one directly
        with self.assertRaises(R.Refused): self.conv(*rows, "END %d" % end)
        old = R.MAX_VIEWER; R.MAX_VIEWER = 10 ** 6
        try: self.assertIn("headless", self.refused(*rows, "END %d" % end))
        finally: R.MAX_VIEWER = old

    def test_the_command_line_writes_the_files_or_refuses_without_writing(self):
        with tempfile.TemporaryDirectory() as d:
            d = pathlib.Path(d); (d / "s.log").write_text(self.log(*self.GOOD))
            r = subprocess.run([sys.executable, str(ROOT / "tools/record_to_pad_script.py"), str(d / "s.log"), "--out", str(d / "x")], capture_output=True, text=True); self.assertEqual(r.returncode, 0, r.stderr)
            sm = json.loads((d / "x.summary.json").read_text()); self.assertEqual((sm["end"], sm["duration_frames"]), (1000, 1000))
            self.assertEqual((d / "x.viewer.txt").read_text().splitlines()[-1], "1000 Q")
            (d / "e.log").write_text(self.log("START 0", "REC 0 00 00", "TICK 300"))
            r = subprocess.run([sys.executable, str(ROOT / "tools/record_to_pad_script.py"), str(d / "e.log"), "--out", str(d / "y")], capture_output=True, text=True)
            self.assertNotEqual(r.returncode, 0); self.assertIn("REFUSED", r.stderr); self.assertFalse((d / "y.headless.txt").exists())

    def test_headless_acceptance_requires_the_exact_endpoint_outcome_and_all_pad_entries(self):
        sm = {"end": 1000, "capture_first": 10, "capture_count": 4, "capture_stride": 330, "expected_pad_entries": 9}
        ok = {"outcome": "window_complete", "frames_captured": 4, "first_frame": 10, "frame_stride": 330, "frame_count": 4, "pad_entries_applied": 9}
        self.assertEqual(S.accept(ok, sm), [])
        for k, v in (("outcome", "io_error"), ("frames_captured", 3), ("pad_entries_applied", 8), ("first_frame", 40)):
            self.assertTrue(S.accept(dict(ok, **{k: v}), sm), k)
        self.assertTrue(any("END frame" in b for b in S.accept(dict(ok, frame_stride=300, frame_count=4), sm)))

    def test_the_capture_window_ends_exactly_on_the_end_frame(self):
        for end in (63, 64, 500, 3700, 99999):
            rows = ["START 0", "REC 0 00 00"] + ["TICK %d" % t for t in range(300, end, 300)] + ["END %d" % end]
            with tempfile.TemporaryDirectory() as d:
                d = pathlib.Path(d); (d / "l").write_text("".join('"line":"%s"\n' % r for r in rows))
                r = subprocess.run([sys.executable, str(ROOT / "tools/record_to_pad_script.py"), str(d / "l"), "--out", str(d / "x")], capture_output=True, text=True); self.assertEqual(r.returncode, 0, r.stderr)
                m = json.loads((d / "x.summary.json").read_text())
                self.assertEqual(m["capture_first"] + m["capture_stride"] * (m["capture_count"] - 1), end); self.assertGreaterEqual(m["capture_first"], 0); self.assertLessEqual(m["capture_count"], 64)

    def test_summarize_capture_decodes_the_observables_and_lists_events(self):
        def sample(score, power, level, x, y, cam): return (score.to_bytes(4, "big") + b"".join((0x807C if i < power else 0x807D).to_bytes(2, "big") for i in range(5)) + level[0].to_bytes(2, "big") + level[1].to_bytes(2, "big") + x.to_bytes(2, "big") + y.to_bytes(2, "big") + cam.to_bytes(2, "big")).hex()
        regions = [dict(offset=int(a), length=int(b)) for a, b in (p.split(":") for p in S.REGIONS.split(","))]
        j = {"outcome": "window_complete", "first_frame": 100, "frame_stride": 50, "ram_regions": regions, "ram_frames": [sample(0, 5, (0, 0), 100, 200, 0), sample(200, 5, (0, 0), 150, 200, 20), sample(200, 3, (0, 0), 160, 200, 30), sample(1000, 3, (0, 1), 48, 100, 0)], "final_work_ram_sha256": "ab"}
        _, rows, events = S.summarize("CAPTURE_SUMMARY " + json.dumps(j))
        self.assertEqual([(r["ordinal"], r["score"], r["power"]) for r in rows], [(100, 0, 5), (150, 200, 5), (200, 200, 3), (250, 1000, 3)])
        self.assertEqual(events, [(150, "score 0 -> 200"), (200, "damage: power 5 -> 3"), (250, "score 200 -> 1000"), (250, "level 0000 -> 0001")])
        j["ram_regions"] = j["ram_regions"][:2]
        with self.assertRaises(SystemExit): S.summarize("CAPTURE_SUMMARY " + json.dumps(j))


if __name__ == "__main__":
    unittest.main()
