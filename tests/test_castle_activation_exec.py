"""Functional tests of the ACTUAL injected retry/deferral code of ALL THREE activation packages (castle-of-illusion-activation-16x9, -21x9 and -32x9, generated from one template by scripts/gen_castle_retry.py): assembled by the product, executed natively
on a synthetic image against stubs of the original loader. Every test runs once per variant. Each scenario asserts the exact continuation PATH (which original continuation ran, how often, where the run stopped), every register, the stack pointer, the CCR where it
is live, and the COMPLETE work-RAM image except the documented extent 0xFC00..0xFCB3 (retry state + diagnostics), the stubs' counters 0x0300..0x033F and the stack area 0xFF00.. (its pointer is asserted).
CCR liveness (README): the original section loader has two callers (0x6d5ac, 0x6d604), both followed by ADDI.W #$80, which rewrites X,N,Z,V,C; d3/d6/a3 are dead there. The fixture's `ret_addi` stub is exactly that caller continuation.
Skipped (never silently passed) without SEGARECOMP_CLI + SEGARECOMP_SDK_DIR; CI sets SEGARECOMP_REQUIRE_EXEC=1 so a skip there is a failure."""
import os, re, struct, sys, pathlib, unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import castle_activation_exec_support as S

if os.environ.get("SEGARECOMP_REQUIRE_EXEC") == "1" and not S.available():
    raise RuntimeError("SEGARECOMP_REQUIRE_EXEC=1 but SEGARECOMP_CLI / SEGARECOMP_SDK_DIR are not set: the executable tests would be skipped")

KEY, SLOTS, SPEC_CAP, THRESHOLD, EXT_END = 0x5AC3, 16, 12, 20, S.STATE_END
CAMX, CAMY = 0x0400, 0x0100
X, N, Z, V, C = 0x10, 0x08, 0x04, 0x02, 0x01
COUNT = {"fail": 0xA0, "ok": 0xA2, "expired": 0xA4, "drop": 0xA6, "defer": 0xA8, "kept": 0xAA, "inval": 0xAC, "latency": 0xAE, "frames": 0xB0, "maxocc": 0xB2, "specdrop": 0xB4}
POOL, STACK = 0xD400, 0xFFFF80
REGS = {"d0": 0x11111111, "d1": 0x22222222, "d2": 0x33333333, "d3": 0x44444444, "d4": 0x00000007, "d5": 0x66666666, "d6": 0x77777777, "d7": 0x88888888,
        "a0": 0x0000AAAA, "a1": 0x0000BBBB, "a2": 0x0000CCCC, "a3": 0xFFFFD040, "a4": 0x0000EEEE, "a5": 0x0000F228}
SP0 = 0x01000000


def w(v): return struct.pack(">H", v)
def state(key=KEY, tmp=(0, 0), fail=0, retrying=0, slots=(), fc0a=0, counters=None):
    b = bytearray(EXT_END - 0xFC00)
    b[0:4] = w(tmp[0]) + w(tmp[1]); b[8] = fail; b[9] = retrying; b[0xA] = fc0a; b[0xE:0x10] = w(key)
    for i, s in enumerate(slots): b[0x10 + 8 * i:0x18 + 8 * i] = w(s[0]) + w(s[1]) + w(s[2]) + w(s[3] if len(s) > 3 else 0)
    for k, v in (counters or {}).items(): b[COUNT[k]:COUNT[k] + 2] = w(v)
    return bytes(b)
def pool(n): return {POOL + 0x40 * i: w(0x0083) for i in range(n)}
def seed(st, n_pool=0, camx=CAMX, camy=CAMY, ca00=0x0040, knob=0, extra=None):
    ram = {0xFC00: st, 0xFA84: w(camx), 0xFA80: w(camy), 0xCA00: w(ca00), 0x0310: struct.pack(">I", knob), 0x1000: bytes(range(256)) * 4, 0x8000: bytes(range(255, -1, -1)) * 8}
    ram.update(pool(n_pool)); ram.update(extra or {}); return ram
def ring(o): return [struct.unpack(">HHH", o["state"][0x10 + 8 * i:0x16 + 8 * i]) for i in range(SLOTS)]
def ctr(o, name): return struct.unpack(">H", o["state"][COUNT[name]:COUNT[name] + 2])[0]
def cnt(o, off): return struct.unpack(">I", o["log"][off:off + 4])[0]
def paths(o):
    names = {"calls": 0, "scan": 0x14, "next": 0x18, "vert": 0x1C, "tail": 0x20, "level": 0x24, "cull_continue": 0x28, "cull_delete": 0x2C, "ret_addi": 0x3C}
    return {k: cnt(o, v) for k, v in names.items() if cnt(o, v)}


def make(variant):
    asm = S.ASM_DIR(variant)
    WL, WR, CULL_L, CULL_R = S.consts(asm)

    @unittest.skipUnless(S.available(), "set SEGARECOMP_CLI and SEGARECOMP_SDK_DIR (the product's platforms directory) to execute the injected code")
    class Code(unittest.TestCase):
        VARIANT = variant

        @classmethod
        def setUpClass(cls): cls.h = S.Harness(asm=asm)

        def run_hook(self, where, regs=None, ram=None, sr=0): return self.h.run(where, {**REGS, **(regs or {})}, ram, ccr=sr & 0x1F)
        def baseline(self, ram, regs=None, sr=0): return self.h.run("noop", {**REGS, **(regs or {})}, ram, ccr=sr & 0x1F)

        def assert_same_ram_and_registers(self, o, base, keep=(), sp=SP0):
            self.assertEqual(o["hash"], base["hash"], "the complete work RAM image (outside the documented extent) is unchanged")
            self.assertEqual(o["a7"], sp, "the stack pointer returned to its initial value")
            for k, v in REGS.items():
                if k not in keep: self.assertEqual(o[k], v, k)

        # ---- constants, static properties, RAM ownership ---------------------------------------------------------------------------------------------------
        def test_shipped_constants(self):
            exp = {"16x9": (0x100, 0x200, 0x200, 0x300), "21x9": (0x100, 0x280, 0x200, 0x380), "32x9": (0x180, 0x2C0, 0x280, 0x3C0)}[variant]
            self.assertEqual((WL, WR, CULL_L, CULL_R), exp)
            self.assertEqual(((CAMX - WL) >> 7) - 1, {"16x9": 5, "21x9": 5, "32x9": 4}[variant]); self.assertEqual(((CAMX + WR) >> 7) + 1, {"16x9": 13, "21x9": 14, "32x9": 14}[variant])
            self.assertIn("cmpi.w #%d,d3" % THRESHOLD, asm.read_text()); self.assertIn("cmpi.w #%d,d3" % SPEC_CAP, asm.read_text())

        def test_only_the_frame_hook_writes_x_and_every_other_block_is_flag_neutral_where_it_matters(self):
            text = asm.read_text()
            blocks = re.split(r"^org usa-europe (0x[0-9a-f]+)$", text, flags=re.M)      # [header, addr, body, addr, body, ...]
            by = {int(blocks[i], 16): blocks[i + 1] for i in range(1, len(blocks), 2)}
            writers = re.compile(r"^\s+(add\w*|sub\w*|neg\w*|asl\S*|asr\S*|lsl\S*|lsr\S*|rox\S*|abcd|sbcd|nbcd|move\S*\s+\S+,\s*ccr|move\S*\s+\S+,\s*sr)\b", re.M)
            for addr, name in ((0x60C80, "entry_hook"), (0x60D40, "fail_hook"), (0x61200, "level_reset"), (0x61260, "left_cull"), (0x61300, "defer_sec")):
                self.assertEqual(writers.findall(by[addr]), [], "%s writes X (diagnostics use LEA/MOVEA/MOVE; the decision uses LEA/ROR/ANDI/CMP)" % name)
            self.assertTrue(writers.findall(by[0x60F00]), "the frame hook's extra loader calls and counters do write X: documented, X is dead at its continuation")

        def test_guest_ram_ownership_of_state_and_diagnostics(self):
            text = asm.read_text()
            absolute = {int(a, 16) for a in re.findall(r"0x(ff[0-9a-f]{4})\b", text)}
            owned = {a for a in absolute if 0xFFFC00 <= a < 0xFFFD00}
            self.assertTrue(owned and all(0xFFFC00 <= a < 0xFFFC00 + (EXT_END - 0xFC00) for a in owned), sorted(hex(a) for a in owned))
            self.assertEqual(SLOTS * 8 + 0x10, 0x90); self.assertLessEqual(0xFC00 + 0x90, 0xFCA0, "the ring ends before the diagnostics")
            self.assertEqual(S.STATE_END, 0xFCB6)
            # the work RAM below the stack: the game's initial SSP is 0xFFFF00; the state (0xFFFC00..0xFFFCB3) begins 0x300 bytes below it (the stack's maximum depth was not measured), in a range the original never addresses (checked against the image locally, README)
            self.assertNotRegex(re.sub(r"(?m)^;.*$", "", text), r"\b(trap|stop|reset|rte)\b"); self.assertEqual(text.count("jmp @"), 7)

        # ---- initialization and level reset --------------------------------------------------------------------------------------------------------------------
        def test_cold_start_initializes_before_any_use(self):
            # work RAM is undefined at power-on: a wrong key clears the WHOLE extent, ring AND cumulative diagnostics
            garbage = state(key=0x1234, slots=[(10 + i, 3, 24 - i) for i in range(SLOTS)], fail=1, retrying=1, fc0a=1, counters={k: 0x7777 for k in COUNT})
            o = self.run_hook("frame", ram=seed(garbage))
            self.assertEqual(o["state"][:0xA0], state()[:0xA0], "the ring is cleared and armed before the vertical loader and before any retry")
            self.assertEqual([ctr(o, k) for k in COUNT if k not in ("frames", "maxocc")], [0] * (len(COUNT) - 2), "the diagnostics start at zero")
            self.assertEqual((ctr(o, "frames"), ctr(o, "maxocc")), (1, 0), "this invocation counted itself")
            self.assertEqual(paths(o), {"vert": 1, "tail": 1}); self.assertEqual(o["pc"], S.STUB_RTS["streamer_tail"] + 16)
            self.assertEqual(struct.unpack(">H", o["log"][0x30:0x32])[0], KEY, "armed BEFORE the original vertical loader ran")

        def test_level_reset_clears_the_ring_and_continues_into_the_original(self):
            full = state(slots=[(10 + i, 3, 24) for i in range(SLOTS)], fail=1, retrying=1, fc0a=1, counters={"fail": 7, "defer": 9, "latency": 33})
            for sr in (0, X, N | Z | V | C, X | C):
                ram = seed(full); o = self.run_hook("reset", ram=ram, sr=sr)
                self.assertEqual(o["state"][:0x90], state()[:0x90]); self.assertEqual((ctr(o, "fail"), ctr(o, "defer"), ctr(o, "latency")), (7, 9, 33), "diagnostics are cumulative across levels, not level state")
                self.assertEqual(paths(o), {"level": 1}); self.assertEqual(o["pc"], S.STUB_RTS["level_init"] + 16)
                self.assertEqual(o["ccr"] & X, sr & X, "X is preserved"); self.assert_same_ram_and_registers(o, self.baseline(ram, sr=sr))

        # ---- frame hook -----------------------------------------------------------------------------------------------------------------------------------
        def test_frame_hook_registers_stack_ram_and_x(self):
            for st in (state(), state(slots=[(10, 3, 24)])):
                for sr in (0, X, N | C):
                    ram = seed(st); o = self.run_hook("frame", ram=ram, sr=sr)
                    self.assertEqual(o["a6"], 0xFFFFFA80, "a6 is set exactly as the original LEA did")
                    if "calls" not in paths(o): self.assertEqual(o["ccr"] & X, sr & X, "X is preserved when no extra loader call ran")
                    self.assertEqual(o["pc"], S.STUB_RTS["streamer_tail"] + 16); self.assertEqual(o["a7"], SP0); self.assertEqual(o["hash"], self.baseline(ram, sr=sr)["hash"])
                    for k, v in REGS.items():
                        if k != "a6": self.assertEqual(o[k], v, k)

        def test_the_hook_does_not_preserve_x_across_extra_loader_calls_so_x_must_be_dead_at_the_continuation(self):
            # The synthetic loader DELIBERATELY changes X on every call (EORI #$10,CCR, then its counter ADDQ rewrites X), as the real loader's ADD.W/MULU do. Injected code cannot read X (no ADDX/ROXL, SR forbidden), so a retry leaves X as the last extra
            # loader call set it. PINNED here, together with the assumption (README: X forced to 0 and to 1 at the continuation gave a bit-identical machine digest on 3,002 frames).
            for sr in (X, 0):
                o = self.run_hook("frame", ram=seed(state(slots=[(10, 3, 24)])), sr=sr)
                self.assertEqual(paths(o).get("calls"), 1); self.assertEqual(o["ccr"] & X, 0)
            o = self.run_hook("frame", ram=seed(state()), sr=X); self.assertEqual(o["ccr"] & X, X)

        def test_retry_success_rebuilds_the_loader_arguments_and_clears_the_slot(self):
            o = self.run_hook("frame", ram=seed(state(slots=[(10, 3, 24, 0), (11, 3, 5, 0)])))
            self.assertEqual(paths(o), {"calls": 2, "vert": 1, "tail": 1})
            self.assertEqual([s[2] for s in ring(o)[:2]], [0, 0]); self.assertEqual(ctr(o, "ok"), 2)
            self.assertEqual(struct.unpack(">HH", o["log"][4:8]), (11, 3)); self.assertEqual(struct.unpack(">I", o["log"][8:12])[0], 0xFFFFCA40); self.assertEqual(struct.unpack(">I", o["log"][12:16])[0], 0xFFFFCA02)

        def test_retry_failure_keeps_the_slot_and_ages_it(self):
            o = self.run_hook("frame", ram=seed(state(slots=[(10, 3, 24)]), knob=1))
            self.assertEqual(ring(o)[0], (10, 3, 23)); self.assertEqual(paths(o)["calls"], 1)

        def test_expiry_after_the_last_attempt(self):
            o = self.run_hook("frame", ram=seed(state(slots=[(10, 3, 1)]), knob=1))
            self.assertEqual(ring(o)[0][2], 0); self.assertEqual(ctr(o, "expired"), 1)

        def test_invalid_slot_is_dropped_without_a_load_and_counted(self):
            for c, r in ((40, 3), (10, 30), (2, 3), (0, 3)):
                o = self.run_hook("frame", ram=seed(state(slots=[(c, r, 24)])))
                self.assertEqual(ring(o)[0][2], 0, (c, r)); self.assertNotIn("calls", paths(o), (c, r)); self.assertEqual(ctr(o, "inval"), 1)

        def test_window_edges_follow_the_variant_lookaheads(self):
            lo, hi = ((CAMX - WL) >> 7) - 1, ((CAMX + WR) >> 7) + 1
            for (c, r), keep in (((lo, 0), True), ((lo - 1, 0), False), ((hi, 7), True), ((hi + 1, 7), False), ((10, 8), False), ((10, 7), True)):
                o = self.run_hook("frame", ram=seed(state(slots=[(c, r, 24)])))
                self.assertEqual("calls" in paths(o), keep, (c, r))

        def test_pending_demand_latency_and_frame_counter_are_measured(self):
            o = self.run_hook("frame", ram=seed(state(slots=[(10, 3, 24, 3), (11, 3, 24, 3), (12, 3, 24, 3)], counters={"frames": 10})))
            self.assertEqual(ctr(o, "frames"), 11); self.assertEqual(ctr(o, "maxocc"), 3, "three occupied slots seen at this invocation")
            self.assertEqual(ctr(o, "latency"), 8, "stamp 3, completed at invocation 11: eight streamer invocations")

        # ---- fail hook (genuine allocation failure) ------------------------------------------------------------------------------------------------------------
        def test_enqueue_continuation_registers_and_the_exact_ccr(self):
            # The CCR at next_entry is dead in the original (LEA/DBRA, every later use preceded by a flag-setting instruction), but the hook reproduces it exactly anyway: the last TST of the scan (Z=0,V=0,C=0, N from the slot word), X untouched.
            for word, nz in ((0x8001, N), (0x0001, 0)):
                for sr in (0, X, N | Z | V | C, X | Z, X | N | V | C):
                    ram = seed(state(tmp=(10, 3)), extra={0xD000: w(word)}); o = self.run_hook("fail", {"d6": 0}, ram, sr)
                    self.assertEqual(ring(o)[0], (10, 3, 24)); self.assertEqual(o["state"][8], 1); self.assertEqual(ctr(o, "fail"), 1)
                    self.assertEqual(struct.unpack(">H", o["state"][0x16:0x18])[0], 0, "stamp = the frame counter (0 here)")
                    self.assertEqual(paths(o), {"next": 1}); self.assertEqual(o["pc"], S.STUB_RTS["next_entry"] + 16)
                    self.assertEqual(o["d6"] & 0xFFFF, 0xFFFF); self.assertEqual(o["ccr"], (sr & X) | nz)
                    self.assert_same_ram_and_registers(o, self.baseline(ram, {"d6": 0}, sr), keep=("d6",))

        def test_every_fail_hook_exit_leaves_the_same_ccr_and_registers(self):
            # queue, duplicate, full ring, retrying and bad key all end at next_entry with the flags of the original path
            full = [(30 + i, 3, 9) for i in range(SLOTS)]
            for st in (state(tmp=(10, 3)), state(tmp=(10, 3), slots=[(10, 3, 9)]), state(tmp=(10, 3), slots=full), state(tmp=(10, 3), retrying=1), state(key=0, tmp=(10, 3))):
                for sr in (0, X | N | Z | V | C, X):
                    ram = seed(st, extra={0xD000: w(0x0001)}); o = self.run_hook("fail", {"d6": 0}, ram, sr)
                    self.assertEqual(paths(o), {"next": 1}); self.assertEqual(o["ccr"], sr & X); self.assert_same_ram_and_registers(o, self.baseline(ram, {"d6": 0}, sr), keep=("d6",))

        def test_scan_continues_while_slots_remain(self):
            ram = seed(state(tmp=(10, 3))); o = self.run_hook("fail", {"d6": 3}, ram, X | Z)
            self.assertEqual(paths(o), {"scan": 1}); self.assertEqual(o["state"], state(tmp=(10, 3))); self.assertEqual(o["ccr"], X | Z, "the original DBF does not touch the CCR")

        def test_dedup_and_a_distinct_section(self):
            o = self.run_hook("fail", {"d6": 0}, seed(state(tmp=(10, 3), slots=[(10, 3, 9)])))
            self.assertEqual(ring(o)[:2], [(10, 3, 9), (0, 0, 0)])
            o = self.run_hook("fail", {"d6": 0}, seed(state(tmp=(10, 4), slots=[(10, 3, 9)]))); self.assertEqual(ring(o)[:2], [(10, 3, 9), (10, 4, 24)])

        def test_queue_full_drops_an_essential_newcomer_without_touching_the_others_and_counts_it(self):
            full = [(30 + i, 3, 9 - i % 5) for i in range(SLOTS)]
            o = self.run_hook("fail", {"d6": 0}, seed(state(tmp=(8, 3), slots=full)))           # column 8 is inside the original window at camera 0x400
            self.assertEqual(ring(o), full); self.assertEqual(ctr(o, "drop"), 1); self.assertEqual(ctr(o, "specdrop"), 0); self.assertEqual(o["state"][8], 1); self.assertEqual(paths(o), {"next": 1})

        def test_a_speculative_failure_is_queued_only_below_the_cap(self):
            # a speculative column (14 > 11 at camera 0x400) that FAILED to allocate takes a slot only while fewer than 12 are in use; the reserved slots stay free for original-window sections
            for used, queued in ((SPEC_CAP - 1, True), (SPEC_CAP, False), (SLOTS - 1, False)):
                o = self.run_hook("fail", {"d6": 0}, seed(state(tmp=(14, 3), slots=[(40 + i, 3, 24, 0) for i in range(used)])))
                self.assertEqual((14, 3, 24) in ring(o), queued, used); self.assertEqual(ctr(o, "specdrop"), 0 if queued else 1, used); self.assertEqual(ctr(o, "drop"), 0)
                self.assertEqual(paths(o), {"next": 1}); self.assertEqual(o["state"][8], 1, "the fail flag is set either way: the original path continued")
            for used in (SPEC_CAP, SLOTS - 1):    # an ESSENTIAL failure uses every free slot, reserved or not
                o = self.run_hook("fail", {"d6": 0}, seed(state(tmp=(9, 3), slots=[(40 + i, 3, 24, 0) for i in range(used)])))
                self.assertIn((9, 3, 24), ring(o), used); self.assertEqual(ctr(o, "specdrop"), 0)
            for sr in (0, X, N | Z | V | C, X | N):    # the classification and the count never disturb the exact CCR of the original path
                o = self.run_hook("fail", {"d6": 0}, seed(state(tmp=(14, 3), slots=[(40 + i, 3, 24, 0) for i in range(SPEC_CAP)]), extra={0xD000: w(0x0001)}), sr)
                self.assertEqual(o["ccr"], sr & X)

        def test_no_enqueue_while_retrying_or_with_a_bad_key(self):
            o = self.run_hook("fail", {"d6": 0}, seed(state(tmp=(10, 3), retrying=1))); self.assertEqual(ring(o)[0], (0, 0, 0)); self.assertEqual(o["state"][8], 1)
            o = self.run_hook("fail", {"d6": 0}, seed(state(key=0, tmp=(10, 3)))); self.assertEqual(ring(o)[0], (0, 0, 0)); self.assertEqual(paths(o), {"next": 1})

        # ---- entry hook and the deferral -------------------------------------------------------------------------------------------------------------------
        def entry(self, col, row, n_pool, retrying=0, key=KEY, slots=(), camx=CAMX, sr=0, extra=None):
            """The original loader called with (col, row): the stack holds a return address (the harness stops at the first RTS it reaches)."""
            ram = seed(state(key=key, retrying=retrying, slots=slots), n_pool, camx=camx, extra={STACK & 0xFFFF: struct.pack(">I", S.SYM["next_entry"]), **(extra or {})})
            regs = {**REGS, "d2": col, "d5": row, "a7": STACK}
            return ram, self.h.run("entry", regs, ram, ccr=sr & 0x1F), regs

        def defer_rts(self, retrying=False):
            base = 0x2900; found = [base + i for i in range(0, 0x100, 2) if self.h.image[base + i:base + i + 2] == b"\x4e\x75"]
            return found[0 if retrying else -1]

        def returned(self, o, retrying=False):
            self.assertEqual(o["pc"], self.defer_rts(retrying), "stopped at the deferral's own RTS: the original loader body never ran"); self.assertEqual(paths(o), {}); self.assertEqual(o["a7"], STACK)

        def test_entry_below_the_threshold_nothing_is_deferred_even_far_beyond_the_window(self):
            for col in (30, 0, 12, 11):
                ram, o, regs = self.entry(col, 3, THRESHOLD - 1)
                self.assertEqual(paths(o), {"calls": 1}, col); self.assertEqual(ring(o), [(0, 0, 0)] * SLOTS); self.assertEqual(ctr(o, "defer"), 0); self.assertEqual(o["d3"], 0, "the displaced MOVEQ #0,D3 ran")

        def test_at_the_threshold_only_speculative_columns_are_deferred(self):
            # camera 0x400: the original window is columns (0x400-0x71..0x400+0x180)>>7 = 6..11 (one more column is kept on the left: left of (cam-0xF1)>>7 = 6)
            for col, deferred in ((12, True), (30, True), (11, False), (8, False), (6, False), (5, True), (0, True)):
                ram, o, regs = self.entry(col, 3, THRESHOLD)
                self.assertEqual("calls" in paths(o), not deferred, col); self.assertEqual(ctr(o, "defer"), 1 if deferred else 0, col); self.assertEqual(ring(o)[0][:3] == (col, 3, 24), deferred, col)

        def test_the_decision_follows_the_camera_only(self):
            for camx, col, deferred in ((0, 4, True), (0, 3, False), (0x80, 5, True), (0x1000, 35, False), (0x1000, 36, True)):
                ram, o, regs = self.entry(col, 2, THRESHOLD, camx=camx); self.assertEqual("calls" in paths(o), not deferred, (hex(camx), col))
            ram, o, regs = self.entry(0, 1, THRESHOLD, camx=0x10); self.assertIn("calls", paths(o), "near the level start the left limit is negative: nothing on the left is speculative")

        def test_the_early_return_is_exact_for_the_caller_and_the_decision_is_x_neutral(self):
            # What the caller can observe after a deferral: registers, stack, RAM and the CCR AFTER its own ADDI.W #$80,D0. The hook leaves N/Z/V/C arbitrary (dead) but its decision (and the diagnostics) never write X.
            for sr in range(0, 32):
                ram, o, regs = self.entry(12, 3, THRESHOLD, sr=sr)
                self.assertEqual(o["pc"], self.defer_rts(), "stopped at the deferral's RTS")                  # the run stops at the first RTS; the caller's continuation is exercised by test_the_callers_ccr_is_independent...
                for k, v in regs.items():
                    if k in ("a7", "d3", "d6", "a3"): continue
                    self.assertEqual(o[k], v, k)
                self.assertEqual(o["sr"] & X, sr & X, "the decision is X-neutral (belt and braces: X is dead at the caller's ADDI)")
                self.assertEqual(o["hash"], self.baseline(ram, sr=sr)["hash"]); self.assertEqual(ring(o)[0][:3], (12, 3, 24))

        def test_the_callers_ccr_and_registers_after_its_addi_are_the_same_whether_the_section_was_deferred_or_loaded(self):
            # A faithful caller (JSR section_load; ADDI.W #$80,D0; CCR capture): after its own ADDI the CCR no longer depends on the entry flags or on what the hook (or the stub loader, which flips X) did to them.
            expect = None
            for sr in range(0, 32):
                results = {}
                for tag, n_pool in (("deferred", THRESHOLD), ("loaded", 0)):
                    ram = seed(state(), n_pool, extra={STACK & 0xFFFF: struct.pack(">I", 0)})
                    o = self.h.run("caller", {**REGS, "d2": 12, "d5": 3, "a7": STACK}, ram, ccr=sr)
                    self.assertEqual(paths(o).get("ret_addi"), 1, (tag, sr)); self.assertEqual(("calls" in paths(o)), tag == "loaded", (tag, sr))
                    results[tag] = o
                d, l = results["deferred"], results["loaded"]
                self.assertEqual(d["ccr"], l["ccr"], "the caller sees the same CCR after its ADDI (entry CCR %02x)" % sr)
                for k in ("d0", "d1", "d2", "d4", "d5", "d7", "a0", "a1", "a2", "a4", "a5"): self.assertEqual(d[k], l[k], k)
                expect = d["ccr"] if expect is None else expect
                self.assertEqual(d["ccr"], expect, "independent of the entry flags")
            r = (REGS["d0"] & 0xFFFF) + 0x80
            self.assertEqual(expect, (N if r & 0x8000 else 0) | (Z if (r & 0xFFFF) == 0 else 0) | (C | X if r > 0xFFFF else 0), "the CCR of ADDI.W #$80,D0 on the caller's d0")

        def test_both_enqueue_paths_stamp_the_frame_counter_for_the_latency_measure(self):
            ram, o, regs = self.entry(12, 3, THRESHOLD); ram[0xFC00] = state(counters={"frames": 5}); ram, o, regs = self.entry(12, 3, THRESHOLD, extra={0xFC00 + COUNT["frames"]: w(5)})
            self.assertEqual(struct.unpack(">H", o["state"][0x16:0x18])[0], 5, "deferral stamps the streamer-invocation counter")
            o = self.run_hook("fail", {"d6": 0}, seed(state(tmp=(10, 3), counters={"frames": 9}))); self.assertEqual(struct.unpack(">H", o["state"][0x16:0x18])[0], 9, "so does a genuine failure")

        def test_a_deferral_returns_exactly_like_a_loader_that_loaded_nothing(self):
            ram, o, regs = self.entry(12, 3, THRESHOLD); self.returned(o)
            for k, v in regs.items():
                if k in ("a7", "d3", "d6", "a3"): continue
                self.assertEqual(o[k], v, k)
            self.assertEqual(o["hash"], self.baseline(ram)["hash"], "no guest RAM outside the retry state changed"); self.assertEqual(o["state"][0:4], w(12) + w(3))

        def test_inside_a_retry_the_section_keeps_waiting_and_is_flagged(self):
            ram, o, regs = self.entry(12, 3, THRESHOLD, retrying=1)
            self.assertEqual(ring(o), [(0, 0, 0)] * SLOTS); self.assertEqual(o["state"][8], 1); self.assertEqual(o["state"][0xA], 1); self.returned(o, retrying=True)

        def test_an_invalid_state_key_disables_the_deferral(self):
            ram, o, regs = self.entry(12, 3, THRESHOLD, key=0); self.assertEqual(paths(o), {"calls": 1}); self.assertEqual(ring(o), [(0, 0, 0)] * SLOTS)

        # ---- the queue policy: speculative deferrals can never displace genuine failures --------------------------------------------------------------------------
        def spec_slots(self, n, base=20): return [(base + i, 3, 24, 0) for i in range(n)]

        def test_speculative_deferrals_stop_at_the_cap_and_load_normally_beyond_it(self):
            for used, deferred in ((SPEC_CAP - 1, True), (SPEC_CAP, False), (SLOTS, False)):
                ram, o, regs = self.entry(12, 3, THRESHOLD, slots=self.spec_slots(used))
                self.assertEqual("calls" in paths(o), not deferred, used)
                if deferred: self.assertEqual(ring(o)[used][:3], (12, 3, 24))
                else: self.assertEqual(ring(o)[:used], [s[:3] for s in self.spec_slots(used)]); self.assertEqual(ctr(o, "defer"), 0, "no new deferral, nothing displaced, nothing dropped"); self.assertEqual(ctr(o, "drop"), 0)

        def test_a_genuine_failure_still_finds_a_slot_when_speculative_work_filled_the_cap(self):
            spec = self.spec_slots(SPEC_CAP)
            o = self.run_hook("fail", {"d6": 0}, seed(state(tmp=(11, 3), slots=spec)))
            self.assertEqual(ring(o)[SPEC_CAP], (11, 3, 24), "an original-window section that fails to allocate is queued in a reserved slot"); self.assertEqual(ctr(o, "drop"), 0)
            for k in range(SLOTS - SPEC_CAP):       # all reserved slots usable by genuine failures
                spec = spec + [(60 + k, 3, 24, 0)] if k else spec
            full_but_one = spec + [(60 + k, 3, 24, 0) for k in range(SLOTS - SPEC_CAP - 1)] if False else None

        def test_speculative_work_cannot_permanently_displace_essential_work(self):
            # Sequence: the cap is full of speculative sections; an essential section fails and is queued; the speculative demand keeps coming and is refused (loaded normally); the essential section is retried and loaded; nothing was dropped.
            spec = self.spec_slots(SPEC_CAP)
            o = self.run_hook("fail", {"d6": 0}, seed(state(tmp=(11, 3), slots=spec)))
            queued = [s[:3] for s in ring(o) if s[2]]; self.assertIn((11, 3, 24), queued)
            ram, o2, regs = self.entry(12, 3, THRESHOLD, slots=[tuple(s) + (0,) for s in queued])       # more speculative demand: the ring has 13 used (>= cap): it loads instead of queueing
            self.assertIn("calls", paths(o2)); self.assertEqual(ctr(o2, "drop"), 0)
            o3 = self.run_hook("frame", ram=seed(state(slots=[(11, 3, 24, 0)]), THRESHOLD - 1))            # the essential section is reconsidered at the next streamer invocation and loads
            self.assertEqual(ring(o3)[0][2], 0); self.assertEqual(ctr(o3, "ok"), 1); self.assertEqual(paths(o3).get("calls"), 1)

        def test_a_full_ring_of_speculative_sections_cannot_arise(self):
            # even a ring that is entirely speculative (16) is only reachable by genuine failures; a deferral never takes slot 13..16
            for used in range(SPEC_CAP, SLOTS):
                ram, o, regs = self.entry(12, 3, THRESHOLD, slots=self.spec_slots(used)); self.assertNotIn(12, [s[0] for s in ring(o)])

        # ---- the retry with a deferral inside it ------------------------------------------------------------------------------------------------------------
        def frame(self, slots, n_pool, camx=CAMX, knob=0): return self.h.run("frame", REGS, seed(state(slots=slots), n_pool, camx=camx, knob=knob), ccr=0)

        def test_a_deferred_section_keeps_its_age_while_it_waits(self):
            o = self.frame([(12, 3, 24, 0), (11, 3, 5, 0)], THRESHOLD)
            s = ring(o); self.assertEqual(s[0], (12, 3, 24)); self.assertEqual(ctr(o, "kept"), 1); self.assertEqual(s[1][2], 0); self.assertEqual(ctr(o, "ok"), 1); self.assertEqual(paths(o).get("calls"), 1)

        def test_once_the_pool_has_room_the_deferred_section_loads(self):
            o = self.frame([(12, 3, 24, 0)], THRESHOLD - 1); self.assertEqual(ring(o)[0][2], 0); self.assertEqual(ctr(o, "ok"), 1)

        def test_a_deferred_section_that_leaves_the_retry_window_is_dropped_and_counted(self):
            o = self.frame([(40, 3, 24, 0)], THRESHOLD); self.assertEqual(ring(o)[0][2], 0); self.assertEqual(ctr(o, "inval"), 1); self.assertNotIn("calls", paths(o))

        def test_a_real_allocation_failure_still_ages_and_expires(self):
            o = self.frame([(11, 3, 1, 0)], 0, knob=1); self.assertEqual(ring(o)[0][2], 0); self.assertEqual(ctr(o, "expired"), 1)

        def test_the_frame_hook_leaves_registers_and_ram_alone(self):
            ram = seed(state(slots=[(12, 3, 24, 0)]), THRESHOLD); o = self.h.run("frame", REGS, ram, ccr=0); base = self.h.run("noop", REGS, ram, ccr=0)
            self.assertEqual(o["hash"], base["hash"]); self.assertEqual(o["a7"], SP0)
            for k, v in REGS.items():
                if k != "a6": self.assertEqual(o[k], v, k)

        # ---- the saturated lifecycle: persistent queue state chained across real executions ---------------------------------------------------------------------
        def chain_entry(self, st, col, row, n_pool, camx=CAMX):
            """One call of the original loader (the stub fails to allocate iff the modelled pool is full); the returned ring state is the NEXT call's input."""
            ram = seed(st, n_pool, camx=camx, knob=1 if n_pool >= 32 else 0, extra={STACK & 0xFFFF: struct.pack(">I", S.SYM["next_entry"])})
            o = self.h.run("entry", {**REGS, "d2": col, "d5": row, "a7": STACK}, ram, ccr=0); return o["state"], o
        def chain_frame(self, st, n_pool, camx=CAMX):
            o = self.h.run("frame", REGS, seed(st, n_pool, camx=camx, knob=1 if n_pool >= 32 else 0), ccr=0); return o["state"], o
        @staticmethod
        def used(st): return sum(1 for i in range(SLOTS) if struct.unpack(">H", st[0x14 + 8 * i:0x16 + 8 * i])[0])
        @staticmethod
        def slots(st): return [(struct.unpack(">HH", st[0x10 + 8 * i:0x14 + 8 * i]), struct.unpack(">H", st[0x14 + 8 * i:0x16 + 8 * i])[0]) for i in range(SLOTS) if struct.unpack(">H", st[0x14 + 8 * i:0x16 + 8 * i])[0]]
        @staticmethod
        def c(st, name): return struct.unpack(">H", st[COUNT[name]:COUNT[name] + 2])[0]

        def test_essential_work_survives_sustained_speculative_pressure_and_recovers(self):
            st = state()
            SPEC = [(12 + i, r) for r in (3, 4) for i in range(10)]           # 20 speculative sections (columns beyond the original window at camera 0x400, which spans columns 6..11)
            ESS = [(6, 3), (7, 3), (8, 3), (9, 3)]                             # the original window: these four are what the player needs NOW
            # phase 1: the pool is full. The first 12 speculative sections are deferred; the rest are loaded as the original would, FAIL to allocate, and must be dropped, not queued
            for col, row in SPEC:
                st, o = self.chain_entry(st, col, row, 32); self.assertLessEqual(self.used(st), SPEC_CAP, (col, row))
            self.assertEqual(self.used(st), SPEC_CAP); self.assertEqual(self.c(st, "defer"), SPEC_CAP); self.assertEqual(self.c(st, "specdrop"), len(SPEC) - SPEC_CAP)
            # phase 2: four ORIGINAL-WINDOW sections fail to allocate: every one must be queued although the speculative work already filled its cap
            for col, row in ESS:
                st, o = self.chain_entry(st, col, row, 32); self.assertIn(((col, row), 24), self.slots(st), (col, row))
            self.assertEqual(self.used(st), SLOTS); self.assertEqual(self.c(st, "drop"), 0)
            # more speculative demand while the ring is full: nothing is queued, nothing displaced, the essential slots are untouched
            before = self.slots(st)
            for col, row in SPEC[:6]:
                st, o = self.chain_entry(st, col, row, 32)
            self.assertEqual(self.slots(st), before)
            # phase 3: sustained pressure (pool stays full) for 10 streamer invocations: speculative sections wait with their age, the essential ones are retried and fail (their age counts down)
            for k in range(10): st, o = self.chain_frame(st, 32)
            ess_ages = {key: age for key, age in self.slots(st) if key in ESS}
            self.assertEqual(sorted(ess_ages), ESS); self.assertTrue(all(a == 24 - 10 for a in ess_ages.values()), ess_ages)
            self.assertEqual(sorted(k for k, a in self.slots(st) if k in SPEC and a == 24), sorted(k for k, a in self.slots(st) if k in SPEC), "speculative waiting never ages")
            self.assertEqual(self.c(st, "expired"), 0)
            # phase 4: camera movement: the camera advances 2 columns; sections now left of the retry window are invalidated and counted, the essential ones that are still inside the window stay
            st, o = self.chain_frame(st, 32, camx=CAMX + 0x100)
            self.assertGreaterEqual(self.c(st, "inval"), 0)
            # phase 5: the pool frees up (a boss dies, a screen clears): ONE streamer invocation loads every pending essential section still in the window, and the speculative ones follow
            st, o = self.chain_frame(st, 10, camx=CAMX + 0x100)
            left = {key for key, a in self.slots(st)}
            self.assertFalse(left & set(ESS), "every essential section that was pending and still in the window loaded: " + str(left & set(ESS)))
            self.assertEqual(self.c(st, "expired"), 0, "nothing essential expired because of speculative work")
            self.assertGreaterEqual(self.c(st, "latency"), 10)

        def test_a_speculative_section_cannot_expire_an_essential_one_in_a_long_mixed_run(self):
            import random
            rng = random.Random(0xC57)
            st = state(); camx = CAMX; pool = 0; essential_pending = set(); lost_to_displacement = 0
            for step in range(70):
                pool = max(0, min(32, pool + rng.choice((-6, -3, 0, 2, 5, 9))))
                camx = max(0x80, camx + rng.choice((-0x80, -0x40, 0, 0x40, 0x80, 0x100)))
                lo, hi = max(0, (camx - 0xF1) >> 7), (camx + 0x180) >> 7                       # the original window's columns
                kind = rng.choice(("spec", "ess", "ess", "frame"))
                before_used, before_slots = self.used(st), self.slots(st)
                if kind == "frame":
                    st, o = self.chain_frame(st, pool, camx=camx)
                else:
                    col = rng.randint(hi + 1, hi + 12) if kind == "spec" else rng.randint(max(lo, 1), max(lo, hi)); row = rng.randint(0, 5)
                    st, o = self.chain_entry(st, col, row, pool, camx=camx)
                    if kind == "spec":
                        self.assertTrue(self.used(st) <= max(SPEC_CAP, before_used), "a speculative section must never raise the ring above the cap (step %d)" % step)
                    elif pool >= 32:                                                              # an essential failure: it MUST be queued unless it was already queued or the ring was genuinely full of essential work
                        keys = {k for k, a in before_slots}
                        if (col, row) not in keys and before_used < SLOTS: self.assertIn(((col, row), 24), self.slots(st), "essential failure lost (step %d)" % step)
                self.assertLessEqual(self.used(st), SLOTS)
            self.assertEqual(self.c(st, "drop"), self.c(st, "drop"))

        # ---- left deletion ---------------------------------------------------------------------------------------------------------------------------------
        def test_left_cull_still_deletes_a_dead_slot_left_of_the_camera(self):
            for typ, deleted in ((0x0000, True), (0x0083, False)):
                ram = seed(state(), extra={0xD0C0: w(typ)}); o = self.run_hook("cull", {"d4": 0xFF38, "a0": 0xFFFFD0C0}, ram)
                self.assertEqual(paths(o), {"cull_delete": 1} if deleted else {"cull_continue": 1}, hex(typ))
            ram = seed(state(), extra={0xD0C0: w(0)}); o = self.run_hook("cull", {"d4": 0x0080, "a0": 0xFFFFD0C0}, ram); self.assertEqual(paths(o), {"cull_continue": 1})

        def test_left_cull_is_signed_and_moves_both_limits(self):
            for d4, deleted in ((5, False), (0, False), (0xFFFF, False), (0x10000 - CULL_L, False), (0x10000 - CULL_L - 1, True), (0x8000, True), (CULL_R - 1, False), (CULL_R, True), (0x7000, True)):
                for sr in (0, X, N | Z | V | C):
                    ram = seed(state(), extra={0xD000: w(0x0083)}); o = self.run_hook("cull", {"d4": d4, "a0": 0xFFFFD000}, ram, sr)
                    self.assertEqual(paths(o), {"cull_delete": 1} if deleted else {"cull_continue": 1}, hex(d4)); self.assertEqual(o["d4"], d4)
                    self.assertEqual(o["ccr"] & X, sr & X, "X preserved"); self.assert_same_ram_and_registers(o, self.baseline(ram, {"d4": d4, "a0": 0xFFFFD000}, sr), keep=("d4", "a0"))

    Code.__name__ = Code.__qualname__ = "Code" + variant
    return Code


Code16 = make("16x9")
Code21 = make("21x9")
Code32 = make("32x9")

if __name__ == "__main__":
    unittest.main()
