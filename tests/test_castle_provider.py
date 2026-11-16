"""Castle of Illusion provider (SEG-149-T002 / SEG-149-T003): the algorithmic contract on FABRICATED work RAM. No ROM, no game data: the synthetic block tables, maps and scroll records below only have the SHAPE the provider documents.

The provider (patches/genesis/castle-of-illusion/src/provider.c) is compiled against the product's ABI 2 header with a small mock host (declared ranges enforced, writes staged and applied at the end of the callback, the typed render
feature recorded) and driven through its public entry point. The test needs the product's SDK headers and a C compiler: set SEGARECOMP_SDK_DIR (the product's `platforms` directory) and optionally SEGARECOMP_CC; otherwise it is
skipped with that reason, never silently passed. The commercial-game evidence (real frames, aspect matrix, save/replay) is described in the project's README and was produced locally; it cannot run in CI."""
import os, pathlib, subprocess, sys, tempfile, unittest
try: import tomllib
except ImportError: tomllib = None

ROOT = pathlib.Path(__file__).resolve().parent.parent
PROJECT = ROOT / "patches/genesis/castle-of-illusion"
SDK, CC = os.environ.get("SEGARECOMP_SDK_DIR"), os.environ.get("SEGARECOMP_CC", "cc")

HARNESS = r'''
#include <segarecomp_mod_genesis.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
const SegaModProvider *segarecomp_mod_provider(void **state_out);
static uint8_t ram[65536];
typedef struct { uint32_t off, len; int write; } Range;
static Range ranges[32]; static int nranges;
static struct { uint32_t off, w, v; } staged[64]; static int nstaged, fault;
static SegaModHost host; static SegaGenesisFeatures features; static SegaGenesisRenderApi api;
static uint32_t pad1, regs[32];
static int in_range(uint32_t off, uint32_t w, int write) { int i; for (i = 0; i < nranges; ++i) if (off >= ranges[i].off && off + w <= ranges[i].off + ranges[i].len && (!write || ranges[i].write)) return 1; return 0; }
static int mread(uint32_t space, uint32_t off, uint32_t w, uint32_t *v) {
  uint32_t i, x = 0;
  if (space == SEGA_GEN_SPACE_M68K_HOOK_REGS) { if (off >= 32 || w != 4) { fault = 1; return SEGA_MOD_E_RANGE; } *v = regs[off]; return 0; }
  if (space != SEGA_GEN_SPACE_M68K_WORK_RAM || !in_range(off, w, 0)) { fault = 1; return SEGA_MOD_E_RANGE; }
  for (i = 0; i < w; ++i) x = (x << 8) | ram[off + i]; *v = x; return 0; }
static int mwrite(uint32_t space, uint32_t off, uint32_t w, uint32_t v) {
  if (space != SEGA_GEN_SPACE_M68K_WORK_RAM || !in_range(off, w, 1) || nstaged >= 64) { fault = 1; return SEGA_MOD_E_RANGE; }
  staged[nstaged].off = off; staged[nstaged].w = w; staged[nstaged].v = v; ++nstaged; return 0; }
static int minput(uint32_t port, uint32_t *b) { if (port != 1U) return 1; *b = pad1; return 0; }
static int mset(uint32_t port, uint32_t b) { printf("setpad %u %x\n", port, b); return 0; }
static void mlog(const char *s, uint32_t n) { (void)s; (void)n; }
static int a_layer(uint32_t a, uint32_t b, uint32_t c, int32_t d, int32_t e, uint32_t f, uint32_t g, uint32_t h) { (void)a; (void)b; (void)c; (void)d; (void)e; (void)f; (void)g; (void)h; return 0; }
static int a_target(uint32_t i) { (void)i; return 0; }
static int a_rect(int32_t x, int32_t y, int32_t w, int32_t h, uint32_t c) { printf("rect %d %d %d %d\n", x, y, w, h); (void)c; return 0; }
static int a_text(int32_t x, int32_t y, const char *t, uint32_t n, uint32_t c) { printf("text %d %d %.*s\n", x, y, (int)n, t); (void)c; return 0; }
static int a_scene(const char *id, uint32_t n) { printf("scene %.*s\n", (int)n, id); return 0; }
static int a_sprites(const GenesisVirtualSpriteSet *s) {
  uint32_t i; printf("vsprites space %u budget %u count %u\n", s->space, s->budget_mode, s->count);
  for (i = 0; i < s->count; ++i) { const GenesisVirtualSprite *c = &s->sprites[i]; printf("vs %u %u %d %d %u %u %u %u %u %u %u\n", c->provenance, c->layer, c->x, c->y, c->width_cells, c->height_cells, c->tile_index, c->palette, c->h_flip, c->v_flip, c->has_clip); }
  return 0; }
static int a_window(uint32_t plane, int32_t x0, int32_t y0, uint32_t cols, uint32_t rows, const uint16_t *w) {
  uint32_t i; if (cols == 0 || rows == 0 || cols > 128 || rows > 64 || cols * rows > 4096) { printf("BAD-WINDOW\n"); return SEGA_MOD_E_RANGE; }
  printf("window %u %d %d %u %u", plane, x0, y0, cols, rows); for (i = 0; i < cols * rows; ++i) printf(" %04x", w[i]); printf("\n"); return 0; }
static void commit(void) { int i; for (i = 0; i < nstaged; ++i) { uint32_t k; for (k = 0; k < staged[i].w; ++k) ram[staged[i].off + k] = (uint8_t)(staged[i].v >> (8U * (staged[i].w - 1U - k))); printf("write %x %u %x\n", staged[i].off, staged[i].w, staged[i].v); } nstaged = 0; }
int main(int argc, char **argv) {
  const SegaModProvider *p; void *state = NULL; char line[256]; uint64_t frame = 0; uint8_t blob[64]; uint32_t bloblen = 0; (void)argc; (void)argv;
  host.size = sizeof host; host.abi_major = 2; host.platform = SEGA_MOD_PLATFORM; host.platform_features = &features; host.read = mread; host.write = mwrite; host.input_get = minput; host.input_set = mset; host.log = mlog;
  features.size = sizeof features; features.render = &api;
  api.size = sizeof api; api.overlay_layer = a_layer; api.overlay_target = a_target; api.overlay_rect = a_rect; api.overlay_text = a_text; api.scene = a_scene; api.virtual_sprites = a_sprites; api.scenery_window = a_window; api.virtual_sprites = a_sprites;
  p = segarecomp_mod_provider(&state);
  while (fgets(line, sizeof line, stdin)) {
    unsigned a, b, c;
    if (sscanf(line, "range %x %u %u", &a, &b, &c) == 3) { ranges[nranges].off = a; ranges[nranges].len = b; ranges[nranges].write = (int)c; ++nranges; }
    else if (sscanf(line, "ram %x %u %x", &a, &b, &c) == 3) { unsigned k; for (k = 0; k < b; ++k) ram[a + k] = (uint8_t)(c >> (8U * (b - 1U - k))); }
    else if (sscanf(line, "pad %x", &a) == 1) pad1 = a;
    else if (sscanf(line, "frame %u", &a) == 1) frame = a;
    else if (sscanf(line, "reg %u %x", &a, &b) == 2) regs[a] = b;
    else if (strncmp(line, "hook", 4) == 0) { host.frame = frame; host.phase = SEGA_MOD_PHASE_HOOK_ENTRY; fault = 0; printf("hook %d\n", p->hook(state, &host, 0)); if (fault) printf("FAULT\n"); }
    else if (strncmp(line, "init", 4) == 0) printf("init %d\n", p->init(state, &host));
    else if (strncmp(line, "phase ", 6) == 0) {
      host.frame = frame; fault = 0;
      host.phase = strncmp(line + 6, "reset", 5) == 0 ? SEGA_MOD_PHASE_RESET : strncmp(line + 6, "input", 5) == 0 ? SEGA_MOD_PHASE_INPUT : strncmp(line + 6, "post-input", 10) == 0 ? SEGA_MOD_PHASE_POST_INPUT : strncmp(line + 6, "frame-end", 9) == 0 ? SEGA_MOD_PHASE_FRAME_END : SEGA_MOD_PHASE_RENDER;
      p->phase(state, &host); if (fault) printf("FAULT\n"); commit();
    }
    else if (strncmp(line, "save", 4) == 0) { uint32_t i; if (p->save_state(state, blob, sizeof blob, &bloblen) != 0) printf("SAVE-FAILED\n"); else { printf("state"); for (i = 0; i < bloblen; ++i) printf(" %02x", blob[i]); printf("\n"); } }
    else if (strncmp(line, "load", 4) == 0) { char *s = line + 4; uint32_t n = 0; while (*s) { unsigned v; int used; if (sscanf(s, " %2x%n", &v, &used) == 1) { blob[n++] = (uint8_t)v; s += used; } else break; } printf("load %d\n", p->load_state(state, blob, n)); }
    else if (strncmp(line, "echo", 4) == 0) printf("%s", line + 5);
  }
  return 0;
}
'''

# ---- the independent expectation: the documented layout, written separately from the provider ----
REC_A, REC_B, MAP_A, MAP_B, TBL_A, TBL_B = 0xFA80, 0xFAC0, 0x2000, 0x5000, 0x0000, 0x0800
POWER, HUD_SLOTS, HUD_FLAGS, CHORD = 0xF322, 0xF244, 0xF409, 0x70


class Ram:
    """Fabricated work RAM: a block-table, two maps and the two scroll records, with the shape of a running level (never the content of one)."""
    def __init__(self, rows=16, cols=240, brows=16, cam=0, v=32, cam_b=0, v_b=28, bstride=32, bptr=MAP_B):
        self.b = bytearray(65536)
        self.rows, self.cols, self.brows, self.bstride, self.bptr = rows, cols, brows, bstride, bptr
        for blk in range(256):
            for k in range(4): self.w(TBL_A + 8 * blk + 2 * k, 2, (0x4000 + blk * 16 + k) & 0xFFFF)            # synthetic words, one distinct word per (block, cell)
            for k in range(4): self.w(TBL_B + 8 * blk + 2 * k, 2, (0x6000 + blk * 16 + 8 + k) & 0xFFFF)
        for r in range(rows):
            for c in range(cols): self.b[MAP_A + r * cols + c] = (r * 31 + c * 7) % 251
        for r in range(brows):
            for c in range(bstride): self.b[bptr + r * bstride + c] = (r * 13 + c * 5) % 241
        self.record(REC_A, v, cam, MAP_A, rows, cols, TBL_A)
        self.record(REC_B, v_b, cam_b, bptr, brows, 0x70, TBL_B)   # plane B's own column field is not a stride (the provider must not use it)
        self.w(POWER, 2, 3); self.w(0xF324, 2, 3)

    def w(self, off, width, val):
        for k in range(width): self.b[off + k] = (val >> (8 * (width - 1 - k))) & 0xFF
    def r(self, off, width=2): return int.from_bytes(self.b[off:off + width], "big")
    def record(self, base, v, cam, ptr, rows, cols, tbl):
        self.w(base, 2, v); self.w(base + 4, 2, cam); self.w(base + 8, 4, 0x00FF0000 | ptr); self.w(base + 12, 2, rows); self.w(base + 14, 2, cols); self.w(base + 16, 4, 0x00FF0000 | tbl)


def ranges():
    if tomllib is None: raise unittest.SkipTest("Python 3.11+ is required to read mod.toml")
    m = tomllib.loads((PROJECT / "mod.toml").read_text())
    return [(x["offset"], x["length"], 1 if x["access"] in ("write", "read-write") else 0) for x in m["memory"]]


def expect_window(ram, base, mapaddr, table, rows, stride, wrap):
    """The name-table window the provider must submit for the plane whose record is at `base` (independent re-derivation)."""
    v, cam = ram.r(base), ram.r(base + 4)
    hs = ((-cam + 512) & 1023) - 512
    shift = (cam + hs) // 8
    x0 = cam // 8 - 40 - shift
    vs = ((v + 512) & 1023) - 512
    shift_y = (v - vs) // 8
    first = (vs >> 3) - 1
    n = 32
    words = []
    for r in range(n):
        wy = first + r + shift_y
        for c in range(128):
            wx = x0 + c + shift
            bx, by = wx >> 1, wy >> 1
            if wrap: bx &= stride - 1
            else: bx = min(max(bx, 0), stride - 1)
            blk = ram.b[mapaddr + by * stride + bx] if 0 <= bx < stride and 0 <= by < rows else 0
            words.append(ram.r(table + 8 * blk + 2 * ((wy & 1) * 2 + (wx & 1))))
    return x0, first, n, words


@unittest.skipUnless(SDK, "set SEGARECOMP_SDK_DIR to the product's platforms directory to compile the provider against the ABI 2 header")
class Provider(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = pathlib.Path(tempfile.mkdtemp())
        (cls.tmp / "harness.c").write_text(HARNESS)
        flags = ["-std=c11", "-Wall", "-Wextra", "-pedantic", "-Werror", "-DSEGA_MOD_TARGET_PLATFORM=1", "-DSEGA_MOD_TARGET_ABI_MAJOR=2U", "-I", str(pathlib.Path(SDK) / "genesis/sdk"), "-I", str(pathlib.Path(SDK) / "sdk")]
        r = subprocess.run([CC, *flags, "-c", "-o", str(cls.tmp / "provider.o"), str(PROJECT / "src/provider.c")], capture_output=True, text=True)
        if r.returncode != 0: raise AssertionError("the provider does not compile as strict C11 against the ABI 2 header:\n" + r.stderr)
        r = subprocess.run([CC, "-std=c11", "-DSEGA_MOD_TARGET_PLATFORM=1", "-DSEGA_MOD_TARGET_ABI_MAJOR=2U", "-I", str(pathlib.Path(SDK) / "genesis/sdk"), "-I", str(pathlib.Path(SDK) / "sdk"), "-o", str(cls.tmp / "t"), str(cls.tmp / "harness.c"), str(cls.tmp / "provider.o")], capture_output=True, text=True)
        if r.returncode != 0: raise AssertionError("the test harness does not build:\n" + r.stderr)

    @classmethod
    def tearDownClass(cls):
        import shutil; shutil.rmtree(cls.tmp, ignore_errors=True)

    def run_script(self, lines):
        head = ["range %x %d %d" % (o, n, w) for o, n, w in ranges()]
        r = subprocess.run([str(self.tmp / "t")], input="\n".join(head + lines) + "\n", capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout.splitlines()

    @staticmethod
    def load(ram):
        """Script lines that put every byte of the fabricated RAM the provider may read into the mock."""
        lines = []
        for lo, hi in ((0, 0x1000), (0x2000, 0x4800), (0x4800, 0x7000), (0xF200, 0xF500), (0xFA80, 0xFAE0)):
            for off in range(lo, hi, 4):
                v = int.from_bytes(ram.b[off:off + 4], "big")
                if v: lines.append("ram %x 4 %x" % (off, v))
        return lines

    def frame(self, ram, pad=0, frame=1, extra=()):
        return self.load(ram) + ["pad %x" % pad, "frame %d" % frame, *extra, "phase input", "phase post-input", "phase frame-end", "phase render"]

    # ---- widescreen scenery ----
    def check_scene(self, ram, scene):
        out = self.run_script(["init"] + self.frame(ram))
        self.assertEqual(out[0], "init 0")
        self.assertNotIn("FAULT", out)
        self.assertIn("scene " + scene, out)
        wins = [l.split() for l in out if l.startswith("window")]
        self.assertEqual([w[1] for w in wins], ["0", "1"], "one window per plane, plane A first")
        for w, (base, mp, tbl, rows, stride, wrap) in zip(wins, ((REC_A, MAP_A, TBL_A, ram.rows, ram.cols, False), (REC_B, ram.bptr, TBL_B, ram.brows, ram.bstride, ram.bstride == 32))):
            x0, y0, n, words = expect_window(ram, base, mp, tbl, rows, stride, wrap)
            self.assertEqual((int(w[2]), int(w[3]), int(w[4]), int(w[5])), (x0, y0, 128, n))
            self.assertEqual([int(x, 16) for x in w[6:]], words, "window words equal the independent block lookup")

    def test_forest_shaped_scenes_across_cameras(self):
        for cam in (0, 5, 343, 511, 512, 600, 1500, 3800):
            self.check_scene(Ram(cam=cam, cam_b=cam // 2), "a16x240-b16")

    def test_castle_shaped_scene_and_vertical_scroll(self):
        for v in (0, 7, 218, 288):
            self.check_scene(Ram(rows=32, cols=112, brows=32, cam=900, v=v, cam_b=450, v_b=v - v // 8), "a32x112-b32")

    def test_vertical_level_with_wrapped_vertical_scroll(self):
        for v in (0, 300, 511, 512, 800, 1000):
            self.check_scene(Ram(rows=192, cols=48, brows=192, cam=200, v=v, cam_b=100, v_b=v // 2), "a192x48-b192")

    def test_scenes_with_a_wider_plane_b_map_or_a_lower_address(self):
        self.check_scene(Ram(rows=80, cols=80, brows=80, cam=600, v=700, cam_b=300, v_b=300, bstride=80), "a80x80-b80x80")
        self.check_scene(Ram(rows=32, cols=128, brows=32, cam=1500, v=100, cam_b=1000, v_b=50, bstride=128), "a32x128-b32x128")
        self.check_scene(Ram(rows=96, cols=64, brows=96, cam=500, v=900, cam_b=250, v_b=450, bptr=0x4800), "a96x64-b96")

    def test_a_map_address_read_from_the_record(self):
        ram = Ram(rows=14, cols=320, brows=14, cam=1000, v=0, cam_b=500, v_b=0)
        moved = Ram(rows=14, cols=320, brows=14, cam=1000, v=0, cam_b=500, v_b=0)
        moved.b[0x2280:0x2280 + 14 * 320] = ram.b[0x2000:0x2000 + 14 * 320]; moved.b[0x2000:0x2280] = bytes(0x280)
        moved.w(REC_A + 10, 2, 0x2280)
        out = self.run_script(["init"] + self.frame(moved))
        wins = [l.split() for l in out if l.startswith("window")]
        x0, y0, n, words = expect_window(ram, REC_A, 0x2000, TBL_A, 14, 320, False)
        self.assertEqual([int(x, 16) for x in wins[0][6:]], words)

    def test_declines_anything_but_the_verified_shape(self):
        for what, edit in (("map address outside the range", lambda r: r.w(REC_A + 10, 2, 0x5100)), ("table address", lambda r: r.w(REC_B + 18, 2, 0x0900)), ("map size", lambda r: r.w(REC_A + 14, 2, 100)),
                           ("zeroed record (a menu or cutscene)", lambda r: [r.w(REC_A + k, 2, 0) or r.w(REC_B + k, 2, 0) for k in range(0, 20, 2)]), ("camera beyond the map", lambda r: r.w(REC_A + 4, 2, 240 * 16)),
                           ("vertical scroll beyond the plane", lambda r: r.w(REC_A, 2, 2000))):
            ram = Ram(cam=100); edit(ram)
            out = self.run_script(["init"] + self.frame(ram))
            self.assertFalse([l for l in out if l.startswith(("window", "scene", "write"))], what)

    def test_window_never_exceeds_the_host_bounds(self):
        out = self.run_script(["init"] + self.frame(Ram(rows=32, cols=112, brows=32, cam=1700, v=288, cam_b=800, v_b=252)))
        self.assertNotIn("BAD-WINDOW", out)
        self.assertNotIn("FAULT", out)

    # ---- Practice+ ----
    def writes(self, out): return [l for l in out if l.startswith("write")]

    def test_no_gesture_no_write(self):
        out = self.run_script(["init"] + self.frame(Ram(cam=100), pad=0x08) + self.frame(Ram(cam=100), pad=0x60, frame=2))
        self.assertEqual(self.writes(out), [])

    def test_gesture_writes_exactly_the_restore(self):
        for power in (1, 2, 3, 4):
            ram = Ram(cam=100); ram.w(POWER, 2, power); ram.w(HUD_FLAGS, 1, 0x80)
            out = self.run_script(["init", "ram f409 1 80"] + self.frame(ram, pad=CHORD))
            self.assertEqual(self.writes(out), ["write f322 2 5"] + ["write %x 2 807c" % (HUD_SLOTS + 2 * i) for i in range(5)] + ["write f409 1 81"], power)
            self.assertNotIn("FAULT", out)

    def test_held_chord_restores_once_and_a_new_press_after_damage_again(self):
        ram = Ram(cam=100); ram.w(POWER, 2, 2)
        step = lambda pad, power, f: self.frame(ram, pad=pad, frame=f, extra=["ram f322 2 %x" % power])
        out = self.run_script(["init"] + step(CHORD, 2, 1) + step(CHORD, 2, 2) + step(CHORD | 0x08, 2, 3) + step(0, 2, 4) + step(CHORD, 2, 5))
        self.assertEqual(len(self.writes(out)), 14, "one restore per press (7 writes each); the held frames and the frame with an extra button add none")

    def test_no_write_when_power_is_full_dead_or_the_scene_is_not_verified(self):
        for power in (0, 5, 6, 9):
            ram = Ram(cam=100); ram.w(POWER, 2, power)
            self.assertEqual(self.writes(self.run_script(["init"] + self.frame(ram, pad=CHORD))), [], power)
        ram = Ram(cam=100); ram.w(REC_A + 10, 2, 0)
        self.assertEqual(self.writes(self.run_script(["init"] + self.frame(ram, pad=CHORD))), [], "no verified level")

    def test_a_chord_that_was_down_before_the_level_never_fires_later(self):
        bad, good = Ram(cam=100), Ram(cam=100); bad.w(REC_A + 10, 2, 0); good.w(POWER, 2, 2)
        out = self.run_script(["init"] + self.frame(bad, pad=CHORD, frame=1) + self.frame(good, pad=CHORD, frame=2) + self.frame(good, pad=0, frame=3) + self.frame(good, pad=CHORD, frame=4))
        self.assertEqual(len(self.writes(out)), 7)

    def test_only_declared_ranges_are_written_and_lives_are_untouched(self):
        declared = [(o, n) for o, n, w in ranges() if w]
        ram = Ram(cam=100); ram.w(POWER, 2, 1)
        out = self.run_script(["init"] + self.frame(ram, pad=CHORD))
        for l in self.writes(out):
            _, off, width, _v = l.split(); off, width = int(off, 16), int(width)
            self.assertTrue(any(o <= off and off + width <= o + n for o, n in declared), l)
            self.assertNotEqual(off, 0xF324)
        self.assertNotIn("FAULT", out)

    def test_state_roundtrip_keeps_the_edge_and_the_counter(self):
        ram = Ram(cam=100); ram.w(POWER, 2, 2)
        first = self.run_script(["init"] + self.frame(ram, pad=CHORD, frame=1) + ["save"])
        blob = next(l for l in first if l.startswith("state")).split()[1:]
        self.assertEqual(len(blob), 16)
        # a NEW process: load the state, keep holding the chord (no repeat), release, press again with damage taken (fires and counts 2)
        again = self.run_script(["init", "load " + " ".join(blob)] + self.frame(ram, pad=CHORD, frame=2) + self.frame(ram, pad=0, frame=3) + self.frame(ram, pad=CHORD, frame=4) + ["save"])
        self.assertEqual(len(self.writes(again)), 7)
        self.assertEqual(next(l for l in again if l.startswith("state")).split()[5:9], ["00", "00", "00", "02"], "the counter continued from the saved state")
        self.assertIn("load 0", again)

    def test_the_chord_is_taken_from_the_game_only_in_a_verified_level(self):
        ram = Ram(cam=100)
        out = self.run_script(["init"] + self.frame(ram, pad=CHORD | 0x08))
        self.assertIn("setpad 1 8", out, "A+B+C is removed from the sample, the other buttons stay")
        out = self.run_script(["init"] + self.frame(ram, pad=0x50 | 0x08) + self.frame(ram, pad=0x60, frame=2))
        self.assertFalse([l for l in out if l.startswith("setpad")], "a partial chord is the game's")
        bad = Ram(cam=100); bad.w(REC_A + 10, 2, 0)
        self.assertFalse([l for l in self.run_script(["init"] + self.frame(bad, pad=CHORD)) if l.startswith("setpad")], "outside a verified level nothing is intercepted")


    # ---- actors beyond the hardware range (hook-observed pieces, virtual sprites, no guest write) ----
    def piece(self, d0, a0=0xD000, a2=0xF506, y=0xA8, size=0x0F, attr=0x4090, flags=0):
        """Script lines for one hook call on the sprite-piece clip routine: the buffer entry (y word, size byte, link byte, attribute word) sits just before a2, the object's flag byte at a0 + 0xE."""
        base = a2 - 6
        return ["ram %x 2 %x" % (base, y), "ram %x 1 %x" % (base + 2, size), "ram %x 2 %x" % (base + 4, attr), "ram %x 1 %x" % (a0 + 0xE, flags), "reg 0 %x" % d0, "reg 8 %x" % (0xFF0000 | a0), "reg 10 %x" % (0xFF0000 | a2), "hook"]

    def actors(self, hooks, scene_ok=True, frames=1):
        ram = Ram(cam=100)
        if not scene_ok: ram.w(REC_A + 10, 2, 0)
        lines = ["init"] + self.load(ram) + ["pad 0", "frame 1"]
        for h in hooks: lines += h
        lines += ["phase input", "phase post-input", "phase frame-end", "phase render"]
        return self.run_script(lines)

    def sprites(self, out): return [l.split() for l in out if l.startswith("vs ")]

    def test_a_dropped_piece_becomes_one_game_art_virtual_sprite(self):
        out = self.actors([self.piece(0x1F6)])
        self.assertIn("vsprites space 1 budget 0 count 1", out)
        # provenance 1 (game state verified), layer 2 (above all), x = 0x1F6 - 128, y = 0xA8 - 128, a 4 x 4 cell piece, tile 0x90, palette 2, no flips, no clip
        self.assertEqual(self.sprites(out), [["vs", "1", "2", "374", "40", "4", "4", "144", "2", "0", "0", "0"]])
        self.assertEqual(self.writes(out), [], "presentation only: no guest write")
        self.assertNotIn("FAULT", out)

    def test_the_games_own_clip_range_is_respected_exactly(self):
        for d0, dropped in ((0x5F, True), (0x60, False), (0x100, False), (0x1DF, False), (0x1E0, True), (0xFF00, True), (0x400, True)):
            out = self.actors([self.piece(d0)])
            self.assertEqual(len(self.sprites(out)), 1 if dropped else 0, hex(d0))
        self.assertEqual(self.sprites(self.actors([self.piece(0xFF00)]))[0][3], str(-256 - 128), "a negative x keeps its sign")

    def test_attribute_bits_become_tile_palette_flips(self):
        out = self.actors([self.piece(0x1F6, attr=0x8000 | (3 << 13) | 0x1000 | 0x0800 | 0x123, size=0x05)])
        self.assertEqual(self.sprites(out), [["vs", "1", "2", "374", "40", "2", "2", "291", "3", "1", "1", "0"]])

    def test_never_clipped_objects_foreign_addresses_and_other_scenes_submit_nothing(self):
        self.assertEqual(self.sprites(self.actors([self.piece(0x1F6, flags=0x20)])), [], "an object the game never clips is kept by the game")
        self.assertEqual(self.sprites(self.actors([self.piece(0x1F6, a0=0x9000)])), [], "an object outside the declared range is not a verified object")
        self.assertEqual(self.sprites(self.actors([self.piece(0x1F6, a2=0xF900)])), [], "a position outside the sprite buffer is not a piece")
        out = self.actors([self.piece(0x1F6)], scene_ok=False)
        self.assertEqual(self.sprites(out), [], "no verified level: no virtual sprite")
        self.assertNotIn("FAULT", out)

    def test_pieces_live_one_frame_and_are_bounded(self):
        hooks = [self.piece(0x1F6 + k, a2=0xF506 + 8 * (k % 32)) for k in range(60)]
        out = self.actors(hooks)
        self.assertEqual(len(self.sprites(out)), 48, "at most 48 pieces per frame")
        ram = Ram(cam=100)
        lines = ["init"] + self.load(ram) + ["pad 0", "frame 1"] + self.piece(0x1F6) + ["phase frame-end", "phase render", "frame 2", "phase frame-end", "phase render"]
        out = self.run_script(lines)
        self.assertEqual(len(self.sprites(out)), 1, "a piece collected in one frame is served once, never carried to the next")

    def test_a_restored_state_starts_with_no_pieces(self):
        ram = Ram(cam=100)
        first = self.run_script(["init"] + self.load(ram) + ["pad 0", "frame 1"] + self.piece(0x1F6) + ["phase frame-end", "save"])
        blob = next(l for l in first if l.startswith("state")).split()[1:]
        out = self.run_script(["init"] + self.load(ram) + ["pad 0", "frame 2", "load " + " ".join(blob), "phase render"])
        self.assertEqual(self.sprites(out), [], "nothing is drawn from before the restore")

    def test_far_coordinates_are_not_submitted(self):
        self.assertEqual(self.sprites(self.actors([self.piece(0x7000)])), [], "x beyond the transport's coordinate limit")

    def test_rejects_a_corrupt_state(self):
        out = self.run_script(["init", "load 00 00 00 05 00 00 00 00 00 00 00 00 00 00 00 00", "echo done"])
        self.assertIn("load 1", out)


if __name__ == "__main__":
    unittest.main()
