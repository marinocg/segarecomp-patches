"""Sonic 3 & Knuckles ABI 2 widescreen provider (SEG-152-T016): the adaptive picture placement and the scenery windows built for it, on FABRICATED work RAM. No ROM, no game data: the synthetic layout, chunk and block
tables below only have the SHAPE the provider reads. The provider source (patches/genesis/sonic-3-and-knuckles/native-widescreen-abi2/src/provider.c) is compiled INTO the harness (so its static functions are exercised
directly) with AddressSanitizer and UndefinedBehaviorSanitizer, against the product's ABI 2 header and a mock render API that records the windows, the per-row mask and the per-row origin the provider submits.

What is checked: (1) `placement` is a pure function of the camera with the left / centred / right endpoints, monotone, never faster than the ramp bound, and the plain narrow-level rule; (2) `level_left_px`: left at the
first camera position, right at the layout's last, centred outside the placement scope and for a layout the provider cannot read, and always centred in the baseline build option (S3K_PLACEMENT 0); (3) for every placement and
every scroll shape (uniform, two bands with different registered plane multiples, a per-line own-plane mask) each line that is not answered by the VDP's own plane has every cell it asks inside a window with the word of
that world cell, windows respect the host's limits, and nothing is read out of bounds (sanitizers). Needs the product's SDK headers and a C compiler: set SEGARECOMP_SDK_DIR (the product's `platforms` directory) and
optionally SEGARECOMP_CC; otherwise skipped with that reason, never silently passed (CI sets SEGARECOMP_REQUIRE_EXEC=1)."""
import os, pathlib, subprocess, tempfile, unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
PROVIDER = ROOT / "patches/genesis/sonic-3-and-knuckles/native-widescreen-abi2/src/provider.c"
SDK, CC = os.environ.get("SEGARECOMP_SDK_DIR"), os.environ.get("SEGARECOMP_CC", "cc")
if os.environ.get("SEGARECOMP_REQUIRE_EXEC") == "1" and not SDK:
    raise RuntimeError("SEGARECOMP_REQUIRE_EXEC=1 but SEGARECOMP_SDK_DIR is not set: the Sonic 3 & Knuckles placement tests would be skipped")

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
static void put16(unsigned a, unsigned v) { ram[a] = (uint8_t)(v >> 8); ram[a + 1U] = (uint8_t)v; }

/* a deterministic synthetic world: fg `fgw` x 4 chunks, bg 8 x 4 chunks; every chunk id, block and name word is a function of its index */
static void make_world(unsigned fgw) {
  unsigned i, row;
  memset(ram, 0, sizeof ram);
  put16(S3K_LAYOUT, fgw); put16(S3K_LAYOUT + 2U, 8U); put16(S3K_LAYOUT + 4U, 4U); put16(S3K_LAYOUT + 6U, 4U);
  for (row = 0U; row < 4U; ++row) {
    put16(S3K_ROWPTR + row * 4U, 0x8100U + row * 0x100U); put16(S3K_ROWPTR + row * 4U + 2U, 0x8600U + row * 0x100U);
    for (i = 0U; i < 0x100U; ++i) { ram[0x8100U + row * 0x100U + i] = (uint8_t)((i * 7U + row * 3U) % 61U); ram[0x8600U + row * 0x100U + i] = (uint8_t)((i * 5U + row * 11U) % 61U); }
  }
  for (i = 0U; i < 64U * 0x40U; ++i) put16(S3K_CHUNKS + i * 2U, ((i * 29U + 5U) & 0x3FFU));
  for (i = 0U; i < 0x400U * 4U; ++i) put16(S3K_BLOCKS + i * 2U, ((i * 31U + 17U) & 0x7FFFU));
}

/* ---- a scroll shape: per line the camera of the foreground, the background scroll and its registered plane multiple ---- */
typedef struct { int bgscroll; int kx; } Band;
static Sonic3kFrame fr;
static SegaGenesisRenderApi api;

static int run_case(const char *name, unsigned plane, int cam, const Band *bands, const int *band_end, int nbands, unsigned left_px, unsigned margin_px, int expect_masked, const unsigned char *own) {
  unsigned l, masked = 0U, checked = 0U, any = 0U, anyd = 0U;
  int b = 0, rc;
  uint8_t mask[28];
  memset(&fr, 0, sizeof fr); memset(&api, 0, sizeof api);
  nwins = 0; bad_limit = 0; have_origin[0] = have_origin[1] = 0; have_mask[0] = have_mask[1] = 0; memset(gmask, 0, sizeof gmask);
  api.scenery_window = m_window; api.scenery_row_origin = m_origin; api.scenery_generic_rows = m_rows;
  fr.ram = ram; fr.height = 224U;
  fr.wide[0] = u16(ram, S3K_LAYOUT); fr.wide[1] = 8U; fr.high[0] = 4U; fr.high[1] = 4U;
  fr.vs[0] = 24; fr.vs[1] = 40;
  for (l = 0U; l < 224U; ++l) {
    while (b + 1 < nbands && (int)l >= band_end[b]) ++b;
    fr.hs[l][0] = -cam; fr.off[l][0] = cam; fr.vsh[l][0] = fr.vs[0];
    fr.hs[l][1] = bands[b].bgscroll; fr.off[l][1] = -bands[b].bgscroll + 512 * bands[b].kx; fr.kx[l] = bands[b].kx; fr.vsh[l][1] = fr.vs[1];
    fr.bgy[l] = (int)l + fr.vs[1];
    fr.own_plane[l][plane] = own != NULL ? own[l] : 0U;
  }
  rc = build_plane_windows(&api, &fr, plane, left_px, margin_px, mask, &any, &anyd);
  if (rc != 0 || bad_limit) { printf("FAIL %s rc=%d bad_limit=%d\n", name, rc, bad_limit); return 1; }
  if (any != 0U) { for (l = 0U; l < 28U; ++l) gmask[plane][l] = mask[l]; have_mask[plane] = 1; }
  for (l = 0U; l < 224U; ++l) {
    const int right_px = (int)(2U * margin_px - left_px);
    const int row = floor_div((int)l + fr.vsh[l][plane], 8);
    const int wy = plane == 0U ? (int)l + fr.vs[0] : fr.bgy[l];
    int side, c;
    if (have_mask[plane] && ((gmask[plane][l >> 3] >> (l & 7U)) & 1U) != 0U) { ++masked; continue; }
    if (fr.own_plane[l][plane] != 0U) { printf("FAIL %s: own-plane line %u is not in the mask\n", name, l); return 1; }
    for (side = 0; side < 2; ++side) {
      const int lo = side == 0 ? floor_div(-(int)left_px - fr.hs[l][plane], 8) : floor_div(320 - fr.hs[l][plane], 8);
      const int hi = side == 0 ? (left_px != 0U ? floor_div(-1 - fr.hs[l][plane], 8) : lo - 1) : (right_px != 0 ? floor_div(319 + right_px - fr.hs[l][plane], 8) : lo - 1);
      for (c = lo; c <= hi; ++c) {
        int found = 0, i;
        const int d = g_delta[plane][l];   /* what render_frame submits as the per-row origin when any is non-zero */
        for (i = 0; i < nwins && !found; ++i) {
          const Win *w = &wins[i];
          const int cx = c + d - w->x0, cy = row - w->y0;
          if (w->plane == (int)plane && cx >= 0 && cx < (int)w->cols && cy >= 0 && cy < (int)w->rows) {
            const unsigned want = world_cell(&fr, plane, c * 8 + fr.hs[l][plane] + fr.off[l][plane], wy);
            if (w->words[(unsigned)cy * w->cols + (unsigned)cx] != (uint16_t)want) { printf("FAIL %s: line %u cell %d word\n", name, l, c); return 1; }
            found = 1;
          }
        }
        if (!found) { printf("FAIL %s: line %u asks cell %d that no window holds\n", name, l, c); return 1; }
        ++checked;
      }
    }
  }
  printf("OK %s masked=%u checked=%u windows=%d\n", name, masked, checked, nwins);
  if (expect_masked == 0 && masked != 0U) { printf("FAIL %s: %u lines masked, none expected\n", name, masked); return 1; }
  if (expect_masked == 1 && masked == 0U) { printf("FAIL %s: nothing masked\n", name); return 1; }
  return 0;
}

static void set_scene(unsigned zone, unsigned act, unsigned cam) { ram[S3K_ZONE] = (uint8_t)zone; ram[S3K_ZONE + 1U] = (uint8_t)act; put16(S3K_CAMX, cam); }

int main(void) {
  static const int margins[] = {39, 101, 238};
  static const int ranges[] = {12096, 7871, 2240, 832, 2 * 238 - 1, 2 * 238, 0, 1};
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
        if (placement(0, r, m) != 0 || placement(r, r, m) != 2 * m || placement(r / 2, r, m) != m) { printf("FAIL placement endpoints range=%d m=%d\n", r, m); ++fails; }
      } else {
        for (cam = 0; cam <= r; ++cam) if (placement(cam, r, m) != (cam < m ? cam : m)) { printf("FAIL narrow rule cam=%d range=%d m=%d\n", cam, r, m); ++fails; break; }
      }
    }
  printf("OK placement\n");
  /* level_left_px: adaptive from the camera and the layout's end in the verified scenes only; every other scene id and an unreadable layout stay centred */
  make_world(97U);   /* 97 chunks: range 97 * 128 - 320 = 12096 */
  {
    static const unsigned char shifting[][2] = {{0x02, 0}, {0x02, 1}, {0x08, 0}, {0x0B, 1}};
    unsigned zone, act, i, count = 0U;
    for (zone = 0U; zone < 256U; ++zone)
      for (act = 0U; act < 256U; ++act) {   /* exhaustive over both scene bytes */
        int want = 0;
        unsigned at_start, at_end;
        for (i = 0U; i < sizeof(shifting) / sizeof(shifting[0]); ++i) want = want || (zone == shifting[i][0] && act == shifting[i][1]);
        if (S3K_PLACEMENT == 0) want = 0;
        set_scene(zone, act, 0U); at_start = level_left_px(ram, 238U);
        set_scene(zone, act, 12096U); at_end = level_left_px(ram, 238U);
        if (at_start != (want ? 0U : 238U) || at_end != (want ? 476U : 238U)) { printf("FAIL scope zone=%u act=%u start=%u end=%u\n", zone, act, at_start, at_end); ++fails; zone = 255U; break; }
        count += (unsigned)want;
      }
    if (fails == 0 && count != (S3K_PLACEMENT == 0 ? 0U : 4U)) { printf("FAIL scope count %u\n", count); ++fails; }
  }
  if (S3K_PLACEMENT != 0) {
    set_scene(2U, 1U, 6048U);
    if (level_left_px(ram, 238U) != 238U) { printf("FAIL middle not centred\n"); ++fails; }
    set_scene(2U, 1U, 20000U);
    if (level_left_px(ram, 238U) != 476U) { printf("FAIL camera past the layout is not clamped to right aligned\n"); ++fails; }
    set_scene(2U, 1U, 0U); put16(S3K_LAYOUT, 0U);   /* an unreadable layout: the verified-boundary-not-obtainable fallback */
    if (level_left_px(ram, 238U) != 238U) { printf("FAIL zero-width layout not centred\n"); ++fails; }
    put16(S3K_LAYOUT, 0x101U);
    if (level_left_px(ram, 238U) != 238U) { printf("FAIL oversize layout not centred\n"); ++fails; }
  }
  printf("OK level_left_px\n");
  /* windows for every placement at every margin and several scroll shapes, with the camera where the placement puts the picture (start, middle, end of a 20-chunk foreground) */
  for (mi = 0; mi < 3; ++mi) {
    unsigned p;
    m = margins[mi];
    make_world(20U);
    for (p = 0U; p <= 2U; ++p) {
      const unsigned lp = p == 0U ? 0U : p == 1U ? (unsigned)m : (unsigned)(2 * m);
      const int cam_at = p == 0U ? 0 : p == 1U ? 1000 : 2240;   /* layout 2560 px: the camera's last value is 2240 */
      char nm[96];
      unsigned char own[224];
      { const Band b1[] = {{-300, 0}}; const int e1[] = {224}; snprintf(nm, sizeof nm, "uniform m=%d left=%u", m, lp); fails += run_case(nm, 0U, cam_at, b1, e1, 1, lp, (unsigned)m, 0, NULL); fails += run_case(nm, 1U, cam_at, b1, e1, 1, lp, (unsigned)m, 0, NULL); }
      { const Band b2[] = {{-300, 0}, {-700, 1}}; const int e2[] = {104, 224}; snprintf(nm, sizeof nm, "two bands m=%d left=%u", m, lp); fails += run_case(nm, 1U, cam_at, b2, e2, 2, lp, (unsigned)m, 0, NULL); }
      { const Band b1[] = {{-300, 0}}; const int e1[] = {224}; unsigned i; for (i = 0U; i < 224U; ++i) own[i] = (unsigned char)(i >= 96U && i < 130U);
        snprintf(nm, sizeof nm, "own-plane lines m=%d left=%u", m, lp); fails += run_case(nm, 1U, cam_at, b1, e1, 1, lp, (unsigned)m, 1, own); }
    }
  }
  printf("FAILS %d\n", fails);
  return fails != 0;
}
'''


@unittest.skipUnless(SDK, "set SEGARECOMP_SDK_DIR to the product's platforms directory")
class Sonic3kPlacement(unittest.TestCase):
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
        for part in ("OK placement", "OK level_left_px", "OK own-plane lines m=238 left=476"):
            self.assertIn(part, out)

    def test_baseline_build_is_centred(self):
        out = self.build_run("baseline", ["-DS3K_PLACEMENT=0"])
        self.assertIn("OK level_left_px", out)


class Source(unittest.TestCase):
    """Cheap text checks that run everywhere (no compiler): the shipped build is adaptive and the baseline option exists."""
    SRC = PROVIDER.read_text()

    def test_shipped_default_is_adaptive_and_baseline_is_selectable(self):
        self.assertIn("#ifndef S3K_PLACEMENT\n#define S3K_PLACEMENT 1", self.SRC)
        self.assertIn("r->view_left(left_px, margin_px)", self.SRC)

    def test_no_guest_memory_write(self):
        self.assertNotIn("->write(", self.SRC)
        self.assertNotIn("memory.write", (PROVIDER.parent.parent / "mod.toml").read_text())


if __name__ == "__main__":
    unittest.main()
