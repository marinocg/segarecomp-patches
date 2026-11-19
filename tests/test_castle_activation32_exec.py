"""Functional tests of the ACTUAL injected 32:9 code (castle-of-illusion-activation-32x9/src/retry.asm): the deferral hook, the 16-slot ring and the retry that keeps a deferred section waiting.
Same method as test_castle_activation_exec.py (assembled by the product, executed natively on a synthetic image against stubs of the original loader; nothing commercial). The window / left-deletion / enqueue
behaviour that is shared with the 21:9 code is covered there; this module covers what the 32:9 code adds. Skipped without SEGARECOMP_CLI + SEGARECOMP_SDK_DIR; CI sets SEGARECOMP_REQUIRE_EXEC=1."""
import os, pathlib, re, struct, sys, unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import castle_activation_exec_support as S

if os.environ.get("SEGARECOMP_REQUIRE_EXEC") == "1" and not S.available():
    raise RuntimeError("SEGARECOMP_REQUIRE_EXEC=1 but SEGARECOMP_CLI / SEGARECOMP_SDK_DIR are not set: the executable tests would be skipped")

ASM32 = S.ROOT / "patches/genesis/castle-of-illusion-activation-32x9/src/retry.asm"
MAP32 = {0x00060c80: 0x2000, 0x00060d40: 0x2100, 0x00060e00: 0x2300, 0x00061000: 0x2600, 0x00061060: 0x2700, 0x00061100: 0x2800}
KEY, SLOTS, EXT_END = 0x5AC3, 16, 0xFCB0
X = 0x10
CAMX, CAMY = 0x0400, 0x0100
COUNT = {"fail": 0xA0, "ok": 0xA2, "expired": 0xA4, "drop": 0xA6, "defer": 0xA8, "kept": 0xAA}
POOL = 0xD400
REGS = {"d0": 0x11111111, "d1": 0x22222222, "d2": 0x0000000C, "d3": 0x44444444, "d4": 0x00000007, "d5": 0x00000003, "d6": 0x77777777, "d7": 0x88888888,
        "a0": 0x0000AAAA, "a1": 0x0000BBBB, "a2": 0x0000CA40, "a3": 0xFFFFD040, "a4": 0x0000EEEE, "a5": 0x0000F228}
STACK = 0xFFFF80
THRESHOLD = int(re.search(r"cmpi\.w #(\d+),d3\n  blt\.s nodefer", ASM32.read_text()).group(1)) if ASM32.exists() else 0


def w(v): return struct.pack(">H", v)
def state(key=KEY, tmp=(0, 0), fail=0, retrying=0, slots=(), fc0a=0):
    b = bytearray(EXT_END - 0xFC00)
    b[0:4] = w(tmp[0]) + w(tmp[1]); b[8] = fail; b[9] = retrying; b[0xA] = fc0a; b[0xE:0x10] = w(key)
    for i, (c, r, a) in enumerate(slots): b[0x10 + 8 * i:0x18 + 8 * i] = w(c) + w(r) + w(a) + w(0)
    return bytes(b)
def pool(n):
    """n occupied slots (type word != 0) in the layout pool 0xD400..0xDBFF."""
    return {POOL + 0x40 * i: w(0x0083) for i in range(n)}
def seed(st, n_pool=0, camx=CAMX, camy=CAMY, knob=0, extra=None):
    ram = {0xFC00: st, 0xFA84: w(camx), 0xFA80: w(camy), 0xCA00: w(0x0040), 0x0310: struct.pack(">I", knob), 0x1000: bytes(range(256)) * 4, 0x8000: bytes(range(255, -1, -1)) * 8}
    ram.update(pool(n_pool)); ram.update(extra or {}); return ram
def ring(o): return [struct.unpack(">HHH", o["state"][0x10 + 8 * i:0x16 + 8 * i]) for i in range(SLOTS)]
def ctr(o, name): return struct.unpack(">H", o["state"][COUNT[name]:COUNT[name] + 2])[0]
def cnt(o, off): return struct.unpack(">I", o["log"][off:off + 4])[0]
def paths(o):
    names = {"calls": 0, "scan": 0x14, "next": 0x18, "vert": 0x1C, "tail": 0x20, "level": 0x24}
    return {k: cnt(o, v) for k, v in names.items() if cnt(o, v)}


@unittest.skipUnless(S.available(), "set SEGARECOMP_CLI and SEGARECOMP_SDK_DIR (the product's platforms directory) to execute the injected code")
class Deferral(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.h = S.Harness(asm=ASM32, mapping=MAP32, free_len=0x900, state_end=EXT_END)

    def call_entry(self, col, row, n_pool, retrying=0, key=KEY, slots=(), camx=CAMX, sr=0):
        """The original loader called with (col, row) from the streamer: the stack holds a return address (the `next_entry` stub marks that the caller continued)."""
        ram = seed(state(key=key, retrying=retrying, slots=slots), n_pool, camx=camx, extra={STACK & 0xFFFF: struct.pack(">I", S.SYM["next_entry"])})
        regs = {**REGS, "d2": col, "d5": row, "a7": STACK}
        return ram, self.h.run("entry", regs, ram, ccr=sr), regs

    def defer_rts(self, retrying=False):
        """The address of the RTS the deferral returns through (the harness stops at the first RTS it reaches): the retry-mode path ends at the first RTS of the defer block, the queueing path at the second."""
        base = 0x2800; found = [base + i for i in range(0, 0x100, 2) if self.h.image[base + i:base + i + 2] == b"\x4e\x75"]
        return found[0 if retrying else 1]

    def assert_returned_to_the_caller(self, o, retrying=False):
        self.assertEqual(o["pc"], self.defer_rts(retrying), "stopped at the deferral's own RTS: the original loader body never ran")
        self.assertEqual(paths(o), {}); self.assertEqual(o["a7"], STACK, "everything the hook pushed was popped: the return address is on top")

    def test_shipped_constants(self):
        self.assertEqual((S.re.search(r"lea 0x(4[0-9a-f]{3})\(a1\),a1", ASM32.read_text()) is not None), True)
        self.assertEqual(THRESHOLD, 20)
        text = ASM32.read_text()
        for needle in ("addi.w #0x180,d3", "subi.w #0xf1,d3", "lea 0x3e80(a1),a1", "lea 0x42c0(a1),a1", "cmpi.w #-0x280,d4", "cmpi.w #0x3c0,d4"):
            self.assertIn(needle, text)

    def test_below_the_threshold_nothing_is_deferred_even_far_beyond_the_window(self):
        for col in (30, 0, 12, 11):
            ram, o, regs = self.call_entry(col, 3, THRESHOLD - 1)
            self.assertEqual(paths(o), {"calls": 1}, col)
            self.assertEqual(ring(o), [(0, 0, 0)] * SLOTS); self.assertEqual(ctr(o, "defer"), 0)
            self.assertEqual(o["d3"], 0, "the displaced MOVEQ #0,D3 ran")

    def test_at_the_threshold_only_speculative_columns_are_deferred(self):
        # camera 0x400: the original window is columns (0x400-0x71..0x400+0x180)>>7 = 6..11 (this hook keeps one more column on the left: left of (cam-0xF1)>>7 = 6)
        for col, deferred in ((12, True), (30, True), (11, False), (8, False), (6, False), (5, True), (0, True)):
            ram, o, regs = self.call_entry(col, 3, THRESHOLD)
            self.assertEqual("calls" in paths(o), not deferred, col)
            self.assertEqual(ctr(o, "defer"), 1 if deferred else 0, col)
            self.assertEqual(ring(o)[0] == (col, 3, 24), deferred, col)

    def test_the_decision_follows_the_camera_not_the_host(self):
        for camx, col, deferred in ((0x0000, 4, True), (0x0000, 3, False), (0x0080, 5, True), (0x1000, 35, False), (0x1000, 36, True)):
            ram, o, regs = self.call_entry(col, 2, THRESHOLD, camx=camx)
            self.assertEqual("calls" in paths(o), not deferred, (hex(camx), col))
        # near the level's start the left limit is negative: nothing on the left is speculative
        ram, o, regs = self.call_entry(0, 1, THRESHOLD, camx=0x0010); self.assertIn("calls", paths(o))

    def test_a_deferral_returns_exactly_like_a_loader_that_loaded_nothing(self):
        for sr in (0, X):
            ram, o, regs = self.call_entry(12, 3, THRESHOLD, sr=sr)
            self.assert_returned_to_the_caller(o)
            for k, v in regs.items():
                if k in ("a7", "d3", "d6", "a3"): continue        # the original loader clobbers d3, d6 and a3 too
                self.assertEqual(o[k], v, k)
            base = self.h.run("noop", regs, ram, ccr=sr)
            self.assertEqual(o["hash"], base["hash"], "no guest RAM outside the retry state changed")
            self.assertEqual(ring(o)[0], (12, 3, 24)); self.assertEqual(o["state"][0:4], w(12) + w(3))

    def test_dedup_and_a_full_ring(self):
        ram, o, regs = self.call_entry(12, 3, THRESHOLD, slots=[(12, 3, 9)])
        self.assertEqual(ring(o)[0], (12, 3, 9), "the queued section is not queued twice"); self.assertEqual(ctr(o, "drop"), 0)
        full = [(20 + i, 3, 9) for i in range(SLOTS)]
        ram, o, regs = self.call_entry(12, 3, THRESHOLD, slots=full)
        self.assertEqual(ring(o), full); self.assertEqual(ctr(o, "drop"), 1, "a full ring drops the newcomer and counts it"); self.assert_returned_to_the_caller(o)

    def test_sixteen_distinct_sections_fit(self):
        slots = [(20 + i, 3, 9) for i in range(SLOTS - 1)]
        ram, o, regs = self.call_entry(12, 3, THRESHOLD, slots=slots)
        self.assertEqual(ring(o)[SLOTS - 1], (12, 3, 24))

    def test_inside_a_retry_the_section_keeps_waiting_and_is_flagged(self):
        ram, o, regs = self.call_entry(12, 3, THRESHOLD, retrying=1)
        self.assertEqual(ring(o), [(0, 0, 0)] * SLOTS, "a retry never queues a second copy"); self.assertEqual(o["state"][8], 1); self.assertEqual(o["state"][0xA], 1)
        self.assert_returned_to_the_caller(o, retrying=True)

    def test_an_invalid_state_key_disables_the_deferral(self):
        ram, o, regs = self.call_entry(12, 3, THRESHOLD, key=0)
        self.assertEqual(paths(o), {"calls": 1}); self.assertEqual(ring(o), [(0, 0, 0)] * SLOTS)

    # ---- the retry (frame hook) with a deferral inside it -----------------------------------------------------------------------------------------------------
    def frame(self, slots, n_pool, camx=CAMX, knob=0):
        ram = seed(state(slots=slots), n_pool, camx=camx, knob=knob)
        return self.h.run("frame", REGS, ram, ccr=0)

    def test_a_deferred_section_keeps_its_age_while_it_waits(self):
        o = self.frame([(12, 3, 24), (11, 3, 5)], THRESHOLD)    # 12 is speculative (stays deferred), 11 is in the original window: its load runs
        s = ring(o)
        self.assertEqual(s[0], (12, 3, 24), "waiting is not failing: the age is untouched"); self.assertEqual(ctr(o, "kept"), 1)
        self.assertEqual(s[1][2], 0, "the essential section loaded and left the ring"); self.assertEqual(ctr(o, "ok"), 1); self.assertEqual(paths(o).get("calls"), 1)

    def test_once_the_pool_has_room_the_deferred_section_loads(self):
        o = self.frame([(12, 3, 24)], THRESHOLD - 1)
        self.assertEqual(ring(o)[0][2], 0); self.assertEqual(ctr(o, "ok"), 1); self.assertEqual(paths(o).get("calls"), 1)

    def test_a_deferred_section_that_leaves_the_retry_window_is_dropped(self):
        o = self.frame([(30, 3, 24)], THRESHOLD)       # camera 0x400 + right lookahead 0x2c0 reaches column 14 at most: column 30 is outside the window
        self.assertEqual(ring(o)[0][2], 0); self.assertNotIn("calls", paths(o))

    def test_a_real_allocation_failure_still_ages_and_expires(self):
        o = self.frame([(11, 3, 1)], 0, knob=1)       # the stub loader fails (pool scan exhausted): the original fail path
        self.assertEqual(ring(o)[0][2], 0); self.assertEqual(ctr(o, "expired"), 1)

    def test_the_frame_hook_leaves_registers_and_ram_alone(self):
        ram = seed(state(slots=[(12, 3, 24)]), THRESHOLD)
        o = self.h.run("frame", REGS, ram, ccr=0)
        base = self.h.run("noop", REGS, ram, ccr=0)
        self.assertEqual(o["hash"], base["hash"]); self.assertEqual(o["a7"], 0x01000000)
        for k, v in REGS.items():
            if k != "a6": self.assertEqual(o[k], v, k)

    def test_level_reset_and_cold_start_clear_the_whole_ring(self):
        full = state(slots=[(20 + i, 3, 24) for i in range(SLOTS)], fail=1, retrying=1, fc0a=1)
        o = self.h.run("reset", REGS, seed(full), ccr=0); self.assertEqual(o["state"], state()); self.assertEqual(paths(o), {"level": 1})
        o = self.h.run("frame", REGS, seed(state(key=0x1234, slots=[(20, 3, 24)] * SLOTS)), ccr=0); self.assertEqual(o["state"], state())


if __name__ == "__main__":
    unittest.main()
