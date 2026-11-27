"""Sonic the Hedgehog ABI 2 widescreen provider (SEG-152-T014): the adaptive picture placement and the scenery windows it needs, on FABRICATED work RAM. No ROM, no game data: the synthetic layout, chunk and block
tables below only have the SHAPE the provider reads. The provider source (patches/genesis/sonic-1/native-widescreen-abi2/src/provider.c) is compiled INTO the harness (so its static functions are exercised directly) with
AddressSanitizer and UndefinedBehaviorSanitizer, against the product's ABI 2 header and a mock render API that records the windows, the per-row mask and the per-row origin the provider submits.

What is checked: (1) `placement` is a pure function of the camera with the left / centred / right endpoints, monotone, never faster than the ramp bound and the plain narrow-level rule; (2) the baseline build option
(S1_PLACEMENT 0) is always centred; (3) for every placement and every scroll shape (uniform, two far-apart bands, many bands that no two windows can hold) each line that is not answered by the VDP's own plane has
every cell it asks inside a window with the word of that world cell, windows respect the host's limits, and nothing is read out of bounds (sanitizers). Needs the product's SDK headers and a C compiler: set
SEGARECOMP_SDK_DIR (the product's `platforms` directory) and optionally SEGARECOMP_CC; otherwise skipped with that reason, never silently passed (CI sets SEGARECOMP_REQUIRE_EXEC=1)."""
import os, pathlib, subprocess, tempfile, unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
PROVIDER = ROOT / "patches/genesis/sonic-1/native-widescreen-abi2/src/provider.c"
SDK, CC = os.environ.get("SEGARECOMP_SDK_DIR"), os.environ.get("SEGARECOMP_CC", "cc")
if os.environ.get("SEGARECOMP_REQUIRE_EXEC") == "1" and not SDK:
    raise RuntimeError("SEGARECOMP_REQUIRE_EXEC=1 but SEGARECOMP_SDK_DIR is not set: the Sonic 1 placement tests would be skipped")

HARNESS = r'''
#include "PROVIDER"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* ---- the mock render API: what the provider submitted for one plane ---- */
typedef struct { int plane; int32_t x0, y0; uint32_t cols, rows; uint16_t words[MAX_COLS * MAX_WIN_ROWS]; } Win;
static Win wins[8]; static int nwins, bad_limit;
static int16_t origin[2][448]; static int have_origin[2];
static uint8_t gmask[2][56]; static int have_mask[2];

static int m_window(uint32_t plane, int32_t x0, int32_t y0, uint32_t cols, uint32_t rows, const uint16_t *w) {
  int n = 0, i;
  for (i = 0; i < nwins; ++i) if (wins[i].plane == (int)plane) ++n;
  if (n >= 2 || cols == 0U || rows == 0U || cols > MAX_COLS || rows > MAX_WIN_ROWS || cols * rows > 4096U) bad_limit = 1;
  wins[nwins].plane = (int)plane; wins[nwins].x0 = x0; wins[nwins].y0 = y0; wins[nwins].cols = cols; wins[nwins].rows = rows;
  memcpy(wins[nwins].words, w, (size_t)cols * rows * 2U); ++nwins; return 0; }
static int m_origin(uint32_t plane, const int16_t *d, uint32_t rows, uint32_t bytes) { if (bytes != rows * 2U || plane > 1U || rows > 448U) bad_limit = 1; memcpy(origin[plane], d, rows * 2U); have_origin[plane] = 1; return 0; }
static int m_rows(uint32_t plane, const uint8_t *m, uint32_t rows, uint32_t bytes) {
  if (plane > 1U || bytes != (rows + 7U) / 8U || rows == 0U || rows > 448U) bad_limit = 1;
  memcpy(gmask[plane], m, bytes); have_mask[plane] = 1;
  if ((rows & 7U) != 0U && (m[bytes - 1U] >> (rows & 7U)) != 0U) bad_limit = 1;   /* padding bits must be zero */
  return 0; }

static uint8_t ram[65536];

/* a deterministic synthetic world: every chunk id 1..0x52, every block, every name word is a function of its index */
static void make_world(void) {
  unsigned i, row;
  memset(ram, 0, sizeof ram);
  for (row = 0U; row < S1_LAYOUT_ROWS; ++row)
    for (i = 0U; i < 0x80U; ++i) ram[S1_LAYOUT + row * 0x80U + i] = (uint8_t)(1U + ((i * 7U + row * 3U) % S1_CHUNK_COUNT));
  for (i = 0U; i < S1_CHUNK_COUNT * 0x100U; ++i) { const unsigned wv = (i * 29U + 5U) & 0x3FFU; ram[S1_CHUNKS + i * 2U] = (uint8_t)(wv >> 8); ram[S1_CHUNKS + i * 2U + 1U] = (uint8_t)wv; }
  for (i = 0U; i < 0x400U * 4U; ++i) { const unsigned wv = (i * 31U + 17U) & 0x7FFFU; ram[S1_BLOCKS + i * 2U] = (uint8_t)(wv >> 8); ram[S1_BLOCKS + i * 2U + 1U] = (uint8_t)wv; }
}

/* ---- a scroll shape: per line the horizontal scroll of the plane, the world offset (a multiple of 512 from -hscroll) and the vertical scroll ---- */
typedef struct { int hs; int mult; } Band;
static int run_case(const char *name, unsigned plane, const Band *bands, const int *band_end, int nbands, unsigned left_px, unsigned margin_px, int expect_masked, int expect_none) {
  static Sonic1Frame fr;
  static SegaGenesisRenderApi api;
  unsigned l, masked = 0U, checked = 0U;
  int b = 0, rc, rmin;
  memset(&fr, 0, sizeof fr); memset(&api, 0, sizeof api);
  nwins = 0; bad_limit = 0; have_origin[0] = have_origin[1] = 0; have_mask[0] = have_mask[1] = 0; memset(gmask, 0, sizeof gmask);
  api.scenery_window = m_window; api.scenery_row_origin = m_origin; api.scenery_generic_rows = m_rows;
  fr.camy = 0x120; fr.bgy = 0x58;
  for (l = 0U; l < 224U; ++l) {
    while (b + 1 < nbands && (int)l >= band_end[b]) ++b;
    fr.hs[plane][l] = bands[b].hs;
    (plane == 0U ? fr.off_fg : fr.off_bg)[l] = -bands[b].hs + 512 * bands[b].mult;
    fr.vs[plane][l] = plane == 0U ? fr.camy : fr.bgy;
  }
  rc = build_plane_windows(&api, &fr, ram, plane, 224U, left_px, margin_px);
  if (expect_none) { printf("%s rc=%d\n", name, rc); return rc != 0 ? 0 : 1; }
  if (rc != 0 || bad_limit) { printf("FAIL %s rc=%d bad_limit=%d\n", name, rc, bad_limit); return 1; }
  rmin = floor_div(fr.vs[plane][0], 8);
  for (l = 0U; l < 224U; ++l) {
    const int *off = plane == 0U ? fr.off_fg : fr.off_bg;
    const int k = (fr.hs[plane][l] + off[l]) / 8;
    const int row = floor_div((int)l + fr.vs[plane][l], 8);
    const int wrow = row + ((plane == 0U ? fr.camy : fr.bgy) - fr.vs[plane][0]) / 8;
    const int right_px = (int)(2U * margin_px - left_px);
    int side, c;
    if (have_mask[plane] && ((gmask[plane][l >> 3] >> (l & 7U)) & 1U) != 0U) { ++masked; continue; }
    if (!have_origin[plane] || origin[plane][l] != k) { printf("FAIL %s: line %u origin %d != %d\n", name, l, have_origin[plane] ? origin[plane][l] : 9999, k); return 1; }
    for (side = 0; side < 2; ++side) {
      const int lo = side == 0 ? floor_div(-(int)left_px - fr.hs[plane][l], 8) : floor_div(320 - fr.hs[plane][l], 8);
      const int hi = side == 0 ? (left_px != 0U ? floor_div(-1 - fr.hs[plane][l], 8) : lo - 1) : (right_px != 0 ? floor_div(319 + right_px - fr.hs[plane][l], 8) : lo - 1);
      for (c = lo; c <= hi; ++c) {
        int found = 0, i;
        for (i = 0; i < nwins && !found; ++i) {
          const Win *w = &wins[i];
          const int cx = c + k - w->x0, cy = row - w->y0;
          if (w->plane == (int)plane && cx >= 0 && cx < (int)w->cols && cy >= 0 && cy < (int)w->rows) {
            const int want = world_cell(ram, plane, c + k, wrow);
            if (want < 0 || w->words[(unsigned)cy * w->cols + (unsigned)cx] != (uint16_t)want) { printf("FAIL %s: line %u cell %d word\n", name, l, c); return 1; }
            found = 1;
          }
        }
        if (!found) { printf("FAIL %s: line %u asks cell %d (world %d row %d) that no window holds\n", name, l, c, c + k, row - rmin); return 1; }
        ++checked;
      }
    }
  }
  printf("OK %s masked=%u checked=%u windows=%d\n", name, masked, checked, nwins);
  if (expect_masked == 0 && masked != 0U) { printf("FAIL %s: %u lines masked, none expected\n", name, masked); return 1; }
  if (expect_masked == 1 && masked == 0U) { printf("FAIL %s: nothing masked, the shape cannot fit two windows\n", name); return 1; }
  return 0;
}

int main(void) {
  static const int margins[] = {39, 101, 238};
  static const int ranges[] = {9407, 7871, 10592, 600, 2 * 238 - 1, 2 * 238, 0, 1};
  int fails = 0, mi, ri, cam, m, r;
  /* placement: endpoints, purity, monotone, ramp bound, narrow rule */
  for (mi = 0; mi < 3; ++mi)
    for (ri = 0; ri < 8; ++ri) {
      int prev = -1, prev_cam = 0;
      m = margins[mi]; r = ranges[ri];
      for (cam = -5; cam <= r + 5; ++cam) {
        const int p = placement(cam, r, m);
        if (p != placement(cam, r, m) || p < 0 || p > 2 * m) { printf("FAIL placement range cam=%d range=%d m=%d p=%d\n", cam, r, m, p); ++fails; break; }
        if (r >= 2 * m && prev >= 0) {
          if (p < prev) { printf("FAIL placement not monotone cam=%d range=%d m=%d\n", cam, r, m); ++fails; break; }
          if (cam > 0 && cam <= r && p - prev > (cam - prev_cam + RAMP_DEN - 1) / RAMP_DEN + 1) { printf("FAIL placement faster than the ramp bound cam=%d range=%d m=%d step=%d\n", cam, r, m, p - prev); ++fails; break; }
        }
        prev = p; prev_cam = cam;
      }
      if (r >= 2 * m) {
        if (placement(0, r, m) != 0 || placement(r, r, m) != 2 * m || placement(r / 2, r, m) != m) { printf("FAIL placement endpoints range=%d m=%d: %d %d %d\n", r, m, placement(0, r, m), placement(r, r, m), placement(r / 2, r, m)); ++fails; }
      } else {
        for (cam = 0; cam <= r; ++cam) if (placement(cam, r, m) != (cam < m ? cam : m)) { printf("FAIL narrow rule cam=%d range=%d m=%d\n", cam, r, m); ++fails; break; }
      }
    }
  printf("OK placement\n");
  /* level_left_px: adaptive from the camera and the right limit; an unverifiable right limit stays centred */
  make_world();
  ram[S1_CAMX] = 0; ram[S1_CAMX + 1] = 0; ram[S1_LIMRIGHT] = (uint8_t)(9407 >> 8); ram[S1_LIMRIGHT + 1] = (uint8_t)(9407 & 255);
  if (S1_PLACEMENT == 0) { if (level_left_px(ram, 238U) != 238U) { printf("FAIL baseline build is not centred\n"); ++fails; } }
  else {
    if (level_left_px(ram, 238U) != 0U) { printf("FAIL level start not left aligned\n"); ++fails; }
    ram[S1_CAMX] = (uint8_t)(9407 >> 8); ram[S1_CAMX + 1] = (uint8_t)(9407 & 255);
    if (level_left_px(ram, 238U) != 476U) { printf("FAIL level end not right aligned\n"); ++fails; }
    ram[S1_ZONE] = 1U; ram[S1_ZONE + 1U] = 0U;   /* a scenery act whose boundaries are not verified: centred */
    if (level_left_px(ram, 238U) != 238U) { printf("FAIL unverified zone not centred\n"); ++fails; }
    ram[S1_ZONE] = 0U; ram[S1_ZONE + 1U] = 3U;
    if (level_left_px(ram, 238U) != 238U) { printf("FAIL unverified act not centred\n"); ++fails; }
    ram[S1_ZONE] = 0U; ram[S1_ZONE + 1U] = 2U;
    if (level_left_px(ram, 238U) != 476U) { printf("FAIL green hill act 3 not adaptive\n"); ++fails; }
    ram[S1_LIMRIGHT] = 0xFFU; ram[S1_LIMRIGHT + 1] = 0xFFU;   /* a right limit the world cannot hold: centred */
    if (level_left_px(ram, 238U) != 238U) { printf("FAIL unverifiable right limit not centred\n"); ++fails; }
    ram[S1_LIMRIGHT] = 0U; ram[S1_LIMRIGHT + 1] = 0U;
    if (level_left_px(ram, 238U) != 238U) { printf("FAIL zero right limit not centred\n"); ++fails; }
  }
  printf("OK level_left_px\n");
  /* windows for every placement at every margin and several scroll shapes */
  for (mi = 0; mi < 3; ++mi) {
    unsigned p;
    m = margins[mi];
    for (p = 0U; p <= 2U; ++p) {
      const unsigned lp = p == 0U ? 0U : p == 1U ? (unsigned)m : (unsigned)(2 * m);
      char nm[96];
      { const Band b1[] = {{-1000, 2}}; const int e1[] = {224}; snprintf(nm, sizeof nm, "uniform m=%d left=%u", m, lp); fails += run_case(nm, 0U, b1, e1, 1, lp, (unsigned)m, 0, 0); fails += run_case(nm, 1U, b1, e1, 1, lp, (unsigned)m, 0, 0); }
      { const Band b2[] = {{-700, 1}, {-3000, 6}}; const int e2[] = {104, 224}; snprintf(nm, sizeof nm, "two bands m=%d left=%u", m, lp); fails += run_case(nm, 1U, b2, e2, 2, lp, (unsigned)m, -1, 0); }
      { const Band b3[] = {{-700, 1}, {-1300, 3}, {-2100, 5}, {-2900, 7}, {-3700, 9}, {-4500, 11}}; const int e3[] = {40, 80, 120, 160, 200, 224};
        snprintf(nm, sizeof nm, "six bands m=%d left=%u", m, lp); fails += run_case(nm, 1U, b3, e3, 6, lp, (unsigned)m, -1, 0); }
    }
  }
  /* a shape no two windows hold at the widest view must be answered partly by the VDP's own plane, never fail or read out of bounds */
  { const Band b3[] = {{-700, 1}, {-1900, 3}, {-3100, 5}, {-4300, 7}, {-5500, 9}, {-6700, 11}}; const int e3[] = {40, 80, 120, 160, 200, 224}; fails += run_case("six far bands m=238 centred", 1U, b3, e3, 6, 238U, 238U, 1, 0); }
  printf("FAILS %d\n", fails);
  return fails != 0;
}
'''


@unittest.skipUnless(SDK, "set SEGARECOMP_SDK_DIR to the product's platforms directory")
class Sonic1Placement(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = pathlib.Path(tempfile.mkdtemp())
        src = HARNESS.replace('"PROVIDER"', f'"{PROVIDER}"')
        (cls.tmp / "harness.c").write_text(src)
        cls.inc = ["-I", str(pathlib.Path(SDK) / "genesis/sdk"), "-I", str(pathlib.Path(SDK) / "sdk")]

    @classmethod
    def tearDownClass(cls):
        import shutil
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def build_run(self, name, extra):
        exe = self.tmp / name
        flags = ["-std=c11", "-Wall", "-Wextra", "-pedantic", "-Werror", "-g", "-fsanitize=address,undefined", "-fno-sanitize-recover=all", "-DSEGA_MOD_TARGET_PLATFORM=1", "-DSEGA_MOD_TARGET_ABI_MAJOR=2U"] + self.inc + extra
        r = subprocess.run([CC, *flags, "-o", str(exe), str(self.tmp / "harness.c")], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, "the provider does not compile as strict C11 with the harness:\n" + r.stderr)
        run = subprocess.run([str(exe)], capture_output=True, text=True, timeout=300)
        self.assertEqual(run.returncode, 0, run.stdout[-2000:] + run.stderr[-2000:])
        self.assertFalse([ln for ln in run.stdout.splitlines() if ln.startswith("FAIL ")], run.stdout[-2000:])
        self.assertIn("FAILS 0", run.stdout)
        return run.stdout

    def test_adaptive_build(self):
        out = self.build_run("adaptive", [])
        for part in ("OK placement", "OK level_left_px", "OK six far bands"):
            self.assertIn(part, out)

    def test_baseline_build_is_centred(self):
        out = self.build_run("baseline", ["-DS1_PLACEMENT=0"])
        self.assertIn("OK level_left_px", out)


class Source(unittest.TestCase):
    """Cheap text checks that run everywhere (no compiler): the shipped build is adaptive and the baseline option exists."""
    SRC = PROVIDER.read_text()

    def test_shipped_default_is_adaptive_and_baseline_is_selectable(self):
        self.assertIn("#ifndef S1_PLACEMENT\n#define S1_PLACEMENT 1", self.SRC)
        self.assertIn("r->view_left(left_px, margin_px)", self.SRC)
        self.assertIn("k_placement_acts[6] = {0x07, 0x00, 0x00, 0x00, 0x00, 0x00}", self.SRC)

    def test_no_guest_memory_write_and_no_state(self):
        self.assertNotIn("->write(", self.SRC)
        self.assertNotIn("memory.write", (PROVIDER.parent.parent / "mod.toml").read_text())


if __name__ == "__main__":
    unittest.main()
