"""Castle of Illusion provider (SEG-149-T002 / SEG-149-T003): the algorithmic contract on FABRICATED work RAM. No ROM, no game data: the synthetic block tables, maps and scroll records below only have the SHAPE the provider documents.

The provider (patches/genesis/castle-of-illusion/widescreen-practice/src/provider.c) is compiled against the product's ABI 2 header with a small mock host (declared ranges enforced, writes staged and applied at the end of the callback, the typed render
feature recorded) and driven through its public entry point. The test needs the product's SDK headers and a C compiler: set SEGARECOMP_SDK_DIR (the product's `platforms` directory) and optionally SEGARECOMP_CC; otherwise it is
skipped with that reason, never silently passed. The commercial-game evidence (real frames, aspect matrix, save/replay) is described in the project's README and was produced locally; it cannot run in CI."""
import os, pathlib, subprocess, sys, tempfile, unittest
try: import tomllib
except ImportError: tomllib = None

ROOT = pathlib.Path(__file__).resolve().parent.parent
PROJECT = ROOT / "patches/genesis/castle-of-illusion/widescreen-practice"
SDK, CC = os.environ.get("SEGARECOMP_SDK_DIR"), os.environ.get("SEGARECOMP_CC", "cc")
if os.environ.get("SEGARECOMP_REQUIRE_EXEC") == "1" and (not SDK or tomllib is None):
    raise RuntimeError("SEGARECOMP_REQUIRE_EXEC=1 but SEGARECOMP_SDK_DIR is not set or Python lacks tomllib: the provider tests would be skipped")

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
static uint32_t pad1, pad2, regs[32];
static int in_range(uint32_t off, uint32_t w, int write) { int i; for (i = 0; i < nranges; ++i) if (off >= ranges[i].off && off + w <= ranges[i].off + ranges[i].len && (!write || ranges[i].write)) return 1; return 0; }
static int mread(uint32_t space, uint32_t off, uint32_t w, uint32_t *v) {
  uint32_t i, x = 0;
  if (space == SEGA_GEN_SPACE_M68K_HOOK_REGS) { if (off >= 32 || w != 4) { fault = 1; return SEGA_MOD_E_RANGE; } *v = regs[off]; return 0; }
  if (space != SEGA_GEN_SPACE_M68K_WORK_RAM || !in_range(off, w, 0)) { fault = 1; return SEGA_MOD_E_RANGE; }
  for (i = 0; i < w; ++i) x = (x << 8) | ram[off + i]; *v = x; return 0; }
static int mwrite(uint32_t space, uint32_t off, uint32_t w, uint32_t v) {
  if (space != SEGA_GEN_SPACE_M68K_WORK_RAM || !in_range(off, w, 1) || nstaged >= 64) { fault = 1; return SEGA_MOD_E_RANGE; }
  staged[nstaged].off = off; staged[nstaged].w = w; staged[nstaged].v = v; ++nstaged; return 0; }
static int minput(uint32_t port, uint32_t *b) { if (port != 1U && port != 2U) return 1; *b = port == 1U ? pad1 : pad2; return 0; }
static int mset(uint32_t port, uint32_t b) { printf("setpad %u %x\n", port, b); return 0; }
static void mlog(const char *s, uint32_t n) { printf("log %.*s\n", (int)n, s); }
static int a_layer(uint32_t a, uint32_t b, uint32_t c, int32_t d, int32_t e, uint32_t f, uint32_t g, uint32_t h) { printf("layer %u %u %u %d %d %u %u %u\n", a, b, c, d, e, f, g, h); return 0; }
static int a_target(uint32_t i) { printf("target %u\n", i); return 0; }
static uint32_t margin;
static int a_margin(uint32_t *m) { *m = margin; return 0; }
static int a_left(uint32_t l, uint32_t m) { printf("view_left %u %u\n", l, m); return 0; }
static int a_rect(int32_t x, int32_t y, int32_t w, int32_t h, uint32_t c) { printf("rect %d %d %d %d\n", x, y, w, h); (void)c; return 0; }
static int a_text(int32_t x, int32_t y, const char *t, uint32_t n, uint32_t c) { printf("text %d %d %.*s\n", x, y, (int)n, t); (void)c; return 0; }
static int a_scene(const char *id, uint32_t n) { printf("scene %.*s\n", (int)n, id); return 0; }
static int a_sprites(const GenesisVirtualSpriteSet *s) {
  uint32_t i; printf("vsprites space %u budget %u count %u\n", s->space, s->budget_mode, s->count);
  for (i = 0; i < s->count; ++i) { const GenesisVirtualSprite *c = &s->sprites[i]; printf("vs %u %u %d %d %u %u %u %u %u %u %u %d %d %u %u\n", c->provenance, c->layer, c->x, c->y, c->width_cells, c->height_cells, c->tile_index, c->palette, c->h_flip, c->v_flip, c->has_clip, c->clip_x, c->clip_y, c->clip_w, c->clip_h); printf("vsflag %u\n", c->flags); }
  return 0; }
static int a_window(uint32_t plane, int32_t x0, int32_t y0, uint32_t cols, uint32_t rows, const uint16_t *w) {
  uint32_t i; if (cols == 0 || rows == 0 || cols > 128 || rows > 64 || cols * rows > 4096) { printf("BAD-WINDOW\n"); return SEGA_MOD_E_RANGE; }
  printf("window %u %d %d %u %u", plane, x0, y0, cols, rows); for (i = 0; i < cols * rows; ++i) printf(" %04x", w[i]); printf("\n"); return 0; }
static void commit(void) { int i; for (i = 0; i < nstaged; ++i) { uint32_t k; for (k = 0; k < staged[i].w; ++k) ram[staged[i].off + k] = (uint8_t)(staged[i].v >> (8U * (staged[i].w - 1U - k))); printf("write %x %u %x\n", staged[i].off, staged[i].w, staged[i].v); } nstaged = 0; }
int main(int argc, char **argv) {
  const SegaModProvider *p; void *state = NULL; char line[256]; uint64_t frame = 0; uint8_t blob[64]; uint32_t bloblen = 0; (void)argc; (void)argv;
  host.size = sizeof host; host.abi_major = 2; host.platform = SEGA_MOD_PLATFORM; host.platform_features = &features; host.read = mread; host.write = mwrite; host.input_get = minput; host.input_set = mset; host.log = mlog;
  features.size = sizeof features; features.render = &api;
  api.size = sizeof api; api.view_margin = a_margin; api.view_left = a_left; api.overlay_layer = a_layer; api.overlay_target = a_target; api.overlay_rect = a_rect; api.overlay_text = a_text; api.scene = a_scene; api.virtual_sprites = a_sprites; api.scenery_window = a_window; api.virtual_sprites = a_sprites;
  p = segarecomp_mod_provider(&state);
  while (fgets(line, sizeof line, stdin)) {
    unsigned a, b, c;
    if (sscanf(line, "range %x %u %u", &a, &b, &c) == 3) { ranges[nranges].off = a; ranges[nranges].len = b; ranges[nranges].write = (int)c; ++nranges; }
    else if (sscanf(line, "ram %x %u %x", &a, &b, &c) == 3) { unsigned k; for (k = 0; k < b; ++k) ram[a + k] = (uint8_t)(c >> (8U * (b - 1U - k))); }
    else if (sscanf(line, "pad2 %x", &a) == 1) pad2 = a;
    else if (sscanf(line, "pad %x", &a) == 1) pad1 = a;
    else if (sscanf(line, "margin %u", &a) == 1) margin = a;
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


# the scenes whose plane B is left to the VDP-derived extension: measured pixel-identical to the authored one in 20 sampled frames each (a48x160-b48 and a96x64-b96 differ and stay authored)
GENERIC_B = {"a16x240-b16", "a48x160-b16", "a48x128-b48", "a16x32-b16", "a192x48-b192", "a32x112-b32", "a14x320-b14", "a17x32-b17", "a48x256-b48", "a16x160-b16", "a32x32-b32", "a16x64-b16"}


def ref_left(cam, cols, margin):
    """The expected placement, written from the rule (not from the C): aligned left at the first column, centred in the middle, aligned right at the last (camera = cols * 16 - 320); the two ramps are
    `zone = min(range / 2, 6 * margin)` camera pixels long and linear; a level narrower than the planned total keeps `min(camera, margin)`."""
    rng = cols * 16 - 320
    cam = max(0, min(cam, rng))
    if rng < 2 * margin:
        return min(cam, margin)
    zone = min(rng // 2, 6 * margin)
    return (margin * min(cam, zone)) // zone + margin - (margin * min(rng - cam, zone)) // zone


def expect_window(ram, base, mapaddr, table, rows, stride, wrap, band=False, left=238):
    """The name-table window the provider must submit for the plane whose record is at `base` (independent re-derivation): the main window starting 6 cells left of the view (the view starts `left` pixels
    left of the camera; 238 is the symmetric 32:9 margin the provider assumes while the host's margin is unknown), 128 columns and 32 rows, or, with band=True, the second window of ADR 0313 (the band is not
    scrolled: its first cell is the view's own first cell less 2, 128 columns, 16 rows from picture row 128 down, the same vertical scroll)."""
    v, cam = ram.r(base), ram.r(base + 4)
    hs = ((-cam + 512) & 1023) - 512
    shift = (cam + hs) // 8
    x0 = -((left + 7) // 8) - 2 if band else ((cam - left) >> 3) - 6 - shift
    vs = ((v + 512) & 1023) - 512
    shift_y = (v - vs) // 8
    first = ((128 + vs) >> 3) - 1 if band else (vs >> 3) - 1
    n = 16 if band else 32
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
        authored_b = scene not in GENERIC_B   # ADR 0314: in the measured scenes plane B is a tiling background the VDP-derived extension already shows: no plane B window at all
        self.assertEqual([w[1] for w in wins], ["0", "1", "0", "1"] if authored_b else ["0", "0"], "per authored plane the main window, then the band window; plane A first (ADR 0313: two windows per plane; ADR 0314: no window for a tiling plane B)")
        planes = ((REC_A, MAP_A, TBL_A, ram.rows, ram.cols, False), (REC_B, ram.bptr, TBL_B, ram.brows, ram.bstride, ram.bstride == 32))
        order = [(0, False), (1, False), (0, True), (1, True)] if authored_b else [(0, False), (0, True)]
        for w, (plane, band) in zip(wins, order):
            base, mp, tbl, rows, stride, wrap = planes[plane]
            x0, y0, n, words = expect_window(ram, base, mp, tbl, rows, stride, wrap, band)
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

    def test_band_scrolled_stage_shapes(self):
        self.check_scene(Ram(rows=48, cols=160, brows=48, cam=900, v=336, cam_b=450, v_b=336), "a48x160-b48")
        self.check_scene(Ram(rows=48, cols=256, brows=48, cam=1500, v=100, cam_b=750, v_b=50), "a48x256-b48")
        self.check_scene(Ram(rows=16, cols=160, brows=16, cam=700, v=0, cam_b=350, v_b=0), "a16x160-b16")
        self.check_scene(Ram(rows=32, cols=32, brows=32, cam=100, v=60, cam_b=50, v_b=30), "a32x32-b32")
        self.check_scene(Ram(rows=80, cols=128, brows=80, cam=900, v=300, cam_b=450, v_b=150, bstride=128, bptr=0x4800), "a80x128-b80x128")
        self.check_scene(Ram(rows=16, cols=64, brows=16, cam=535, v=32, cam_b=535, v_b=32), "a16x64-b16")

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

    def actors(self, hooks, scene_ok=True, frames=1, margin=101, cam=100):
        """One frame with the host's plan `margin` (px per side; 101 = the 21:9 package's, 0 = no extension) and the given camera. The margin is learnt at this frame's render, so the placement is the widest of the plan (see actors_placed for the exact one)."""
        ram = Ram(cam=cam)
        if not scene_ok: ram.w(REC_A + 10, 2, 0)
        lines = ["init"] + self.load(ram) + ["pad 0", "margin %d" % margin, "frame 1"]
        for h in hooks: lines += h
        lines += ["phase input", "phase post-input", "phase frame-end", "phase render"]
        return self.run_script(lines)

    def sprites(self, out): return [l.split() for l in out if l.startswith("vs ")]

    def test_a_dropped_piece_becomes_one_game_art_virtual_sprite(self):
        out = self.actors([self.piece(0x1F6)])
        self.assertIn("vsprites space 1 budget 1 count 1", out)
        # provenance 1 (game state verified), layer 1 (between: the attribute word 0x4090 has priority 0), x = 0x1F6 - 128, y = 0xA8 - 128, a 4 x 4 cell piece, tile 0x90, palette 2, no flips, no clip
        self.assertEqual(self.sprites(out), [["vs", "1", "1", "374", "40", "4", "4", "144", "2", "0", "0", "0", "0", "0", "0", "0"]])
        self.assertEqual(self.writes(out), [], "presentation only: no guest write")
        self.assertNotIn("FAULT", out)

    def test_the_pieces_own_priority_bit_selects_the_layer(self):
        # ADR 0312: a priority-0 piece (bit 15 clear) sits behind high-priority planes (BETWEEN, 1); a priority-1 piece is above everything (ABOVE_ALL, 2); nothing else about the command depends on it
        low = self.sprites(self.actors([self.piece(0x1F6, attr=0x4090)]))
        high = self.sprites(self.actors([self.piece(0x1F6, attr=0xC090)]))
        self.assertEqual((low[0][2], high[0][2]), ("1", "2"))
        self.assertEqual(low[0][:2] + low[0][3:], high[0][:2] + high[0][3:], "only the layer differs; the palette bits 14..13 and the tile are the same")
        mixed = self.sprites(self.actors([self.piece(0x1F6, attr=0x0090), self.piece(0x1F8, attr=0x8091), self.piece(0x1FA, attr=0x7FFF), self.piece(0x1FC, attr=0xFFFF)]))
        self.assertEqual([m[2] for m in mixed], ["1", "2", "1", "2"], "one set mixes both layers, in submission order")
        edge = self.sprites(self.actors([self.piece(0x1C0 + 4, attr=0x0090)]))
        self.assertEqual((edge[0][2], edge[0][11:]), ("1", ["1", "320", "0", "1024", "224"]), "a clipped edge piece keeps its clip and takes its own layer")

    def test_every_cell_the_host_can_ask_for_is_answered_by_one_of_the_two_windows(self):
        # ADR 0313: the playfield rows are scrolled with the camera, the rows of a split-scroll band with scroll 0; their cell ranges can be disjoint (a union wider than the 128-column bound), so each authored plane has two windows.
        # The host asks for plane cell floor((x - hscroll) / 8) of row floor((line + vscroll) / 8); a window answers a cell it contains, the first window of the plane first.
        # ADR 0314: plane B is authored only in the scenes where it was measured to differ from the VDP-derived extension; elsewhere it has no window and the VDP-derived extension answers it.
        for cam in (0, 5, 96, 343, 511, 512, 600, 1500, 3800):
            for ram, planes in ((Ram(rows=32, cols=128, brows=32, bstride=128, cam=cam % 2000, cam_b=((cam * 3) // 5) % 2000), (0, 1)), (Ram(cam=cam, cam_b=(cam * 3) // 5), (0,))):   # a32x128-b32x128 (authored plane B), a16x240-b16 (plane B left to the VDP-derived extension)
                out = self.run_script(["init"] + self.frame(ram))
                wins = [l.split() for l in out if l.startswith("window")]
                self.assertEqual(len(wins), 4 if len(planes) == 2 else 2)
                self.assertEqual(sorted({int(w[1]) for w in wins}), list(planes), "a plane has windows exactly when it is authored")
                for plane in planes:
                    base = (REC_A, REC_B)[plane]
                    mine = [(int(w[2]), int(w[3]), int(w[4]), int(w[5])) for w in wins if int(w[1]) == plane]
                    v, camp = ram.r(base), ram.r(base + 4)
                    vs = ((v + 512) & 1023) - 512
                    hs_play = ((-camp + 512) & 1023) - 512
                    for hs, rows in ((hs_play, range(0, 192, 3)), (0, range(150, 224, 2))):   # scrolled playfield rows, then the unscrolled rows from 150 down
                        for line in rows:
                            for x in range(-238, 558 + 1, 7):
                                cx, cy = (x - hs) // 8, (line + vs) // 8
                                self.assertTrue(any(x0 <= cx < x0 + c and y0 <= cy < y0 + r for x0, y0, c, r in mine), "plane %d cam %d: cell (%d, %d) at x %d line %d (hscroll %d) is in no window" % (plane, cam, cx, cy, x, line, hs))

    # ---- the asymmetric view (product ADR 0315) ----
    def two_frames(self, ram, margin, extra=()):
        """Frame 1 (the host's margin is not known yet: its render learns it), then frame 2, whose windows and placement are the ones under test. Returns the output lines of frame 2 only."""
        out = self.run_script(["init", "margin %d" % margin] + self.frame(ram, frame=1) + ["echo FRAME2"] + self.frame(ram, frame=2, extra=extra))
        self.assertNotIn("FAULT", out)
        return out[out.index("FRAME2") + 1:], out[:out.index("FRAME2")]

    def test_the_placement_ramps_slowly_between_the_aligned_ends(self):
        # left of the view at the level's first column, centred in the middle, right of the view at the last column, linear ramps in between (a slope of at most 1/6, so the parallax layers do not slide against the foreground)
        for margin in (39, 101, 238):
            for cam in (0, 1, 38, 39, 40, 100, 237, 238, 239, 1000, 1500, 1800, 2100, 3000, 3282, 3300, 3481, 3520, 3600):
                ram = Ram(rows=16, cols=240, brows=16, cam=cam, cam_b=cam // 2)
                second, first = self.two_frames(ram, margin)
                want = ref_left(cam, 240, margin)
                self.assertEqual([l for l in second if l.startswith("view_left")], ["view_left %d %d" % (want, margin)], "margin %d camera %d" % (margin, cam))
                self.assertEqual([l for l in first if l.startswith("view_left")], [], "the first frame knows no margin: nothing is declared")
                wins = [l.split() for l in second if l.startswith("window")]
                x0, y0, n, words = expect_window(ram, REC_A, MAP_A, TBL_A, 16, 240, False, left=want)
                self.assertEqual((int(wins[0][2]), [int(x, 16) for x in wins[0][6:]]), (x0, words), "the plane A window follows the placement (margin %d camera %d)" % (margin, cam))
                bx0, _, _, bwords = expect_window(ram, REC_A, MAP_A, TBL_A, 16, 240, False, band=True, left=want)
                self.assertEqual((int(wins[1][2]), [int(x, 16) for x in wins[1][6:]]), (bx0, bwords), "the band window follows the placement")

    def test_the_placement_properties(self):
        # pure properties of the rule over every camera of several level widths: the ends are aligned, the middle is centred, it never moves faster than the camera allows (no void left of the level or right of its end),
        # it is monotone with a slope of at most 1/6 once the level is wide enough for the ramps, and it is symmetric (left(c) + left(range - c) = total)
        for cols in (240, 160, 96, 48):
            for margin in (39, 101, 238):
                rng = cols * 16 - 320
                prev = None
                for cam in range(0, rng + 1):
                    left = ref_left(cam, cols, margin)
                    self.assertTrue(0 <= left <= 2 * margin)
                    if rng >= 2 * margin:
                        self.assertLessEqual(left, cam, "no void left of the level")
                        self.assertGreaterEqual(left, 2 * margin - (rng - cam), "the view never passes the level's end")
                        self.assertLessEqual(abs(left + ref_left(rng - cam, cols, margin) - 2 * margin), 1, "symmetric")
                        if prev is not None:
                            self.assertTrue(0 <= left - prev <= 1, "monotone, one pixel at most per camera pixel")
                    prev = left
                if rng >= 2 * margin:
                    self.assertEqual((ref_left(0, cols, margin), ref_left(rng, cols, margin)), (0, 2 * margin), "aligned left at the start, right at the end")
                    zone = min(rng // 2, 6 * margin)
                    self.assertEqual({ref_left(c, cols, margin) for c in range(zone, rng - zone + 1)} - {margin}, set(), "centred between the ramps")
                    # the slope over the first ramp is margin / zone <= 1/6 when the level is wide enough for a full 6-margin ramp
                    if rng >= 12 * margin:
                        self.assertLessEqual(ref_left(zone, cols, margin) - ref_left(0, cols, margin), margin)
                        self.assertLessEqual((ref_left(zone // 2, cols, margin) + 1) * 6 * zone // zone, 6 * margin + 6)

    def test_no_placement_without_a_known_margin_or_a_verified_scene(self):
        ram = Ram(cam=100)
        out = self.run_script(["init"] + self.frame(ram, frame=1) + self.frame(ram, frame=2))   # the mock host reports margin 0: no extension is planned
        self.assertEqual([l for l in out if l.startswith("view_left")], [], "margin 0: the centred layout is assumed, nothing is declared")
        windows = [l.split() for l in out if l.startswith("window")]
        x0, _, _, _ = expect_window(ram, REC_A, MAP_A, TBL_A, 16, 240, False)
        self.assertEqual(int(windows[0][2]), x0, "the windows are the symmetric ones (238)")
        menu = Ram(cam=100); [menu.w(REC_A + k, 2, 0) or menu.w(REC_B + k, 2, 0) for k in range(0, 20, 2)]
        second, _ = self.two_frames(menu, 238)
        self.assertEqual([l for l in second if l.startswith(("view_left", "window", "scene"))], [], "a menu or cutscene declares no placement")

    def test_a_changed_margin_is_never_given_a_placement_computed_for_another(self):
        ram = Ram(cam=150)
        out = self.run_script(["init", "margin 238"] + self.frame(ram, frame=1) + self.frame(ram, frame=2) + ["margin 39"] + ["echo F3"] + self.frame(ram, frame=3) + ["echo F4"] + self.frame(ram, frame=4))
        f3 = out[out.index("F3") + 1:out.index("F4")]
        f4 = out[out.index("F4") + 1:]
        self.assertEqual([l for l in out[:out.index("F3")] if l.startswith("view_left")], ["view_left %d 238" % ref_left(150, 240, 238)], "frame 2: margin 238 learnt in frame 1")
        self.assertEqual([l for l in f3 if l.startswith("view_left")], [], "frame 3: the windows were built for margin 238 but the host now plans 39: no placement")
        self.assertEqual([l for l in f3 if l.startswith("window")], [], "frame 3: and no window either (they answer the cells of a view that is no longer the host's); the actors and the indicator are still submitted")
        self.assertTrue([l for l in f3 if l.startswith("rect")], "the indicator is independent of the view")
        self.assertEqual([l for l in f4 if l.startswith("view_left")], ["view_left %d 39" % ref_left(150, 240, 39)], "frame 4: built for 39, declared for 39")

    def test_windows_cover_the_placed_view(self):
        # the whole presented view: screen x from -left to 320 + (2 * margin - left); scrolled playfield rows (and plane B's own scroll where it is authored) and the unscrolled band rows
        for margin in (39, 78, 101, 238):
            for cam in (0, 7, 39, 96, 238, 343, 511, 512, 600, 1500, 3800):
                for ram, planes in ((Ram(rows=32, cols=128, brows=32, bstride=128, cam=cam % 2000, cam_b=((cam * 3) // 5) % 2000), (0, 1)), (Ram(cam=cam, cam_b=(cam * 3) // 5), (0,))):
                    second, _ = self.two_frames(ram, margin)
                    left = ref_left(ram.r(REC_A + 4), ram.cols, margin)
                    self.assertEqual([l for l in second if l.startswith("view_left")], ["view_left %d %d" % (left, margin)])
                    wins = [l.split() for l in second if l.startswith("window")]
                    for plane in planes:
                        base = (REC_A, REC_B)[plane]
                        mine = [(int(w[2]), int(w[3]), int(w[4]), int(w[5])) for w in wins if int(w[1]) == plane]
                        v, camp = ram.r(base), ram.r(base + 4)
                        vs = ((v + 512) & 1023) - 512
                        hs_play = ((-camp + 512) & 1023) - 512
                        for hs, rows in ((hs_play, range(0, 192, 5)), (0, range(150, 224, 2))):
                            for line in rows:
                                for x in range(-left, 320 + 2 * margin - left, 7):
                                    cx, cy = (x - hs) // 8, (line + vs) // 8
                                    self.assertTrue(any(x0 <= cx < x0 + c and y0 <= cy < y0 + r for x0, y0, c, r in mine), "margin %d camera %d plane %d: cell (%d, %d) at x %d line %d is in no window" % (margin, cam, plane, cx, cy, x, line))

    def test_the_indicator_is_always_a_top_right_layer_never_the_fixed_overlay(self):
        # the fixed overlay is the game's relocated HUD in the host's accounting and sits at the left edge of the view (the picture's own power meter when the picture is placed left): the panel is a layer
        second, first = self.two_frames(Ram(cam=100), 238)
        for out in (second, first, self.run_script(["init"] + self.frame(Ram(cam=100)))):   # planned, learnt in the same render, and no extension (margin 0)
            self.assertIn("layer 1 2 1 0 0 40 16 0", out, "anchored to the top right of the presentation, where the picture's own HUD never is")
            self.assertLess(out.index("layer 1 2 1 0 0 40 16 0"), out.index("target 1"))
            self.assertLess(out.index("target 1"), out.index("rect 0 0 24 8"), "the panel is drawn into the layer, never into the fixed overlay (target 0)")

    def test_the_hardware_piece_flag_is_set_on_kept_edge_pieces_only(self):
        # ADR 0313: a piece the game kept (the host's Level 3 extension already draws it with the original rules) carries HARDWARE_PIECE; a piece the game dropped does not
        dropped = self.actors([self.piece(0x1F6)])
        edge = self.actors([self.piece(0x1C0 + 4)])
        inside = self.actors([self.piece(0x80 + 100)])
        flags = lambda out: [l.split()[1] for l in out if l.startswith("vsflag")]
        self.assertEqual((flags(dropped), flags(edge), flags(inside)), (["0"], ["1"], []), "dropped: unflagged; kept beside the raster: flagged; kept inside the raster: not submitted")

    def test_the_games_own_clip_range_is_respected_exactly(self):
        # a 4 x 4 cell piece (32 px wide): dropped by the game outside 0x60..0x1DF (drawn whole), kept inside; a kept piece that lies fully inside the 320 px raster is the hardware's alone
        for d0, drawn in ((0x5F, True), (0x80, False), (0x100, False), (0x1DF, True), (0x1E0, True), (0xFFF4, True), (0xFF00, False), (0x400, False)):   # the last two are dropped by the game but lie beyond the widest presented view (21:9 plan): nothing shows them
            out = self.actors([self.piece(d0)])
            self.assertEqual(len(self.sprites(out)), 1 if drawn else 0, hex(d0))
        self.assertEqual(self.sprites(self.actors([self.piece(0xFFF4)]))[0][3], str(-12 - 128), "a negative x keeps its sign")

    def test_a_kept_piece_beside_the_raster_is_drawn_only_outside_it(self):
        # the sprite table can address 32 columns each side of the 320 px raster; the game keeps those pieces but nothing displays them
        right = self.sprites(self.actors([self.piece(0x1C0 + 0)]))    # screen x 320, 32 px wide: wholly right of the raster
        self.assertEqual(len(right), 1)
        self.assertEqual(right[0][11:], ["1", "320", "0", "1024", "224"], "clip: only x >= 320")
        straddle = self.sprites(self.actors([self.piece(0x1A0 + 0x10)]))   # screen x 304: 16 px in the picture, 16 beside it
        self.assertEqual(len(straddle), 1); self.assertEqual(straddle[0][11:], ["1", "320", "0", "1024", "224"])
        left = self.sprites(self.actors([self.piece(0x60 + 0x10)]))     # screen x -16: 16 px beside the raster, 16 in it
        self.assertEqual(len(left), 1); self.assertEqual(left[0][11:], ["1", "-1024", "0", "1024", "224"]); self.assertEqual(left[0][3], "-16")
        inside = self.actors([self.piece(0x80 + 288)])                 # screen x 288, exactly flush with the right edge (288 + 32 = 320)
        self.assertEqual(self.sprites(inside), [], "a kept piece wholly inside the raster is drawn by the hardware only")
        small = self.sprites(self.actors([self.piece(0x80 + 312, size=0x00)]))   # 1 x 1 cell piece at 312: 8 px, flush with the edge
        self.assertEqual(small, [])
        small = self.sprites(self.actors([self.piece(0x80 + 313, size=0x00)]))
        self.assertEqual(len(small), 1, "one pixel beyond the edge")

    def test_attribute_bits_become_tile_palette_flips(self):
        out = self.actors([self.piece(0x1F6, attr=0x8000 | (3 << 13) | 0x1000 | 0x0800 | 0x123, size=0x05)])
        self.assertEqual(self.sprites(out), [["vs", "1", "2", "374", "40", "2", "2", "291", "3", "1", "1", "0", "0", "0", "0", "0"]])

    def test_never_clipped_objects_foreign_addresses_and_other_scenes_submit_nothing(self):
        self.assertEqual(self.sprites(self.actors([self.piece(0x1F6, flags=0x20)])), [], "an object the game never clips is kept by the game (outside the table's range the hardware wraps it: not reproduced)")
        edge = self.sprites(self.actors([self.piece(0x1C0 + 4, flags=0x20)]))
        self.assertEqual(len(edge), 1, "a never-clipped object's piece beside the raster is still drawn there (clipped to the part outside the raster)"); self.assertEqual(edge[0][11:], ["1", "320", "0", "1024", "224"])
        self.assertEqual(self.sprites(self.actors([self.piece(0x100, flags=0x20)])), [], "a never-clipped piece inside the raster is the hardware's")
        self.assertEqual(self.sprites(self.actors([self.piece(0x1F6, a0=0x9000)])), [], "an object outside the declared range is not a verified object")
        self.assertEqual(self.sprites(self.actors([self.piece(0x1F6, a2=0xF900)])), [], "a position outside the sprite buffer is not a piece")
        out = self.actors([self.piece(0x1F6)], scene_ok=False)
        self.assertEqual(self.sprites(out), [], "no verified level: no virtual sprite")
        self.assertNotIn("FAULT", out)


    # ---- Task C: visible pieces are never starved by invisible ones; the view the host presents decides ----
    # A piece is submitted only if the game DROPPED it (screen x < -32 or >= 352, d0 outside 0x60..0x1DF) or KEPT it beside the raster (its part beside the raster). Screen x = d0 - 128; every test piece is 32 x 32 px unless said.
    def at(self, sx, **kw): return self.piece((sx + 128) & 0xFFFF, **kw)

    def actors_placed(self, hooks, margin=101, cam=601, margin2=None):   # camera 601 of a 240-block level: the ramp (6 * 101 = 606 camera pixels) places the picture 100 columns from the left of the view
        """Two frames: frame 1 learns the host's plan, frame 2 (with `hooks`, plan `margin2` or the same) builds the exact placement view_left = placement(camera). Returns frame 2's output only."""
        ram = Ram(cam=cam)
        lines = ["init"] + self.load(ram) + ["pad 0", "margin %d" % margin, "frame 1", "phase input", "phase post-input", "phase frame-end", "phase render", "echo ---\n"]
        if margin2 is not None: lines.append("margin %d" % margin2)
        lines += ["frame 2"]
        for h in hooks: lines += h
        lines += ["phase input", "phase post-input", "phase frame-end", "phase render"]
        out = self.run_script(lines)
        return out[out.index("---") + 1:]

    def xs(self, out): return [int(v[3]) for v in self.sprites(out)]
    def spread(self, base, n, per=60, **kw): return [self.at(base + k % per, a2=0xF506 + 8 * (k % 32), a0=0xD000 + 0x40 * (k % 8), **kw) for k in range(n)]

    def test_visible_pieces_after_many_invisible_ones_are_all_submitted(self):
        # 21:9 plan (101 px per side), camera 100: the view is [-100, 422). 120 pieces at x 470 (beyond the view but inside the widest 32:9 bound, so they are collected) come first, then 20 visible ones
        far = self.spread(470, 120, per=8)
        vis = [self.at(352 + k, a2=0xF506 + 8 * (k % 32), a0=0xD000 + 0x40 * (k % 8)) for k in range(20)]
        out = self.actors_placed(far + vis)
        self.assertEqual(self.xs(out), [352 + k for k in range(20)], "all 20 visible pieces, in the game's order, none of the invisible ones")
        self.assertFalse(any(l.startswith("log ") for l in out), "nothing visible was lost")
        # the same on the first frame of a session (the plan is only learnt at render, the exact placement is unknown): the widest placement of the plan is used and everything inside it is kept
        self.assertEqual([x for x in self.xs(self.actors(far[:40] + vis)) if x < 400], [352 + k for k in range(20)])

    def test_invisible_pieces_beyond_the_widest_view_do_not_even_take_a_scratch_place(self):
        beyond = self.spread(900, 400)
        vis = [self.at(360 + k, a2=0xF506 + 8 * (k % 32)) for k in range(5)]
        out = self.actors_placed(beyond + vis)
        self.assertEqual(self.xs(out), [360 + k for k in range(5)])
        self.assertFalse(any(l.startswith("log ") for l in out))

    def test_both_directions_and_the_exact_edges_of_the_placed_view(self):
        # camera 601: the placement is 100 (see ref_left): the picture sits 100 px from the view's left edge; the view is [-100, 422) in screen x (320 + 202 - 100); a piece is kept while a pixel of it is within 8 px of the view
        for sx, shown in ((-141, False), (-140, False), (-139, True), (-120, True), (352, True), (429, True), (430, False), (600, False)):
            out = self.actors_placed([self.at(sx)])
            self.assertEqual(len(self.sprites(out)), 1 if shown else 0, sx)
        # the camera at the level's first column (left = 0): nothing left of the picture is presented, so nothing there is submitted (the host would refuse it as "virtual sprites not presented"); the right side holds the whole total
        out = self.actors_placed([self.at(-90), self.at(-40), self.piece(0x70)], cam=0)    # two dropped pieces left of the picture and one KEPT piece straddling the left edge (its part beside the raster is left of 0)
        self.assertEqual(self.xs(out), [], "left placement 0: the margin left of the picture has no width")
        self.assertEqual(self.xs(self.actors_placed([self.at(421), self.at(521)], cam=0)), [421, 521], "right of the picture the view reaches 320 + 202 - 0 = 522")
        # far from the level start the view is centred: left = margin = 101
        out = self.actors_placed([self.at(-100), self.at(-150), self.piece(0x80 + 321), self.at(430)], cam=2000)
        self.assertEqual(self.xs(out), [-100, 321], "view [-101, 421): -150 and 430 are beyond it")

    def test_partial_intersection_keeps_the_whole_piece_for_the_host_to_clip(self):
        self.assertEqual(self.xs(self.actors_placed([self.at(400)])), [400], "32 px piece at 400, 22 px of it inside the view")
        self.assertEqual(self.xs(self.actors_placed([self.at(-120)])), [-120], "12 px of it inside the view's left part")

    def test_a_kept_edge_piece_counts_by_its_part_beside_the_raster(self):
        # the game keeps a piece at screen 328 (wholly beside the raster) and one straddling the right edge (296..328: its part beside the raster is [320,328)): both are in the 21:9 view
        self.assertEqual(len(self.sprites(self.actors_placed([self.piece(0x1C0 + 8)]))), 1)
        self.assertEqual(len(self.sprites(self.actors_placed([self.at(296)]))), 1)
        # a kept piece inside the raster is the hardware's alone
        self.assertEqual(len(self.sprites(self.actors_placed([self.at(100)]))), 0)
        # no extension planned: the part beside the raster is shown by nobody
        self.assertEqual(self.sprites(self.actors_placed([self.piece(0x1C0 + 8), self.at(296), self.at(374), self.at(-60)], margin=0)), [], "no extension planned: nothing outside the picture is presented")

    def test_the_vertical_rows_are_the_rasters(self):
        for y, shown in ((96, False), (97, True), (95, False), (128 + 223, True), (128 + 224, False), (128 + 230, False)):
            out = self.actors_placed([self.at(374, y=y, size=0x0F)])   # 4 cells = 32 px tall; screen y = y - 128: the rows -31..223 intersect the 224 rows
            self.assertEqual(len(self.sprites(out)), 1 if shown else 0, y)

    def test_geometry_changes_never_drop_a_piece_the_new_view_shows(self):
        # the plan grows 16:9 (39) -> 21:9 (101) at frame 2: the placement was built for the old margin, so the widest placement of the new plan is used
        self.assertEqual(self.xs(self.actors_placed([self.at(400)], margin=39, margin2=101)), [400], "the grown plan shows it at once")
        # the plan shrinks 21:9 -> 16:9: that frame is still the old geometry; the next frame (exact 39 placement: [-39, 359)) does not show it
        self.assertEqual(self.xs(self.actors_placed([self.at(400)], margin=101, margin2=39)), [400])
        self.assertEqual(self.xs(self.actors_placed([self.at(400)], margin=39)), [], "stable 16:9 plan: x 400 is beyond [-39, 359) + 8")
        self.assertEqual(self.xs(self.actors_placed([self.at(340)], margin=39)), [340])
        # no extension at all (Original, 4:3): only the picture
        self.assertEqual(self.xs(self.actors_placed([self.at(340), self.at(-40)], margin=0)), [])
        # a transition frame whose candidates exceed the scratch reports the loss (a dropped candidate may have been visible there)
        out = self.actors_placed(self.spread(470, 160, per=8), margin=39, margin2=101)
        self.assertTrue(any(l.startswith("log castle:") for l in out))

    def test_a_stale_scene_never_leaves_pieces_behind(self):
        self.assertEqual(self.sprites(self.actors([self.piece(0x1F6)], scene_ok=False)), [])

    def test_maximum_density_keeps_the_games_first_64_visible_pieces_and_says_so(self):
        # 200 visible pieces at x 352..429: the scratch holds 128 in order, the host takes 64: the first 64 of the game's order; one log line says visible commands were not drawn
        dense = [self.at(352 + k % 78, a2=0xF506 + 8 * (k % 32), a0=0xD000 + 0x40 * (k % 8)) for k in range(200)]
        out = self.actors_placed(dense)
        self.assertEqual(self.xs(out), [352 + k % 78 for k in range(64)])
        self.assertEqual(len([l for l in out if l.startswith("log castle: visible")]), 1, "one line when the loss starts, not one per frame")
        exactly = self.actors_placed(dense[:64])
        self.assertEqual(len(self.sprites(exactly)), 64); self.assertFalse(any(l.startswith("log ") for l in exactly), "exactly the host's limit is not a loss")

    def test_a_full_scratch_prefers_pieces_the_current_plan_shows(self):
        # 140 pieces in the 32:9 band the 21:9 plan does not show, then 30 it does: the later, visible ones take the unlikely ones' places
        out = self.actors_placed(self.spread(470, 140, per=8) + [self.at(352 + k, a2=0xF506 + 8 * (k % 32), a0=0xD000 + 0x40 * (k % 8)) for k in range(30)])
        self.assertEqual(self.xs(out), [352 + k for k in range(30)])
        self.assertFalse(any(l.startswith("log ") for l in out))
        # 140 visible pieces with no unlikely one to evict: 64 are drawn, the rest is a reported loss
        out = self.actors_placed(self.spread(352, 140, per=60))
        self.assertEqual(len(self.sprites(out)), 64)
        self.assertTrue(any(l.startswith("log castle:") for l in out))

    def test_priority_bits_and_game_order_survive_the_selection(self):
        hooks = [self.at(360, attr=0x0090), self.at(700, attr=0x8091), self.at(372, attr=0x8092), self.at(-60, attr=0x0093)]
        out = self.sprites(self.actors_placed(hooks))
        self.assertEqual([(int(v[3]), v[2]) for v in out], [(360, "1"), (372, "2"), (-60, "1")], "x 700 is not presented; the others keep the game's order and their own priority layers")

    def test_the_provider_logs_only_with_the_declared_capability_in_every_package(self):
        # The mock host does not gate capabilities; the real host DISABLES a mod that calls host.log without `host.log`. Every Castle package ships the same provider, so every one must declare it.
        uses_log = "h->log(" in (PROJECT / "src/provider.c").read_text()
        self.assertTrue(uses_log, "the shared provider reports lost visible commands through host.log")
        for name in ("widescreen-practice", "activation-16x9", "activation-21x9"):
            manifest = tomllib.loads((ROOT / "patches/genesis/castle-of-illusion" / name / "mod.toml").read_text())
            self.assertIn("host.log", manifest["capabilities"]["required"], name)

    def test_pieces_live_one_frame_and_are_bounded(self):
        hooks = [self.piece(0x1F6 + k % 40, a2=0xF506 + 8 * (k % 32)) for k in range(70)]
        out = self.actors(hooks)
        self.assertEqual(len(self.sprites(out)), 64, "at most the host's 64 commands per frame (GENESIS_VSPRITE_MAX), the first 64 of the game's order")
        self.assertTrue(any(l.startswith("log castle: visible virtual sprites exceeded") for l in out), "a visible piece the host's budget cannot take is reported, never lost silently")
        ram = Ram(cam=100)
        lines = ["init"] + self.load(ram) + ["pad 0", "margin 101", "frame 1"] + self.piece(0x1F6) + ["phase frame-end", "phase render", "frame 2", "phase frame-end", "phase render"]
        out = self.run_script(lines)
        self.assertEqual(len(self.sprites(out)), 1, "a piece collected in one frame is served once, never carried to the next")

    def test_a_restored_state_starts_with_no_pieces(self):
        ram = Ram(cam=100)
        first = self.run_script(["init"] + self.load(ram) + ["pad 0", "margin 101", "frame 1"] + self.piece(0x1F6) + ["phase frame-end", "save"])
        blob = next(l for l in first if l.startswith("state")).split()[1:]
        out = self.run_script(["init"] + self.load(ram) + ["pad 0", "margin 101", "frame 2", "load " + " ".join(blob), "phase render"])
        self.assertEqual(self.sprites(out), [], "nothing is drawn from before the restore")

    def test_far_coordinates_are_not_submitted(self):
        self.assertEqual(self.sprites(self.actors([self.piece(0x7000)])), [], "x beyond the transport's coordinate limit")

    def test_rejects_a_corrupt_state(self):
        out = self.run_script(["init", "load 00 00 00 05 00 00 00 00 00 00 00 00 00 00 00 00", "echo done"])
        self.assertIn("load 1", out)


if __name__ == "__main__":
    unittest.main()
