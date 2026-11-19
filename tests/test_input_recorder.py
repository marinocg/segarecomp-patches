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

    def test_it_logs_only_changes_with_the_guest_frame_number_and_touches_nothing(self):
        lines = ["init"]
        for frame, pad in ((7, 0), (8, 0), (9, 0x08), (10, 0x08), (11, 0x48), (12, 0x00), (100000, 0x80)): lines += ["pad %x" % pad, "frame %d" % frame, "phase input", "phase post-input", "phase frame-end"]
        out = self.run_script(lines)
        self.assertEqual([l for l in out if l.startswith("log ")], ["log REC 7 00 00", "log REC 9 08 00", "log REC 11 48 00", "log REC 12 00 00", "log REC 100000 80 00"])
        self.assertEqual([l for l in out if l.startswith(("write", "setpad", "FAULT"))], [], "it reads the pad and logs: no write, no pad override, no fault")

    def test_manifest_is_read_and_log_only(self):
        m = tomllib.loads((PROJECT / "mod.toml").read_text())
        self.assertEqual(sorted(m["capabilities"]["required"]), ["host.log", "input.read"]); self.assertNotIn("memory", m); self.assertEqual([s["kind"] for s in m["source"]], ["native-c11"])


class Tools(unittest.TestCase):
    LOG = ('MOD_LOG {"line":"REC 0 00 00"}\nnoise\nMOD_LOG {"line":"REC 422 80 00"}\nMOD_LOG {"line":"REC 426 00 00"}\nMOD_LOG {"line":"REC 2502 28 00"}\nMOD_LOG {"line":"REC 2504 08 40"}\n')

    def test_convert_to_viewer_and_headless_scripts(self):
        e = R.parse(self.LOG); v, h = R.convert(e)
        self.assertEqual(v, ["0 -", "422 S", "426 -", "2502 RC", "2504 R"])
        self.assertEqual(h, ["0:1:0x00", "0:2:0x00", "422:1:0x80", "426:1:0x00", "2502:1:0x28", "2504:1:0x08", "2504:2:0x40"])

    def test_a_rewound_session_is_refused(self):
        with self.assertRaises(SystemExit): R.convert(R.parse('"line":"REC 100 00 00"\n"line":"REC 90 08 00"'))

    def test_the_command_line_writes_the_three_files_and_a_quit_line(self):
        with tempfile.TemporaryDirectory() as d:
            d = pathlib.Path(d); (d / "s.log").write_text(self.LOG)
            r = subprocess.run([sys.executable, str(ROOT / "tools/record_to_pad_script.py"), str(d / "s.log"), "--out", str(d / "x"), "--quit-after", "60"], capture_output=True, text=True); self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual((d / "x.viewer.txt").read_text().splitlines()[-1], "2564 Q"); self.assertEqual(json.loads((d / "x.summary.json").read_text())["last_frame"], 2504)
            self.assertTrue((d / "x.headless.txt").read_text().startswith("0:1:0x00,0:2:0x00,422:1:0x80"))
            (d / "e.log").write_text("nothing here"); self.assertNotEqual(subprocess.run([sys.executable, str(ROOT / "tools/record_to_pad_script.py"), str(d / "e.log"), "--out", str(d / "y")], capture_output=True, text=True).returncode, 0)

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
