"""Functional tests of the ACTUAL injected retry code (castle-of-illusion-activation-21x9/src/retry.asm): assembled by the product, executed natively on a synthetic image against stubs of the original loader.
Each scenario asserts the exact continuation PATH taken (which original continuation ran, how often, and where the run stopped), the CCR, every register, and the COMPLETE work RAM image (everything except the
documented retry-state extent 0xFC00..0xFC2F, the test stubs' counters 0x0300..0x033F, and the stack area 0xFF00.. whose pointer is asserted to return to its initial value).
Skipped (never silently passed) without SEGARECOMP_CLI + SEGARECOMP_SDK_DIR; CI sets SEGARECOMP_REQUIRE_EXEC=1 so a skip there is a failure."""
import os, re, struct, sys, pathlib, unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import castle_activation_exec_support as S

if os.environ.get("SEGARECOMP_REQUIRE_EXEC") == "1" and not S.available():
    raise RuntimeError("SEGARECOMP_REQUIRE_EXEC=1 but SEGARECOMP_CLI / SEGARECOMP_SDK_DIR are not set: the executable tests would be skipped")

KEY = 0x5AC3
CAMX, CAMY = 0x0400, 0x0100
X, N, Z, V, C = 0x10, 0x08, 0x04, 0x02, 0x01
SR_USER = 0x00


def w(v): return struct.pack(">H", v)
def state(key=KEY, tmp=(0, 0), fail=0, retrying=0, slots=()):
    b = bytearray(0x30)
    b[0:4] = w(tmp[0]) + w(tmp[1]); b[8] = fail; b[9] = retrying; b[0xE:0x10] = w(key)
    for i, (c, r, a) in enumerate(slots): b[0x10 + 8 * i:0x18 + 8 * i] = w(c) + w(r) + w(a) + w(0)
    return bytes(b)
def seed(st, camx=CAMX, camy=CAMY, ca00=0x0040, knob=0, extra=None):
    ram = {0xFC00: st, 0xFA84: w(camx), 0xFA80: w(camy), 0xCA00: w(ca00), 0x0310: struct.pack(">I", knob), 0x1000: bytes(range(256)) * 4, 0x8000: bytes(range(255, -1, -1)) * 8}
    ram.update(extra or {}); return ram
def slots_of(o): return [struct.unpack(">HHH", o["state"][0x10 + 8 * i:0x16 + 8 * i]) for i in range(4)]
def cnt(o, off): return struct.unpack(">I", o["log"][off:off + 4])[0]
def paths(o):
    """The continuations that ran: {name: count}; zero entries omitted."""
    names = {"calls": 0, "scan": 0x14, "next": 0x18, "vert": 0x1C, "tail": 0x20, "level": 0x24, "cull_continue": 0x28, "cull_delete": 0x2C}
    return {k: cnt(o, v) for k, v in names.items() if cnt(o, v)}
REGS = {"d0": 0x11111111, "d1": 0x22222222, "d2": 0x33333333, "d3": 0x44444444, "d4": 0x00000007, "d5": 0x66666666, "d6": 0x77777777, "d7": 0x88888888,
        "a0": 0x0000AAAA, "a1": 0x0000BBBB, "a2": 0x0000CCCC, "a3": 0xFFFFD040, "a4": 0x0000EEEE, "a5": 0x0000F228}
SP0 = 0x01000000


@unittest.skipUnless(S.available(), "set SEGARECOMP_CLI and SEGARECOMP_SDK_DIR (the product's platforms directory) to execute the injected code")
class RetryCode(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.h = S.Harness()

    def run_hook(self, where, regs=None, ram=None, sr=SR_USER):
        return self.h.run(where, {**REGS, **(regs or {})}, ram, ccr=sr & 0x1F)

    def baseline(self, ram, regs=None, sr=SR_USER):
        return self.h.run("noop", {**REGS, **(regs or {})}, ram, ccr=sr & 0x1F)

    def assert_same_ram_and_registers(self, o, base, keep=()):
        self.assertEqual(o["hash"], base["hash"], "the complete work RAM image (outside the documented extents) is unchanged")
        self.assertEqual(o["a7"], SP0, "the stack pointer returned to its initial value")
        for k, v in REGS.items():
            if k not in keep: self.assertEqual(o[k], v, k)

    # ---- constants and static properties -------------------------------------------------------------------------------------------------------------------
    def test_shipped_constants(self):
        self.assertEqual((S.WINDOW_R, S.WINDOW_L, S.CULL_LEFT, S.CULL_RIGHT), (0x280, 0x100, 0x200, 0x380))
        self.assertEqual(((CAMX - S.WINDOW_L) >> 7) - 1, 5); self.assertEqual(((CAMX + S.WINDOW_R) >> 7) + 1, 14)

    def test_no_hook_writes_the_x_flag(self):
        text = S.ASM.read_text()
        writers = re.findall(r"^\s+(add\w*|sub\w*|neg\w*|asl\S*|asr\S*|lsl\S*|lsr\S*|rox\S*|abcd|sbcd|nbcd|move\S*\s+\S+,\s*ccr|move\S*\s+\S+,\s*sr)\b", text, flags=re.M)
        self.assertEqual(writers, [], "an instruction that writes X (or the whole CCR/SR) in a hook; X would no longer be preserved for the original continuation")

    # ---- initialization and level reset --------------------------------------------------------------------------------------------------------------------
    def test_cold_start_initializes_before_any_use(self):
        garbage = state(key=0x1234, slots=[(10, 3, 7), (11, 3, 9), (12, 3, 5), (13, 3, 24)], fail=1, retrying=1)
        o = self.run_hook("frame", ram=seed(garbage))
        self.assertEqual(o["state"], state(), "the ring is cleared and armed before the vertical loader and before any retry")
        self.assertEqual(paths(o), {"vert": 1, "tail": 1}); self.assertEqual(o["pc"], S.STUB_RTS["streamer_tail"] + 16)
        # ... and the clearing happened BEFORE the original vertical loader ran (the stub snapshots the key at its entry)
        self.assertEqual(struct.unpack(">H", o["log"][0x30:0x32])[0], KEY)

    def test_level_reset_clears_all_four_and_continues_into_the_original(self):
        full = state(slots=[(10, 3, 24), (11, 3, 12), (12, 3, 5), (13, 3, 1)], fail=1, retrying=1)
        for sr in (SR_USER, SR_USER | X):
            ram = seed(full); o = self.run_hook("reset", ram=ram, sr=sr)
            self.assertEqual(o["state"], state()); self.assertEqual(paths(o), {"level": 1}); self.assertEqual(o["pc"], S.STUB_RTS["level_init"] + 16)
            self.assertEqual(o["ccr"] & X, sr & X, "X is preserved"); self.assert_same_ram_and_registers(o, self.baseline(ram, sr=sr))

    # ---- frame hook ------------------------------------------------------------------------------------------------------------------------------------------
    def test_frame_hook_registers_stack_ram_and_x(self):
        for st in (state(), state(slots=[(10, 3, 24)])):
            for sr in (SR_USER, SR_USER | X, SR_USER | N | C):
                ram = seed(st); o = self.run_hook("frame", ram=ram, sr=sr)
                self.assertEqual(o["a6"], 0xFFFFFA80, "a6 is set exactly as the original LEA did")
                if "calls" not in paths(o):     # when the original loader runs (a retry) it sets the CCR itself: the stub's ADDQ writes X, as the real loader's arithmetic does
                    self.assertEqual(o["ccr"] & X, sr & X, "X is preserved")
                self.assertEqual(o["pc"], S.STUB_RTS["streamer_tail"] + 16)
                self.assertEqual(o["a7"], SP0); self.assertEqual(o["hash"], self.baseline(ram, sr=sr)["hash"])
                for k, v in REGS.items():
                    if k != "a6": self.assertEqual(o[k], v, k)

    def test_the_hook_does_not_preserve_x_across_extra_loader_calls_so_x_must_be_dead_at_the_continuation(self):
        # The synthetic loader DELIBERATELY changes X on every call (EORI #$10,CCR, then its counter ADDQ rewrites X from the carry), exactly as the real loader's ADD.W/ADD.W D3,D3 do. Injected code cannot read X (the product assembler
        # has no ADDX/ROXL and forbids SR access), so the hook neither saves nor restores it: after a retry X is whatever the last extra loader call left. This test PINS that fact (and thereby the assumption): if X were live at the original
        # continuation (streamer tail 0x6d53c, whose first instruction MOVE.W 4(A6),D0 rewrites N/Z/V/C but not X, returning into the per-frame update at 0x9808) the retry would change guest behaviour. README: X was forced to 0 and to 1 right before
        # that continuation in the real image over 3,002 scrolling frames and the complete machine digest of every frame was identical, so X is dead there on every executed path.
        for sr in (SR_USER | X, SR_USER):
            o = self.run_hook("frame", ram=seed(state(slots=[(10, 3, 24)])), sr=sr)
            self.assertEqual(paths(o).get("calls"), 1)
            self.assertEqual(o["ccr"] & X, 0, "after the loader's last ADDQ X is the carry of that addition (0): the entry X is NOT preserved")
        o = self.run_hook("frame", ram=seed(state()), sr=SR_USER | X)
        self.assertEqual(o["ccr"] & X, X, "with nothing queued the hook runs no extra loader call and X is exactly the original vertical loader's")

    def test_retry_success_rebuilds_the_loader_arguments_and_clears_the_slot(self):
        o = self.run_hook("frame", ram=seed(state(slots=[(10, 3, 24), (11, 3, 5)])))
        self.assertEqual(paths(o), {"calls": 2, "vert": 1, "tail": 1})      # both slots are served in one invocation (no starvation); the original loader ran twice
        self.assertEqual([s[2] for s in slots_of(o)[:2]], [0, 0])
        log = o["log"]; self.assertEqual(struct.unpack(">HH", log[4:8]), (11, 3))
        self.assertEqual(struct.unpack(">I", log[8:12])[0], 0xFFFFCA40); self.assertEqual(struct.unpack(">I", log[12:16])[0], 0xFFFFCA02)

    def test_retry_failure_keeps_the_slot_and_ages_it(self):
        o = self.run_hook("frame", ram=seed(state(slots=[(10, 3, 24)]), knob=1))
        self.assertEqual(slots_of(o)[0], (10, 3, 23)); self.assertEqual(paths(o)["calls"], 1)

    def test_expiry_after_the_last_attempt(self):
        o = self.run_hook("frame", ram=seed(state(slots=[(10, 3, 1)]), knob=1))
        self.assertEqual(slots_of(o)[0][2], 0); self.assertEqual(paths(o)["calls"], 1)

    def test_invalid_slot_is_dropped_without_a_load(self):
        for c, r in ((40, 3), (10, 30), (2, 3), (0, 3), (6, 3 - 5)):
            if r < 0: continue
            o = self.run_hook("frame", ram=seed(state(slots=[(c, r, 24)])))
            self.assertEqual(slots_of(o)[0][2], 0, (c, r)); self.assertNotIn("calls", paths(o), (c, r))

    def test_window_edges(self):
        # kept: columns 5..14, rows 0..7 for CAMX=0x400, CAMY=0x100; dropped just outside
        for (c, r), keep in (((5, 0), True), ((4, 0), False), ((14, 7), True), ((15, 7), False), ((10, 8), False), ((10, 7), True)):
            o = self.run_hook("frame", ram=seed(state(slots=[(c, r, 24)])))
            self.assertEqual("calls" in paths(o), keep, (c, r))

    # ---- fail hook -------------------------------------------------------------------------------------------------------------------------------------------
    def test_enqueue_continuation_registers_and_flags(self):
        for word, nz in ((0x8001, N), (0x0001, 0)):
            for sr in (SR_USER, SR_USER | X, SR_USER | N | Z | V | C):
                ram = seed(state(tmp=(10, 3)), extra={0xD000: w(word)}); o = self.run_hook("fail", {"d6": 0}, ram, sr)
                self.assertEqual(slots_of(o)[0], (10, 3, 24)); self.assertEqual(o["state"][8], 1)
                self.assertEqual(paths(o), {"next": 1}); self.assertEqual(o["pc"], S.STUB_RTS["next_entry"] + 16)
                self.assertEqual(o["d6"] & 0xFFFF, 0xFFFF, "the original DBF ran to -1 (scan exhausted)")
                self.assertEqual(o["ccr"], (sr & X) | nz, "the CCR equals the one the original path had: the last TST of the scan (Z=0, V=0, C=0, N from the slot word); X untouched")
                self.assert_same_ram_and_registers(o, self.baseline(ram, {"d6": 0}, sr), keep=("d6",))

    def test_scan_continues_while_slots_remain(self):
        ram = seed(state(tmp=(10, 3))); o = self.run_hook("fail", {"d6": 3}, ram, SR_USER | X | Z)
        self.assertEqual(paths(o), {"scan": 1}); self.assertEqual(o["state"], state(tmp=(10, 3))); self.assertEqual(o["ccr"], X | Z, "the original DBF does not touch the CCR")

    def test_dedup(self):
        o = self.run_hook("fail", {"d6": 0}, seed(state(tmp=(10, 3), slots=[(10, 3, 9)], fail=0)))
        self.assertEqual(slots_of(o), [(10, 3, 9), (0, 0, 0), (0, 0, 0), (0, 0, 0)]); self.assertEqual(paths(o), {"next": 1})

    def test_same_column_other_row_is_a_different_section(self):
        o = self.run_hook("fail", {"d6": 0}, seed(state(tmp=(10, 4), slots=[(10, 3, 9)])))
        self.assertEqual(slots_of(o)[:2], [(10, 3, 9), (10, 4, 24)])

    def test_distinct_section_takes_the_next_slot(self):
        o = self.run_hook("fail", {"d6": 0}, seed(state(tmp=(11, 3), slots=[(10, 3, 9)])))
        self.assertEqual(slots_of(o)[:2], [(10, 3, 9), (11, 3, 24)])

    def test_queue_full_drops_the_fifth_without_touching_the_four(self):
        full = [(10, 3, 9), (11, 3, 8), (12, 3, 7), (13, 3, 6)]
        o = self.run_hook("fail", {"d6": 0}, seed(state(tmp=(14, 3), slots=full)))
        self.assertEqual(slots_of(o), full); self.assertEqual(o["state"][8], 1); self.assertEqual(paths(o), {"next": 1})

    def test_no_enqueue_while_retrying_or_with_a_bad_key(self):
        o = self.run_hook("fail", {"d6": 0}, seed(state(tmp=(10, 3), retrying=1)))
        self.assertEqual(slots_of(o)[0], (0, 0, 0)); self.assertEqual(o["state"][8], 1)
        o = self.run_hook("fail", {"d6": 0}, seed(state(key=0, tmp=(10, 3))))
        self.assertEqual(slots_of(o)[0], (0, 0, 0)); self.assertEqual(paths(o), {"next": 1})

    # ---- entry hook ------------------------------------------------------------------------------------------------------------------------------------------
    def test_entry_hook_records_the_call_and_reproduces_the_displaced_instructions(self):
        regs = {"d2": 0x0000000A, "d5": 0x00000003, "d7": 0x12345678, "a2": 0x0000CA40}
        ram = seed(state()); o = self.run_hook("entry", regs, ram)
        self.assertEqual(o["state"][0:4], w(10) + w(3), "the (column,row) of the call in progress")
        self.assertEqual(paths(o), {"calls": 1})                            # the original loader body ran once
        log = o["log"]; self.assertEqual(struct.unpack(">HH", log[4:8]), (10, 3)); self.assertEqual(struct.unpack(">I", log[8:12])[0], 0xCA40)
        self.assertEqual(o["d3"], 0, "the displaced MOVEQ #0,D3 ran"); self.assertEqual(o["a7"], SP0)

    # ---- left deletion ---------------------------------------------------------------------------------------------------------------------------------------
    def test_left_cull_still_deletes_a_dead_slot_left_of_the_camera(self):
        # the builder runs over a stale draw list at a level change; a freed slot (type word 0) left of the camera was removed by the original unsigned test (a1 would be 0 -> odd-address crash)
        for typ, deleted in ((0x0000, True), (0x0083, False)):
            ram = seed(state(), extra={0xD0C0: w(typ)}); o = self.run_hook("cull", {"d4": 0xFF38, "a0": 0xFFFFD0C0}, ram)
            self.assertEqual(paths(o), {"cull_delete": 1} if deleted else {"cull_continue": 1}, hex(typ))
        ram = seed(state(), extra={0xD0C0: w(0)}); o = self.run_hook("cull", {"d4": 0x0080, "a0": 0xFFFFD0C0}, ram)
        self.assertEqual(paths(o), {"cull_continue": 1}, "right of the camera the original behavior is unchanged (no type test)")

    def test_left_cull_is_signed_and_moves_both_limits(self):
        # d4 = screen x + 128. The original unsigned CMPI #$280/BCC deleted EVERY object left of the camera.
        for d4, deleted in ((0x0005, False), (0x0000, False), (0xFFFF, False), (0x10000 - S.CULL_LEFT, False), (0x10000 - S.CULL_LEFT - 1, True), (0x8000, True),
                            (S.CULL_RIGHT - 1, False), (S.CULL_RIGHT, True), (0x7000, True)):
            for sr in (SR_USER, SR_USER | X):
                ram = seed(state(), extra={0xD000: w(0x0083)}); o = self.run_hook("cull", {"d4": d4, "a0": 0xFFFFD000}, ram, sr)
                self.assertEqual(paths(o), {"cull_delete": 1} if deleted else {"cull_continue": 1}, hex(d4))
                self.assertEqual(o["pc"], S.STUB_RTS["cull_delete" if deleted else "cull_continue"] + 16)
                self.assertEqual(o["ccr"] & X, sr & X, "X preserved"); self.assertEqual(o["d4"], d4, "d4 is not modified (the later sprite code reads it)")
                self.assert_same_ram_and_registers(o, self.baseline(ram, {"d4": d4, "a0": 0xFFFFD000}, sr), keep=("d4", "a0"))


if __name__ == "__main__":
    unittest.main()
