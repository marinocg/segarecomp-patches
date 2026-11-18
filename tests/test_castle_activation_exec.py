"""Functional tests of the ACTUAL injected retry code (castle-of-illusion-activation-21x9/src/retry.asm): assembled by the product, executed natively on a synthetic image against stubs of the original loader.
Covers initialization, level reset, enqueue, deduplication, queue-full, expiry, success, invalidation, register/stack preservation and memory bounds. Skipped (never silently passed) without SEGARECOMP_CLI + SEGARECOMP_SDK_DIR."""
import struct, sys, pathlib, unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import castle_activation_exec_support as S

KEY = 0x5AC3
CAMX, CAMY = 0x0400, 0x0100          # window: columns 5..14, rows 0..7 for the shipped lookahead constants (see test_window below)


def w(v): return struct.pack(">H", v)
def state(key=KEY, tmp=(0, 0), fail=0, retrying=0, slots=()):
    b = bytearray(0x30)
    b[0:4] = w(tmp[0]) + w(tmp[1]); b[8] = fail; b[9] = retrying; b[0xE:0x10] = w(key)
    for i, (c, r, a) in enumerate(slots): b[0x10 + 8 * i:0x18 + 8 * i] = w(c) + w(r) + w(a) + w(0)
    return bytes(b)
def seed(st, camx=CAMX, camy=CAMY, ca00=0x0040, knob=0):
    return {0xFC00: st, 0xFA84: w(camx), 0xFA80: w(camy), 0xCA00: w(ca00), 0x0310: struct.pack(">I", knob)}
def slots_of(o):
    st = o["state"]; return [(struct.unpack(">HHH", st[0x10 + 8 * i:0x16 + 8 * i])) for i in range(4)]
def calls(o): return struct.unpack(">I", o["log"][0:4])[0]
def counter(o, off): return struct.unpack(">I", o["log"][off:off + 4])[0]
REGS = {"d0": 0x11111111, "d1": 0x22222222, "d2": 0x33333333, "d3": 0x44444444, "d4": 0x00000007, "d5": 0x66666666, "d6": 0x77777777, "d7": 0x88888888,
        "a0": 0x0000AAAA, "a1": 0x0000BBBB, "a2": 0x0000CCCC, "a3": 0x0000DDDD, "a4": 0x0000EEEE, "a5": 0x0000F228}


@unittest.skipUnless(S.available(), "set SEGARECOMP_CLI and SEGARECOMP_SDK_DIR (the product's platforms directory) to execute the injected code")
class RetryCode(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.h = S.Harness()

    def test_window_constants_are_the_shipped_ones(self):
        self.assertEqual((S.WINDOW_R, S.WINDOW_L), (0x280, 0x100))
        self.assertEqual(((CAMX - S.WINDOW_L) >> 7) - 1, 5); self.assertEqual(((CAMX + S.WINDOW_R) >> 7) + 1, 14)

    def test_cold_start_initializes_before_any_use(self):
        garbage = state(key=0x1234, slots=[(10, 3, 7), (11, 3, 9), (12, 3, 5), (13, 3, 24)], fail=1, retrying=1)
        o = self.h.run("frame", REGS, seed(garbage))
        self.assertEqual(o["state"], state(), "the ring is cleared and armed before the vertical loader and before any retry")
        self.assertEqual(calls(o), 0); self.assertEqual(counter(o, 0x1C), 1); self.assertEqual(counter(o, 0x20), 1)

    def test_frame_hook_preserves_registers_and_stack(self):
        for st in (state(), state(slots=[(10, 3, 24)])):
            o = self.h.run("frame", REGS, seed(st))
            for k, v in REGS.items():
                if k != "a6": self.assertEqual(o[k], v, k)
            self.assertEqual(o["a6"], 0xFFFFFA80); self.assertEqual(o["a7"], 0x01000000)   # a6 is set exactly as the original `lea $fa80,a6` does

    def test_enqueue_and_original_continuation(self):
        o = self.h.run("fail", {**REGS, "d6": 0}, seed(state(tmp=(10, 3))))
        self.assertEqual(slots_of(o)[0], (10, 3, 24)); self.assertEqual(o["state"][8], 1)
        self.assertEqual(counter(o, 0x18), 1); self.assertEqual(o["d6"], 0x0000FFFF)
        for k in ("d0", "d1", "a0"): self.assertEqual(o[k], REGS[k], k)
        self.assertEqual(o["a7"], 0x01000000)

    def test_scan_continues_while_slots_remain(self):
        o = self.h.run("fail", {**REGS, "d6": 3}, seed(state(tmp=(10, 3))))
        self.assertEqual(counter(o, 0x14), 1); self.assertEqual(o["state"], state(tmp=(10, 3)))

    def test_dedup(self):
        o = self.h.run("fail", {**REGS, "d6": 0}, seed(state(tmp=(10, 3), slots=[(10, 3, 9)])))
        self.assertEqual(slots_of(o), [(10, 3, 9), (0, 0, 0), (0, 0, 0), (0, 0, 0)])

    def test_same_column_other_row_is_a_different_section(self):
        o = self.h.run("fail", {**REGS, "d6": 0}, seed(state(tmp=(10, 4), slots=[(10, 3, 9)])))
        self.assertEqual(slots_of(o)[:2], [(10, 3, 9), (10, 4, 24)])

    def test_distinct_section_takes_the_next_slot(self):
        o = self.h.run("fail", {**REGS, "d6": 0}, seed(state(tmp=(11, 3), slots=[(10, 3, 9)])))
        self.assertEqual(slots_of(o)[:2], [(10, 3, 9), (11, 3, 24)])

    def test_queue_full_drops_the_fifth_without_touching_the_four(self):
        full = [(10, 3, 9), (11, 3, 8), (12, 3, 7), (13, 3, 6)]
        o = self.h.run("fail", {**REGS, "d6": 0}, seed(state(tmp=(14, 3), slots=full)))
        self.assertEqual(slots_of(o), full); self.assertEqual(o["state"][8], 1)

    def test_no_enqueue_while_retrying_or_with_a_bad_key(self):
        o = self.h.run("fail", {**REGS, "d6": 0}, seed(state(tmp=(10, 3), retrying=1)))
        self.assertEqual(slots_of(o)[0], (0, 0, 0)); self.assertEqual(o["state"][8], 1)
        o = self.h.run("fail", {**REGS, "d6": 0}, seed(state(key=0, tmp=(10, 3))))
        self.assertEqual(slots_of(o)[0], (0, 0, 0))

    def test_retry_success_rebuilds_the_loader_arguments_and_clears_the_slot(self):
        o = self.h.run("frame", REGS, seed(state(slots=[(10, 3, 24), (11, 3, 5)])))
        self.assertEqual(calls(o), 2)                      # both slots are served in one invocation (no starvation)
        self.assertEqual([s[2] for s in slots_of(o)[:2]], [0, 0])
        log = o["log"]; self.assertEqual(struct.unpack(">HH", log[4:8]), (11, 3))      # the last call's d2 (column) and d5 (row)
        self.assertEqual(struct.unpack(">I", log[8:12])[0], 0xFFFFCA40); self.assertEqual(struct.unpack(">I", log[12:16])[0], 0xFFFFCA02)

    def test_retry_failure_keeps_the_slot_and_ages_it(self):
        o = self.h.run("frame", REGS, seed(state(slots=[(10, 3, 24)]), knob=1))
        self.assertEqual(slots_of(o)[0], (10, 3, 23)); self.assertEqual(calls(o), 1)

    def test_expiry_after_the_last_attempt(self):
        o = self.h.run("frame", REGS, seed(state(slots=[(10, 3, 1)]), knob=1))
        self.assertEqual(slots_of(o)[0][2], 0); self.assertEqual(calls(o), 1)

    def test_invalid_slot_is_dropped_without_a_load(self):
        for c, r in ((40, 3), (10, 30), (2, 3)):
            o = self.h.run("frame", REGS, seed(state(slots=[(c, r, 24)])))
            self.assertEqual(slots_of(o)[0][2], 0, (c, r)); self.assertEqual(calls(o), 0, (c, r))

    def test_level_reset_clears_all_four_and_continues_into_the_original(self):
        o = self.h.run("reset", REGS, seed(state(slots=[(10, 3, 24), (11, 3, 12), (12, 3, 5), (13, 3, 1)], fail=1)))
        self.assertEqual(o["state"], state()); self.assertEqual(counter(o, 0x24), 1)
        for k, v in REGS.items(): self.assertEqual(o[k], v, k)

    def test_left_cull_moves_the_limit_to_the_left_lookahead(self):
        # d4 = screen x + 128 (the original deleted the object when it was negative); now it is deleted below -(left lookahead)
        for d4, deleted in ((0x0005, False), (0x0000, False), (0xFFFF, False), (0x10000 - S.WINDOW_L, False), (0x10000 - S.WINDOW_L - 1, True), (0x8000, True)):
            o = self.h.run("cull", {**REGS, "d4": d4}, seed(state()))
            self.assertEqual((counter(o, 0x2C), counter(o, 0x28)), (1, 0) if deleted else (0, 1), hex(d4))
            for k, v in REGS.items():
                if k != "d4": self.assertEqual(o[k], v, k)

    def test_memory_outside_the_extent_is_untouched(self):
        scenarios = [("frame", state(slots=[(10, 3, 24), (11, 3, 5)]), 0), ("frame", state(key=7), 1), ("fail", state(tmp=(10, 3)), 0), ("reset", state(), 0), ("cull", state(), 0)]
        for where, st, knob in scenarios:
            base = self.h.run("noop", REGS, seed(st, knob=knob)); o = self.h.run(where, {**REGS, "d6": 0}, seed(st, knob=knob))
            self.assertEqual(o["hash"], base["hash"], where); self.assertEqual(o["above"], base["above"], where)


if __name__ == "__main__":
    unittest.main()
