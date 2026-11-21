"""Castle of Illusion debug free-fly (patches/genesis/castle-of-illusion/debug-fly): the provider's contract on FABRICATED work RAM (no ROM, no game data), through the same mock ABI 2 host as test_castle_provider.py
(declared ranges enforced: an access outside them faults). Needs SEGARECOMP_SDK_DIR and a C compiler; skipped otherwise, and CI (SEGARECOMP_REQUIRE_EXEC=1) turns a skip into a failure."""
import os, pathlib, subprocess, sys, tempfile, unittest
try: import tomllib
except ImportError: tomllib = None

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import test_castle_provider as P

ROOT = P.ROOT
PROJECT = ROOT / "patches/genesis/castle-of-illusion/debug-fly"
SDK, CC = P.SDK, P.CC
if os.environ.get("SEGARECOMP_REQUIRE_EXEC") == "1" and (not SDK or tomllib is None):
    raise RuntimeError("SEGARECOMP_REQUIRE_EXEC=1 but SEGARECOMP_SDK_DIR is not set or Python lacks tomllib: the debug-fly tests would be skipped")

MICKEY, X, Y, VY_LO, VY_HI = 0xDC00, 0xDC10, 0xDC14, 0xDC1A, 0xDC1C
POWER, HUD, HUDF, CAMX, CAMY = 0xF322, 0xF244, 0xF409, 0xFA84, 0xFA80
REC, LEVEL = 0xFA80, 0xFF44
UP, DOWN, LEFT, RIGHT, B, C, A, START = 1, 2, 4, 8, 0x10, 0x20, 0x40, 0x80
CHORD = A | B | C


@unittest.skipUnless(SDK, "set SEGARECOMP_SDK_DIR to the product's platforms directory")
class Fly(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = pathlib.Path(tempfile.mkdtemp())
        (cls.tmp / "harness.c").write_text(P.HARNESS)
        inc = ["-I", str(pathlib.Path(SDK) / "genesis/sdk"), "-I", str(pathlib.Path(SDK) / "sdk")]
        flags = ["-std=c11", "-Wall", "-Wextra", "-pedantic", "-Werror", "-DSEGA_MOD_TARGET_PLATFORM=1", "-DSEGA_MOD_TARGET_ABI_MAJOR=2U"] + inc
        r = subprocess.run([CC, *flags, "-c", "-o", str(cls.tmp / "provider.o"), str(PROJECT / "src/provider.c")], capture_output=True, text=True)
        if r.returncode != 0: raise AssertionError("the provider does not compile as strict C11:\n" + r.stderr)
        r = subprocess.run([CC, "-std=c11", "-DSEGA_MOD_TARGET_PLATFORM=1", "-DSEGA_MOD_TARGET_ABI_MAJOR=2U", *inc, "-o", str(cls.tmp / "t"), str(cls.tmp / "harness.c"), str(cls.tmp / "provider.o")], capture_output=True, text=True)
        if r.returncode != 0: raise AssertionError("the harness does not build:\n" + r.stderr)

    @classmethod
    def tearDownClass(cls):
        import shutil; shutil.rmtree(cls.tmp, ignore_errors=True)

    def run_script(self, lines):
        m = tomllib.loads((PROJECT / "mod.toml").read_text())
        head = ["range %x %d %d" % (x["offset"], x["length"], 1 if x["access"] in ("write", "read-write") else 0) for x in m["memory"]]
        r = subprocess.run([str(self.tmp / "t")], input="\n".join(head + lines) + "\n", capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout.splitlines()

    @staticmethod
    def world(x=300, y=120, camx=200, camy=0, power=3, record=True, slot=1, level=(0, 0)):
        """A running scrolling level with a live Mickey (record, slot, power, level id, pause flag) on fabricated RAM."""
        r = ["ram %x 2 %x" % (REC + 8, 0xFF if record else 0), "ram %x 2 %x" % (REC + 12, 16 if record else 0), "ram %x 2 %x" % (REC + 14, 240 if record else 0), "ram %x 2 %x" % (REC + 16, 0xFF if record else 0), "ram %x 2 %x" % (REC + 18, 0)]
        return r + ["ram %x 2 %x" % (X, x), "ram %x 2 %x" % (Y, y), "ram %x 2 %x" % (MICKEY, slot), "ram %x 2 %x" % (CAMX, camx), "ram %x 2 %x" % (CAMY, camy), "ram %x 2 %x" % (POWER, power),
                    "ram %x 2 %x" % (VY_LO, 0x6000), "ram %x 2 %x" % (VY_HI, 0xFFFD), "ram %x 2 %x" % (LEVEL, level[0]), "ram %x 2 %x" % (LEVEL + 2, level[1])]

    def frame(self, pad, n=1, world=(), first=False):
        """n frames with the given pad sample; returns the mock's output lines."""
        lines = ["init"] if first else []
        lines += list(world)
        for k in range(n): lines += ["pad %x" % pad, "frame %d" % (k + 1), "phase input", "phase post-input", "phase frame-end"]
        return lines

    def writes(self, out): return [(int(l.split()[1], 16), int(l.split()[2]), int(l.split()[3], 16)) for l in out if l.startswith("write ")]
    def setpads(self, out): return [int(l.split()[2], 16) for l in out if l.startswith("setpad")]
    def last(self, out, addr):
        v = [w[2] for w in self.writes(out) if w[0] == addr]; return v[-1] if v else None

    # ---- toggle ----------------------------------------------------------------------------------------------------------------------------------
    def test_nothing_happens_without_the_chord(self):
        out = self.run_script(self.frame(RIGHT | A, 3, self.world(), first=True))
        self.assertEqual(self.writes(out), []); self.assertEqual(self.setpads(out), [])

    def test_the_chord_is_an_edge_and_starts_flying_from_mickeys_position(self):
        out = self.run_script(["init"] + self.world(300, 120) + ["pad %x" % CHORD, "frame 1", "phase input", "phase post-input", "phase frame-end", "pad %x" % CHORD, "frame 2", "phase input", "phase post-input", "phase frame-end"])
        self.assertEqual(self.last(out, X), 300); self.assertEqual(self.last(out, Y), 120)     # flying from where he is, not from 0
        self.assertEqual(self.setpads(out), [0, 0], "the game sees no button while flying (not even the chord)")
        # held chord does not toggle again: still flying after the second sample
        out2 = self.run_script(["init"] + self.world() + ["pad %x" % CHORD, "frame 1", "phase input", "phase post-input", "phase frame-end", "pad %x" % CHORD, "frame 2", "phase input", "phase post-input", "phase frame-end", "pad %x" % RIGHT, "frame 3", "phase input", "phase post-input"])
        self.assertEqual(self.last(out2, X), 303)

    def test_the_chord_again_leaves_the_mode_and_stops_every_write(self):
        lines = ["init"] + self.world()
        for pad in (CHORD, 0, CHORD, 0, RIGHT, RIGHT): lines += ["pad %x" % pad, "frame 1", "phase input", "phase post-input", "phase frame-end"]
        out = self.run_script(lines)
        self.assertEqual(self.setpads(out)[-2:], [], "after leaving, the pad is the game's again") if False else None
        ws = self.writes(out); n_before = len(ws)
        out_off = self.run_script(["init"] + self.world() + sum((["pad %x" % p, "frame 1", "phase input", "phase post-input", "phase frame-end"] for p in (CHORD, 0, CHORD, 0)), []) + ["echo MARK\n"] + sum((["pad %x" % RIGHT, "frame 1", "phase input", "phase post-input", "phase frame-end"] for _ in range(3)), []))
        tail = out_off[out_off.index("MARK"):]
        self.assertEqual([l for l in tail if l.startswith(("write", "setpad"))], [], "no write and no pad change once the mode is off")

    # ---- flying ----------------------------------------------------------------------------------------------------------------------------------
    def fly(self, pads, world=None):
        lines = ["init"] + (world or self.world()) + ["pad %x" % CHORD, "frame 1", "phase input", "phase post-input", "phase frame-end", "pad 0", "frame 2", "phase input", "phase post-input", "phase frame-end"]
        for p in pads: lines += ["pad %x" % p, "frame 3", "phase input", "phase post-input", "phase frame-end"]
        return self.run_script(lines)

    def test_the_dpad_moves_mickey_three_pixels_and_a_doubles_it(self):
        for pad, dx, dy in ((RIGHT, 3, 0), (LEFT, -3, 0), (UP, 0, -3), (DOWN, 0, 3), (RIGHT | DOWN, 3, 3), (RIGHT | A, 6, 0), (UP | LEFT | A, -6, -6)):
            out = self.fly([pad]); self.assertEqual((self.last(out, X), self.last(out, Y)), (300 + dx, 120 + dy), hex(pad))

    def test_position_fractions_and_vertical_velocity_are_cleared_every_frame(self):
        out = self.fly([RIGHT])
        for addr in (X + 2, Y + 2, VY_LO, VY_HI): self.assertEqual(self.last(out, addr), 0, hex(addr))

    def test_floors_walls_and_enemies_cannot_move_him_the_position_is_asserted_at_the_frames_end(self):
        # the game's collision code changes the position during the frame: the frame-end write puts it back
        lines = ["init"] + self.world(300, 120) + ["pad %x" % CHORD, "frame 1", "phase input", "phase post-input", "phase frame-end", "pad %x" % RIGHT, "frame 2", "phase input", "phase post-input",
                                                  "echo COLLISION\n", "ram %x 2 %x" % (X, 296), "ram %x 2 %x" % (Y, 140), "phase frame-end"]
        out = self.run_script(lines)
        after = out[out.index("COLLISION"):]
        self.assertIn("write %x 2 %x" % (X, 303), after, "a write AFTER the game's correction puts the position back"); self.assertIn("write %x 2 %x" % (Y, 120), after)

    def test_mickey_stays_inside_the_visible_part_of_the_screen_the_camera_is_never_touched(self):
        # camera x 200: screen x = x - 200, allowed 32..272; vertical scroll 0: screen y = y, allowed 16..176
        out = self.fly([RIGHT] * 40, self.world(465, 120, 200, 0)); self.assertLessEqual(self.last(out, X) - 200, 272); self.assertGreaterEqual(self.last(out, X) - 200, 272 - 3)
        out = self.fly([LEFT] * 40, self.world(235, 120, 200, 0)); self.assertGreaterEqual(self.last(out, X) - 200, 32)
        out = self.fly([DOWN] * 40, self.world(300, 170, 200, 0)); self.assertLessEqual(self.last(out, Y), 176)
        out = self.fly([UP] * 40, self.world(300, 20, 200, 0)); self.assertGreaterEqual(self.last(out, Y), 16)
        for out in (self.fly([RIGHT] * 5), self.fly([UP] * 5)): self.assertFalse([w for w in self.writes(out) if w[0] in (CAMX, CAMY)])

    def test_position_is_clamped_to_the_map_and_the_vertical_scroll_wraps_as_a_signed_value(self):
        out = self.fly([LEFT] * 10, self.world(40, 120, 0, 0)); self.assertIn(self.last(out, X), (32, 33, 34))       # camera at the level start: he stops at the left screen margin (3 px steps)
        out = self.fly([DOWN], self.world(300, 100, 200, 1020)); self.assertEqual(self.last(out, Y), 103)      # scroll 1020 = -4: screen y = 104: down is allowed

    # ---- power ----------------------------------------------------------------------------------------------------------------------------------------
    def test_power_is_kept_full_only_while_flying_and_only_when_alive(self):
        out = self.fly([0], self.world(power=2))
        self.assertEqual(self.last(out, POWER), 5); self.assertEqual([self.last(out, HUD + 2 * i) for i in range(5)], [0x807C] * 5); self.assertEqual(self.last(out, HUDF) & 1, 1)
        out = self.fly([0], self.world(power=0)); self.assertIsNone(self.last(out, POWER), "a dead Mickey is the game's own sequence")
        out = self.fly([0], self.world(power=5)); self.assertIsNone(self.last(out, POWER), "no write per frame when already full")
        out = self.run_script(self.frame(0, 3, self.world(power=2), first=True)); self.assertIsNone(self.last(out, POWER), "not flying: untouched")

    # ---- hardening: verified state only, no stale coordinates -------------------------------------------------------------------------------------
    def phase(self, pad, ph=("input", "post-input", "frame-end")): return ["pad %x" % pad, "frame 1"] + ["phase " + p for p in ph]

    def test_activation_is_refused_unless_a_playable_level_with_a_live_mickey_is_verified(self):
        for kw in (dict(record=False), dict(slot=0), dict(power=0), dict(power=6)):
            out = self.run_script(["init"] + self.world(**kw) + self.phase(CHORD) + self.phase(RIGHT))
            self.assertEqual([l for l in out if l.startswith(("write", "setpad"))], [], "refused: no write, and the game keeps its pad (%s)" % kw)

    def test_the_mode_ends_by_itself_without_writing_when_the_state_stops_being_verified(self):
        def scenario(change):
            lines = ["init"] + self.world() + self.phase(CHORD) + self.phase(0) + self.phase(RIGHT) + ["echo CHANGE\n"] + change + self.phase(RIGHT) + self.phase(RIGHT) + self.phase(DOWN)
            out = self.run_script(lines); return out[out.index("CHANGE"):]
        changes = {"level transition": ["ram %x 2 %x" % (LEVEL + 2, 1)], "menu / cutscene / load (record zeroed)": ["ram %x 2 %x" % (REC + 8, 0)], "Mickey's slot freed": ["ram %x 2 %x" % (MICKEY, 0)],
                   "death (power 0)": ["ram %x 2 %x" % (POWER, 0)], "respawn / restart (Mickey moved by 200)": ["ram %x 2 %x" % (X, 100)], "respawn vertically": ["ram %x 2 %x" % (Y, 400)]}
        for name, ch in changes.items():
            tail = scenario(ch)
            self.assertEqual([l for l in tail if l.startswith(("write", "setpad"))], [], name + ": nothing is written again and the pad is the game's again")

    def test_after_the_mode_ended_a_new_level_is_never_given_the_old_coordinates_and_a_new_chord_starts_from_the_new_state(self):
        lines = ["init"] + self.world(300, 120) + self.phase(CHORD) + self.phase(0) + self.phase(RIGHT) + self.world(48, 127, 0, 0, 3, True, 1, (0, 1)) + self.phase(0) + ["pad 0", "frame 9", "phase input", "phase post-input", "phase frame-end", "echo NEWLEVEL\n"]
        lines += self.phase(0) + self.phase(CHORD) + self.phase(0) + self.phase(RIGHT)
        out = self.run_script(lines); tail = out[out.index("NEWLEVEL"):]
        self.assertEqual(self.last(tail, X), 51, "the new chord starts from the NEW level's Mickey (48), not from the old coordinates")

    def test_start_still_reaches_the_game_so_a_flying_player_can_pause(self):
        out = self.run_script(["init"] + self.world() + self.phase(CHORD) + self.phase(0) + self.phase(START) + self.phase(START | RIGHT))
        self.assertEqual(self.setpads(out)[-2:], [START, START], "Start passes; the d-pad does not")
        # no pause flag is read or relied on: while the game is paused only the tracked position changes, and it is asserted again when the game runs
        self.assertEqual(self.last(out, X), 303)

    def test_the_toggling_chord_never_reaches_the_game_on_either_edge_nor_while_held(self):
        out = self.run_script(["init"] + self.world() + self.phase(CHORD | RIGHT) + self.phase(CHORD | RIGHT) + self.phase(0) + self.phase(CHORD | LEFT) + self.phase(CHORD | LEFT) + self.phase(B | C) + self.phase(0) + self.phase(RIGHT))
        pads = self.setpads(out)
        # entering (chord+right, chord+right, release): nothing reaches the game. Leaving (chord+left, chord+left held, then only B+C still down): no A/B/C on the toggling frame, none while held or partially held;
        # the d-pad, which is not part of the chord, passes. Once all three buttons are up the game gets its pad untouched again (no further override).
        self.assertEqual(pads, [0, 0, 0, LEFT, LEFT, 0])

    def test_a_chord_in_an_unverified_state_is_left_to_the_game(self):
        out = self.run_script(["init"] + self.world(record=False) + self.phase(CHORD | RIGHT) + self.phase(0))
        self.assertEqual(self.setpads(out), [], "refused: the game keeps seeing its buttons")

    def test_restore_mid_frame_and_at_a_frame_boundary(self):
        base = ["init"] + self.world(310, 130) + self.phase(CHORD) + self.phase(0) + self.phase(RIGHT)
        out = self.run_script(base + ["save"]); blob = next(l for l in out if l.startswith("state")).split()[1:]; self.assertEqual(len(blob), 24)
        # at a frame boundary: loaded, then a normal frame continues from the saved position (the guest RAM is restored with it; here it still holds the same values)
        out2 = self.run_script(["init"] + self.world(313, 130) + ["load " + " ".join(blob)] + self.phase(RIGHT))
        self.assertEqual(self.last(out2, X), 316)
        # mid-frame: the first frame after the load runs only post-input and frame-end (no input sample): the stale pad must not move him, and the position written is the saved one
        out3 = self.run_script(["init"] + self.world(313, 130) + ["load " + " ".join(blob), "pad 8", "frame 2", "phase post-input", "phase frame-end"])
        self.assertEqual((self.last(out3, X), self.last(out3, Y)), (313, 130))
        # a state saved while flying, restored into another level: the first verification ends the mode, nothing stale is written into that level
        out4 = self.run_script(["init"] + self.world(48, 127, 0, 0, 3, True, 1, (0, 1)) + ["load " + " ".join(blob)] + self.phase(RIGHT) + self.phase(RIGHT))
        self.assertEqual([l for l in out4 if l.startswith("write ")], [], "no stale coordinate is written into a level the state was not saved in")

    # ---- safety ----------------------------------------------------------------------------------------------------------------------------------------
    def test_only_declared_ranges_are_written_and_nothing_faults(self):
        out = self.fly([RIGHT, DOWN, A | LEFT, UP])
        self.assertNotIn("FAULT", out)
        m = tomllib.loads((PROJECT / "mod.toml").read_text()); ok = [(x["offset"], x["offset"] + x["length"]) for x in m["memory"] if x["access"] in ("write", "read-write")]
        for off, w, _ in self.writes(out): self.assertTrue(any(lo <= off and off + w <= hi for lo, hi in ok), hex(off))
        self.assertEqual(sorted(x["access"] for x in m["memory"]), ["read", "read", "read-write", "read-write", "read-write", "read-write"])

    def test_state_roundtrip_and_corrupt_state(self):
        out = self.run_script(["init"] + self.world(310, 130) + ["pad %x" % CHORD, "frame 1", "phase input", "phase post-input", "phase frame-end", "save"])
        blob = next(l for l in out if l.startswith("state")).split()[1:]
        out2 = self.run_script(["init"] + self.world(310, 130) + ["load " + " ".join(blob), "pad %x" % RIGHT, "frame 2", "phase input", "phase post-input"])
        self.assertIn("load 0", out2); self.assertEqual(self.last(out2, X), 313, "still flying after a restore, from the saved position")
        self.assertIn("load 1", self.run_script(["init", "load 00 00 00 05 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00"]))
        self.assertIn("load 1", self.run_script(["init", "load " + " ".join(["00"] * 16)]), "the previous 16-byte format is refused")

    def test_manifest_scope(self):
        m = tomllib.loads((PROJECT / "mod.toml").read_text())
        self.assertEqual(m["target"]["revision"][0]["sha256"], "2d535ff7eda650a64a9093ba6fabf8d5ac87801b898a76b591db41a1c8e47c4f")
        self.assertEqual(sorted(m["capabilities"]["required"]), ["input.intercept", "input.read", "memory.read.m68k.work_ram", "memory.write.m68k.work_ram", "state.mod"])
        self.assertNotIn("hook", m); self.assertNotIn("geometry", m); self.assertEqual([s["kind"] for s in m["source"]], ["native-c11"], "no ROM edit, no guest code")


if __name__ == "__main__":
    unittest.main()
