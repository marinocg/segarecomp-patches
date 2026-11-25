"""The pure helpers of tools/abi_parity_compare.py (SEG-152-T009/T010): pad-script construction and the comparison verdict logic. The tool itself needs a legally held image, a product checkout and a compiler and is
local-only; nothing here touches any of them (a fabricated trace stands in for a run)."""
import importlib.util, pathlib, sys, unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("abi_parity_compare", ROOT / "tools" / "abi_parity_compare.py")
tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tool)


def make_bmp(w=96, h=64, paint=None):
    """A fabricated 24-bit BMP (synthetic imagery only): a gradient, optionally with `paint` {(x, y): (r, g, b)} overrides."""
    paint = paint or {}
    stride = (w * 3 + 3) & ~3
    body = bytearray()
    for y in range(h - 1, -1, -1):   # bottom-up, like the viewer's capture
        row = bytearray()
        for x in range(w):
            r, g, b = paint.get((x, y), (x * 2 % 256, y * 4 % 256, (x + y) % 256))
            row += bytes((b, g, r))
        body += row + b"\0" * (stride - w * 3)
    head = b"BM" + (54 + len(body)).to_bytes(4, "little") + b"\0\0\0\0" + (54).to_bytes(4, "little") + (40).to_bytes(4, "little") + w.to_bytes(4, "little") + h.to_bytes(4, "little") + b"\1\0\x18\0" + b"\0" * 24
    return bytes(head) + bytes(body)


def run(verdicts, bmp=None, ram=None, coverage=None, end=39, rc=0, outcome="window_closed", native=True, mod_summary=True, events=None, replay=False, session=None):
    cov = coverage if coverage is not None else {c: {"offered": 1, "accepted": 1, "presented": 1, "rejected": 0} for c in ("scenery", "hud")}
    trace = {f: {"f": f, "status": v[0], "side": v[1], "shift": v[2], "acc": v[3], "reason": v[4], "auth": v[5]} for f, v in verdicts.items()}
    ev = events if events is not None else [(f,) + tuple(v) for f, v in verdicts.items()]
    return {"trace": trace, "events": ev, "bmp": bmp if bmp is not None else make_bmp(), "ram": ram if ram is not None else bytes(65536), "coverage": cov,
            "summary": {"faulted": False} if mod_summary else {}, "native": {"frames": len(ev)} if native else {}, "rc": rc, "outcome": outcome, "end_poll": end,
            "replay": replay, "session": session}


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

    def test_a_scenario_that_never_presents_scenery_is_not_evidence(self):
        c = self.comparer()
        quiet = {f: (2, 238, 0, 1, 0, 0) for f in range(0, 40)}   # HUD only: the presentation silently was Original
        self.assertFalse(c.equal("wide", run(quiet), run(quiet)))
        self.assertTrue(c.equal("orig", run(quiet), run(quiet)))   # Original asks for no scenery by design

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


class MarginMaze(unittest.TestCase):
    """The operator-approved special-stage difference (SEG-152-T009): ONLY the accepted mask gains a bit, in the frames that deliver the margin maze."""
    SS = {f: (2, 238, 0, 2, 0, 1) for f in range(1, 40)}

    def comparer(self):
        c = object.__new__(tool.Cmp)
        c.failures, c.report = [], {}
        return c

    def with_maze(self, frames, field=3, value=3):
        v = dict(self.SS)
        for f in frames:
            row = list(v[f]); row[field] = value; v[f] = tuple(row)
        return v

    def test_the_extra_mask_bit_in_some_frames_is_the_approved_difference(self):
        a, b = run(self.SS), run(self.with_maze(range(10, 20)))
        extra, bad = self.comparer().maze_frames(a, b)
        self.assertEqual((extra, bad), (list(range(10, 20)), []))
        self.assertTrue(self.comparer().equal_maze("special-wide", a, b, "wide", minimum=30))

    def test_any_other_difference_is_not_approved(self):
        a = run(self.SS)
        for field, value in ((0, 3), (1, 300), (2, 5), (4, 7), (5, 0)):   # status, side, shift, reason, authored
            extra, bad = self.comparer().maze_frames(a, run(self.with_maze([12], field, value)))
            self.assertEqual((extra, bad), ([], [12]), field)
        extra, bad = self.comparer().maze_frames(a, run(self.with_maze([12], 3, 6)))   # a different mask, not "one more bit"
        self.assertEqual(bad, [12])
        c = self.comparer()
        self.assertFalse(c.equal_maze("special-wide", a, run(self.with_maze([12], 4, 7)), "wide", minimum=30))

    def test_without_a_presented_margin_nothing_may_differ(self):
        a = run(self.SS)
        self.assertTrue(self.comparer().equal_maze("special-orig", a, run(self.SS), "orig", minimum=30))
        self.assertFalse(self.comparer().equal_maze("special-orig", a, run(self.with_maze([12])), "orig", minimum=30))
        self.assertFalse(self.comparer().equal_maze("special-wide", a, run(self.SS), "wide", minimum=30))   # a margin mode that never delivers the maze proves nothing

    def test_content_rect_finds_the_presented_picture(self):
        w, h = 40, 30
        paint = {(x, y): (9, 9, 9) for x in range(10, 30) for y in range(5, 25)}
        black = {(x, y): (0, 0, 0) for x in range(w) for y in range(h)}
        black.update(paint)
        self.assertEqual(tool.content_rect(make_bmp(w, h, black)), (10, 5, 30, 25))


class ProviderVariants(unittest.TestCase):
    """The test-only provider variants the local comparator builds (maze-free, no per-row answer, redraw self-test and its deliberate mutant, coverage logging) are text edits of the real Sonic 1 provider: each must still apply to it, so
    a provider change that breaks a variant fails here (no product CLI needed) instead of silently invalidating the local evidence."""
    SRC = (ROOT / "patches/genesis/sonic-1/native-widescreen-abi2/src/provider.c").read_text()

    def test_every_variant_applies_to_the_real_provider(self):
        for name, edit in (("selfmaze", tool.selfmaze_edit), ("selfbad", tool.selfbad_edit), ("coverage", tool.coverage_edit)):
            out = edit(self.SRC)
            self.assertNotEqual(out, self.SRC, name)
        self.assertIn("g_vset.budget_mode = GENESIS_VSPRITE_BUDGET_LIMIT;", tool.selfmaze_edit(self.SRC))
        self.assertNotIn("u16(ram, ot + 6U) - u16(ram, ou + 6U)", tool.selfbad_edit(self.SRC))   # the mutant really drops the art-tile base adjustment
        self.assertIn("host.log", tool.coverage_manifest('[capabilities]\nrequired = ["frame.vdp"]\n'))
        self.assertEqual(tool.coverage_manifest('required = ["host.log"]'), 'required = ["host.log"]')

    def test_the_inline_variant_targets_exist(self):
        self.assertIn("if (v->side != 0U) ss_margin_maze(", self.SRC)   # maze-free variant
        self.assertIn("if (r->scenery_generic_rows(0U, mask, 224U, 28U) != 0 || r->scenery_generic_rows(1U, mask, 224U, 28U) != 0) return;", self.SRC)   # no-per-row-answer variant
        self.assertIn("  r = feat->render;\n", self.SRC)   # fault variant

    def test_a_variant_refuses_a_provider_it_does_not_fit(self):
        for edit in (tool.selfmaze_edit, tool.coverage_edit):
            with self.assertRaises(ValueError):
                edit("int main(void) { return 0; }\n")


class Privacy(unittest.TestCase):
    """--work holds intermediate ROM images, captures and RAM snapshots and --diag the pictures: neither may resolve inside the public repository."""
    def test_paths_inside_the_repository_are_refused(self):
        for inside in (ROOT, ROOT / "work", ROOT / "tools" / ".." / "tmp-captures"):
            with self.assertRaises(SystemExit):
                tool.require_outside_repo(inside, "--work")

    def test_a_symlink_into_the_repository_is_refused(self):
        import tempfile
        with tempfile.TemporaryDirectory() as t:
            link = pathlib.Path(t) / "link"
            link.symlink_to(ROOT)
            with self.assertRaises(SystemExit):
                tool.require_outside_repo(link / "captures", "--diag")

    def test_a_directory_elsewhere_is_accepted(self):
        import tempfile
        with tempfile.TemporaryDirectory() as t:
            self.assertEqual(tool.require_outside_repo(t, "--work"), pathlib.Path(t).resolve())

    def test_cmp_refuses_a_work_directory_in_the_repository(self):
        import argparse
        with self.assertRaises(SystemExit):
            tool.Cmp(argparse.Namespace(product_root=str(ROOT), work=str(ROOT / "work")))


class Evidence(unittest.TestCase):
    """The negative tests of the comparator itself: a truncated, gapped, unhealthy or visually different run, or a checkpoint with the wrong frame identity, must NOT pass."""
    GOOD = {f: (2, 238, 0, 3, 0, 1) for f in range(0, 40)}

    def test_a_complete_run_has_no_problem(self):
        self.assertEqual(tool.validate_run(run(self.GOOD), "r", 39, mod=True), [])

    def test_truncated_run_is_rejected(self):
        short = {f: v for f, v in self.GOOD.items() if f < 20}
        self.assertTrue(any("does not cover" in p for p in tool.validate_run(run(short), "r", 39)))

    def test_run_that_overshoots_its_script_is_rejected(self):
        long_ = {f: (2, 238, 0, 3, 0, 1) for f in range(0, 80)}
        self.assertTrue(any("does not cover" in p for p in tool.validate_run(run(long_), "r", 39)))

    def test_missing_frame_is_rejected(self):
        gap = {f: v for f, v in self.GOOD.items() if f != 17}
        self.assertTrue(any("not consecutive" in p for p in tool.validate_run(run(gap), "r", 39)))

    def test_unhealthy_runs_are_rejected(self):
        for kw, frag in (({"rc": 1}, "exit status"), ({"outcome": "guest_stop"}, "terminal outcome"), ({"native": False}, "no native summary"), ({"coverage": {}}, "coverage information"),
                         ({"bmp": b""}, "no valid final capture"), ({"ram": b"x"}, "guest RAM capture"), ({"mod_summary": False}, "no mod summary"), ({"events": []}, "no trace")):
            self.assertTrue(any(frag in p for p in tool.validate_run(run(self.GOOD, **kw), "r", 39, mod=True)), kw)
        self.assertTrue(any("coverage information" in p for p in tool.validate_run(run(self.GOOD, coverage={"scenery": {"offered": 1}, "hud": {}}), "r", 39)))

    def test_a_replayed_session_must_complete(self):
        ok = tool.validate_run(run(self.GOOD, replay=True, session={"mode": "replay", "outcome": "complete", "frame": 39}), "r", 39)
        self.assertEqual(ok, [])
        self.assertEqual(tool.validate_run(run(self.GOOD, replay=True, session={"outcome": "complete_unverified"}), "r", 39), [])   # the viewer's own checkpoint check is only made for the program that recorded
        for bad in (None, {"outcome": "diverged"}, {"outcome": "incomplete"}):
            self.assertTrue(any("did not replay to its end" in p for p in tool.validate_run(run(self.GOOD, replay=True, session=bad), "r", 39)), bad)

    def test_a_restore_needs_its_one_discontinuity(self):
        plain = tool.validate_run(run(self.GOOD), "r", 39, restore="load")
        self.assertTrue(any("exactly one load discontinuity" in p for p in plain))
        fwd = {f: (2, 238, 0, 3, 0, 1) for f in list(range(0, 10)) + list(range(30, 40))}
        self.assertEqual(tool.validate_run(run(fwd), "r", 39, restore="load"), [])
        self.assertTrue(any("exactly one rewind" in p for p in tool.validate_run(run(fwd), "r", 39, restore="rewind")))
        ev = [(f, 2, 238, 0, 3, 0, 1) for f in list(range(0, 20)) + list(range(10, 25))]   # repeated frame numbers after a backward jump are legitimate for a rewind only
        self.assertEqual(tool.validate_run(run({}, events=ev), "r", 24, restore="rewind"), [])
        self.assertTrue(any("not consecutive" in p for p in tool.validate_run(run({}, events=ev), "r", 24)))

    def test_ordered_occurrences_are_compared_not_the_last_of_a_frame_number(self):
        c = object.__new__(tool.Cmp)
        a = run(self.GOOD)
        b = run(self.GOOD)
        b["events"] = b["events"][:5] + [b["events"][6], b["events"][5]] + b["events"][7:]   # the same per-frame verdicts, in another order
        self.assertIn("ordered-occurrences", c.compare("k", a, b)[0])

    def test_checkpoint_identical_pictures_pass(self):
        bad, d = tool.compare_checkpoint(run(self.GOOD), run(self.GOOD), 39, "cp")
        self.assertEqual((bad, d["differing"], d["bbox"]), ([], 0, None))

    def test_checkpoint_with_a_differing_intermediate_picture_fails_with_count_and_box(self):
        other = make_bmp(paint={(10, 20): (255, 0, 0), (12, 22): (0, 255, 0)})
        bad, d = tool.compare_checkpoint(run(self.GOOD), run(self.GOOD, bmp=other), 39, "cp")
        self.assertTrue(any("2 pixels differ" in p for p in bad))
        self.assertEqual((d["differing"], d["bbox"]), (2, (10, 20, 12, 22)))

    def test_checkpoint_with_different_geometry_fails(self):
        bad, _ = tool.compare_checkpoint(run(self.GOOD), run(self.GOOD, bmp=make_bmp(w=100)), 39, "cp")
        self.assertTrue(any("geometry" in p for p in bad))

    def test_checkpoint_with_the_wrong_frame_identity_fails(self):
        shifted = {f: (2, 238, 0, 3, 0, 1) for f in range(1, 41)}
        bad, _ = tool.compare_checkpoint(run(self.GOOD), run(shifted), 39, "cp")
        self.assertTrue(any("different guest frames" in p for p in bad))
        far = {f: (2, 238, 0, 3, 0, 1) for f in range(0, 60)}
        bad, _ = tool.compare_checkpoint(run(far), run(far), 39, "cp")
        self.assertTrue(any("does not cover" in p for p in bad))   # both ended on the same frame, but not the requested one

    def test_checkpoint_of_an_incomplete_run_cannot_pass_on_equal_pictures(self):
        bad, _ = tool.compare_checkpoint(run(self.GOOD, rc=1), run(self.GOOD), 39, "cp")
        self.assertTrue(any("exit status" in p for p in bad))

    def test_bmp_diff_and_png_helpers(self):
        a, b = make_bmp(), make_bmp(paint={(0, 0): (1, 2, 3), (95, 63): (4, 5, 6)})
        d = tool.bmp_diff(a, b)
        self.assertEqual((d["differing"], d["bbox"]), (2, (0, 0, 95, 63)))
        w, h, rows = tool.diff_visual(a, b, d)
        self.assertEqual((w, h, len(rows)), (96, 64, 64))
        import tempfile
        with tempfile.TemporaryDirectory() as t:
            tool.write_png(pathlib.Path(t) / "x.png", w, h, rows)
            self.assertEqual((pathlib.Path(t) / "x.png").read_bytes()[:8], b"\x89PNG\r\n\x1a\n")
        with self.assertRaises(ValueError):
            tool.bmp_info(a[:60])
