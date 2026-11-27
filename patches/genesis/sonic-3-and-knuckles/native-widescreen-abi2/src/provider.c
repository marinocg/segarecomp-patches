/*
 * Sonic 3 & Knuckles (Genesis, lock-on composite) native widescreen provider for the schema 3 / native ABI 2 SDK (segarecomp_mod_genesis.h, minor 3): the port of the ABI 1 provider of
 * patches/genesis/sonic-3-and-knuckles/native-widescreen with the SAME game knowledge, constants and verification logic (SEG-152-T011, ADR 0320). Bound by its package to ONE exact image (the 4 MiB
 * S&K + Sonic 3 composite, built as a declared lock-on cartridge); identities are enforced by the package, not here.
 *
 * What changes is only how the answers are delivered: the ABI 1 per-cell scenery callback becomes bounded scenery WINDOWS built from the exact-frame view, the per-line background plane multiple
 * (the ABI 1 `bg_register` result, a whole number of 512 px plane widths) becomes the per-row origin delta of the product (`scenery_row_origin`, minor 3), the lines the ABI 1 provider answered from
 * the VDP's own plane become the per-row generic mask (minor 2), the HUD overlay becomes one RGBA bitmap, and a frame the provider does not serve is refused with the ABI 1 diagnostic reason (a
 * refusal, never a fault). The provider is an exact-frame provider (capability frame.vdp): `render` runs once per produced frame against the frame's own copies.
 *
 * Cross-frame state (ADR 0320 decision 3): the ABI 1 provider kept the registered plane multiples of the previous presented frame (`g_prev_kx/g_prev_ky`). They are NOT a pure cache: the previous-frame
 * tie-break term changes which multiple wins in some real scenes (clearing them before every frame changed the accepted lines of Carnival Night Zone Act 1 in the local comparison). They are therefore
 * ESSENTIAL state: kept by `render` exactly as the ABI 1 provider kept them, and serialized through `state.mod` (448 bytes) so that save/load and rewind restore the seed of the saved moment.
 */
#include <segarecomp_mod_genesis.h>

#define S3K_CHUNKS 0x0000U      /* 128x128 px chunks: 0x80 bytes each = 8x8 block words (16x16 px blocks) */
#define S3K_CHUNK_BYTES 0x80U
#define S3K_LAYOUT 0x8000U      /* layout header: words fg width, bg width (chunks), fg height, bg height (rows) */
#define S3K_ROWPTR 0x8008U      /* then per row r: word fg row pointer, word bg row pointer (work-RAM offsets of one byte per chunk) */
#define S3K_MAX_ROWS 32U
#define S3K_BLOCKS 0x9000U      /* 16x16 blocks: 8 bytes (4 name-table words TL TR BL BR) indexed by the low 10 bits of a chunk word */
#define S3K_BLOCK_MASK 0x3FFU
#define S3K_GAMEMODE 0xF600U    /* byte: 0x0C = running level */
#define S3K_ZONE 0xFE10U        /* bytes: zone, act */
#define S3K_HSCROLL 0xE000U     /* per-line scroll buffer copied to the VDP at VBlank: 224 x (fg word, bg word), signed */
#define S3K_HSCROLL_LINES 224U
#define S3K_VSCROLL 0xF616U     /* words: foreground and background vertical scroll the VBlank handler writes to VSRAM */
#define S3K_HUD_X 0xF711U       /* signed byte: the HUD's horizontal slide offset (the HUD is built only while it is non-zero) */
#define S3K_COMPETITION 0xFFE8U /* word: non-zero in competition mode */
#define S3K_FLASH 0xFE05U       /* byte: bit 3 is the HUD blink phase */
#define S3K_RINGS 0xFE20U       /* word: ring count */
#define S3K_MINUTES 0xFE23U     /* byte: timer minutes */
#define S3K_EDGE 48U            /* picture edge bands judged apart from the centre (the game streams them) */

#define REASON_OK 0U
#define REASON_UNSUPPORTED_SCENE SEGA_GEN_REASON_UNSUPPORTED_SCENE
#define REASON_BAD_STATE SEGA_GEN_REASON_BAD_STATE
#define REASON_BAD_SCROLL SEGA_GEN_REASON_BAD_SCROLL
#define REASON_MISMATCH SEGA_GEN_REASON_MISMATCH
#define MAX_COLS 128U
#define MAX_WIN_ROWS 32U

typedef struct Sonic3kFrame {
  const uint8_t *ram;
  unsigned accepted;
  unsigned wide[2], high[2];            /* layout size per plane in chunks */
  int vs[2];                            /* the game's vertical scroll per plane */
  int off[S3K_HSCROLL_LINES][2];        /* world x of screen column 0 per output line and plane (the game's own per-line scroll; for the background plus the registered plane multiple) */
  int kx[S3K_HSCROLL_LINES];            /* the registered background plane multiple (units of 512 px) of each line */
  int bgy[S3K_HSCROLL_LINES];           /* background world y of each output line */
  int hs[S3K_HSCROLL_LINES][2];         /* the horizontal scroll the VDP applies to each line of each plane, as the host reads it */
  int vsh[S3K_HSCROLL_LINES][2];        /* the vertical scroll of each plane, as the host reads it */
  uint8_t own_plane[S3K_HSCROLL_LINES][2];
  uint16_t base[S3K_HSCROLL_LINES][2];  /* name-table base address per line and plane */
  const uint8_t *vram;
  unsigned height;
  unsigned hud_frame;                   /* HUD: the game's mapping frame (0 all, 1 no RINGS label, 2 no TIME label, 3 neither) */
  int hud_x;                            /* HUD: the slide offset applied to every piece */
} Sonic3kFrame;

static Sonic3kFrame g_frame;
static uint16_t g_words[2][MAX_COLS * MAX_WIN_ROWS];      /* one window of a plane is built and submitted at a time (the host copies it) */
static int32_t g_cell[MAX_WIN_ROWS][256];            /* the answer of a plane cell as the lines that ask it want it, or -1 while no line asked */
static int16_t g_delta[2][S3K_HSCROLL_LINES];

static unsigned u16(const uint8_t *r, unsigned a) { return ((unsigned)r[a & 0xFFFFU] << 8) | r[(a + 1U) & 0xFFFFU]; }
static int wrap_to(int v, int size) { const int m = v % size; return m < 0 ? m + size : m; }
static int floor_div(int a, int b) { return a >= 0 ? a / b : -((-a + b - 1) / b); }

/* Name-table word of the cell containing world pixel (wx, wy) of `plane` (0 fg, 1 bg); 0 outside the foreground. The background repeats vertically over its own layout and
 * horizontally continues by plane widths beyond its layout's ends. */
static unsigned world_cell(const Sonic3kFrame *f, unsigned plane, int wx, int wy) {
  const uint8_t *ram = f->ram;
  const int w = (int)f->wide[plane] * 128, h = (int)f->high[plane] * 128;
  unsigned chunk, bw, fx, fy, col, row, word;
  if (plane == 1U) {
    if (w >= 512 && wx >= w) wx -= ((wx - w) / 512 + 1) * 512;
    else if (w >= 512 && wx < 0) wx += ((-wx - 1) / 512 + 1) * 512;
    wx = wrap_to(wx, w);
    wy = wrap_to(wy, h);
  }
  else if (wx < 0 || wy < 0 || wx >= w || wy >= h) return 0U;
  chunk = ram[(u16(ram, S3K_ROWPTR + ((unsigned)wy >> 7) * 4U + plane * 2U) + ((unsigned)wx >> 7)) & 0xFFFFU];
  bw = u16(ram, S3K_CHUNKS + chunk * S3K_CHUNK_BYTES + ((((unsigned)wy & 127U) >> 4) * 8U + (((unsigned)wx & 127U) >> 4)) * 2U);
  fx = (bw >> 10) & 1U;
  fy = (bw >> 11) & 1U;
  col = (((unsigned)wx & 15U) >> 3) ^ fx;
  row = (((unsigned)wy & 15U) >> 3) ^ fy;
  word = u16(ram, S3K_BLOCKS + (bw & S3K_BLOCK_MASK) * 8U + (row * 2U + col) * 2U);
  return word ^ (fx ? 0x0800U : 0U) ^ (fy ? 0x1000U : 0U);
}

static unsigned vdp_cell(const uint8_t *vram, unsigned base, int x, int hs, unsigned line, int vs) {
  const unsigned px = (unsigned)(x - hs) & 511U, py = (unsigned)((int)line + vs) & 255U, a = base + ((py >> 3) * 64U + (px >> 3)) * 2U;
  return ((unsigned)vram[a & 0xFFFFU] << 8) | vram[(a + 1U) & 0xFFFFU];
}

static int same_cell(unsigned a, unsigned b) { return a == b || ((a & 0x7FFU) == 0U && (b & 0x7FFU) == 0U); }

/* The campaign zone ids of this image (verified with the level select): 0 Angel Island, 1 Hydrocity, 2 Marble Garden, 3 Carnival Night, 4 Flying Battery, 5 IceCap, 6 Launch Base,
 * 7 Mushroom Hill, 8 Sandopolis, 9 Lava Reef, 0x0A Sky Sanctuary, 0x0B Death Egg (acts 1-2), 0x0C The Doomsday (one act), 0x16 the Lava Reef boss act (act 0) and Hidden Palace
 * (act 1), 0x17 the Death Egg final-boss act. The competition zones and the bonus stages are not in the list. */
static int scenery_scope(unsigned zone, unsigned act) {
  if (zone <= 0x0BU || zone == 0x16U) return act <= 1U;
  return (zone == 0x0CU || zone == 0x17U) && act == 0U;
}

/* Background registration (unchanged from ABI 1): the layout column a plane column shows is the scroll-implied position plus an unknown multiple of the plane's width (512 px), and likewise
 * vertically (256 px). For each line the multiple that makes the provider's cells equal the VDP's own cells across the visible line is searched (previous line's first); the line is then
 * reconstructed continuously from that origin. A line no multiple explains is answered from the VDP's own plane (see scenery_check).
 * The one-point tie-break term for the multiple the same line had in the previous presented frame (`g_prev_kx[l]`, `g_prev_ky[l]`) is the only cross-frame input (see the header). */
static int g_prev_kx[S3K_HSCROLL_LINES], g_prev_ky[S3K_HSCROLL_LINES];   /* line l - 1: this frame's registered multiple; line l: the previous frame's (the ABI 1 arrays, unchanged) */

static unsigned bg_line_bad(const Sonic3kFrame *f, const SegaGenesisFrameView *v, unsigned l, int wx0, int wy, unsigned limit) {
  unsigned bad = 0U;
  for (int x = (int)S3K_EDGE; x < (int)v->width - (int)S3K_EDGE; x += 8) {
    if (!same_cell(world_cell(f, 1U, wx0 + x, wy), vdp_cell(v->vram, f->base[l][1], x, -f->off[l][1], l, f->vs[1]))) {
      if (++bad > limit) return bad;
    }
  }
  return bad;
}

static unsigned bg_ext_agree(const Sonic3kFrame *f, const SegaGenesisFrameView *v, unsigned l, int wx0, int wy) {
  const int side = v->side > 0U && v->side < 128U ? (int)v->side : 64;
  unsigned agree = 0U;
  for (int x = -side; x < (int)v->width + side; x += 8) {
    if (x >= 0 && x < (int)v->width) continue;
    agree += same_cell(world_cell(f, 1U, wx0 + x, wy), vdp_cell(v->vram, f->base[l][1], x, -f->off[l][1], l, f->vs[1]));
  }
  return agree;
}

static int bg_register(Sonic3kFrame *f, const SegaGenesisFrameView *v, unsigned l, int *kx_out, int *ky_out) {
  const int nx = ((int)f->wide[1] * 128 + 511) / 512, ny = ((int)f->high[1] * 128 + 255) / 256;
  const unsigned allowed = 1U;
  int best_kx = 0, best_ky = 0;
  long best = -1;
  if (l > 0U && f->off[l][1] == f->off[l - 1U][1] - g_prev_kx[l - 1U] * 512 && f->own_plane[l - 1U][1] == 0U &&
      bg_line_bad(f, v, l, f->off[l][1] + g_prev_kx[l - 1U] * 512, (int)l + f->vs[1] + g_prev_ky[l - 1U] * 256, allowed) <= allowed) {
    *kx_out = g_prev_kx[l - 1U]; *ky_out = g_prev_ky[l - 1U];
    return 1;
  }
  for (int ky = 0; ky < ny; ++ky)
    for (int kx = 0; kx < nx; ++kx) {
      const int wx0 = f->off[l][1] + kx * 512, wy = (int)l + f->vs[1] + ky * 256;
      long score;
      if (bg_line_bad(f, v, l, wx0, wy, allowed) > allowed) continue;
      score = (long)bg_ext_agree(f, v, l, wx0, wy) * 4L + ((l > 0U && kx == g_prev_kx[l - 1U] && ky == g_prev_ky[l - 1U]) ? 2L : 0L) +
              ((kx == g_prev_kx[l] && ky == g_prev_ky[l]) ? 1L : 0L);
      if (score > best) { best = score; best_kx = kx; best_ky = ky; }
    }
  *kx_out = best_kx; *ky_out = best_ky;
  return best >= 0;
}

static unsigned scenery_check(Sonic3kFrame *f, const SegaGenesisFrameView *v, const SegaGenesisVdpHelpers *vdp, const uint8_t *ram) {
  unsigned total[2] = {0U, 0U}, bad[2] = {0U, 0U}, edge_total = 0U, edge_bad = 0U;
  if (ram[S3K_GAMEMODE] != 0x0CU) return REASON_UNSUPPORTED_SCENE;
  if (v->width != 320U || v->height > S3K_HSCROLL_LINES) return REASON_BAD_STATE;
  for (unsigned p = 0U; p < 2U; ++p) {
    f->wide[p] = u16(ram, S3K_LAYOUT + p * 2U);
    f->high[p] = u16(ram, S3K_LAYOUT + 4U + p * 2U);
    if (f->wide[p] == 0U || f->high[p] == 0U || f->high[p] > S3K_MAX_ROWS || f->wide[p] > 0x100U) return REASON_BAD_STATE;
    f->vs[p] = (int16_t)u16(ram, S3K_VSCROLL + p * 2U);
  }
  for (unsigned l = 0U; l < v->height; ++l) {
    const SegaGenesisFrameLine *line = &v->lines[l];
    for (unsigned p = 0U; p < 2U; ++p) {
      int32_t hs = 0, vs = 0;
      const int ram_hs = (int16_t)u16(ram, S3K_HSCROLL + l * 4U + p * 2U);
      if ((line->registers[16] & 0x33U) != 0x01U || (line->registers[11] & 7U) != 3U || (line->registers[12] & 0x87U) != 0x81U || line->registers[17] != 0U ||
          line->registers[18] != 0U || vdp->vscroll_is_per_column(line->registers))
        return REASON_BAD_SCROLL;
      if (vdp->read_hscroll(v->vram, line->registers, p, l, &hs) != 0 || vdp->read_vscroll(line->vsram, line->registers, p, 0U, &vs) != 0)
        return REASON_BAD_SCROLL;
      if ((((int)hs - ram_hs) & 0x3FF) != 0 || (((int)vs - f->vs[p]) & 0x3FF) != 0) return REASON_BAD_SCROLL;
      f->off[l][p] = -ram_hs;
      f->hs[l][p] = (int)hs;
      f->vsh[l][p] = (int)vs;
      f->base[l][p] = (uint16_t)(p == 0U ? ((unsigned)(line->registers[2] & 0x38U) << 10) : ((unsigned)(line->registers[4] & 7U) << 13));
    }
  }
  f->ram = ram;
  f->vram = v->vram;
  f->height = v->height;
  for (unsigned l = 0U; l < v->height; ++l) {
    int kx, ky;
    if (!bg_register(f, v, l, &kx, &ky)) f->own_plane[l][1] = 1U;
    g_prev_kx[l] = kx; g_prev_ky[l] = ky;
    f->kx[l] = kx;
    f->off[l][1] += kx * 512;
    f->bgy[l] = (int)l + f->vs[1] + ky * 256;
  }
  for (unsigned l = 0U; l < v->height; ++l)
    for (unsigned p = 0U; p < 2U; ++p) {
      unsigned t = 0U, b = 0U, et = 0U, eb = 0U;
      if (p == 1U && f->own_plane[l][1] != 0U) continue;
      for (int x = 0; x < (int)v->width; x += 8) {
        const unsigned w = world_cell(f, p, x + f->off[l][p], p == 0U ? (int)l + f->vs[0] : f->bgy[l]);
        const unsigned vw = vdp_cell(v->vram, f->base[l][p], x, -f->off[l][p], l, f->vs[p]);
        if (x < (int)S3K_EDGE || x >= (int)v->width - (int)S3K_EDGE) { ++et; eb += !same_cell(w, vw); continue; }
        ++t;
        b += !same_cell(w, vw);
      }
      if (b * 10U <= t) { edge_total += et; edge_bad += eb; }
      if (b * 10U > t) {
        f->own_plane[l][p] = 1U;
        if (p == 0U) return REASON_MISMATCH;
      } else {
        total[p] += t;
        bad[p] += b;
      }
    }
  if (total[0] == 0U || bad[0] * 50U > total[0] || bad[1] * 50U > total[1] || edge_bad * 2U > edge_total) return REASON_MISMATCH;
  return REASON_OK;
}

/* The scenery of one plane as bounded windows, the per-row origin delta and the per-row generic mask.
 *
 * The host looks a column outside the picture up at plane cell p = floor((x - hscroll) / 8) + delta[line] (the window cell) of plane row floor((line + vscroll) / 8); the ABI 1 provider answered the same pixel
 * with the world cell at world x = screen x + off(line) (off carries the registered plane multiple), i.e. plane cell p of line l holds the world cell at 8 p + hscroll + off(l), whatever the delta is: the delta
 * only chooses WHERE in the windows the answer is stored. Lines of one cell row that ask the same plane-to-world mapping (the same multiples and scroll wrap) are a GROUP; their cells never conflict. Groups
 * with different mappings would need different words for the same window cell if they sat at the same place, so each group gets its own whole-cell shift: its natural place (the multiple, relative to the
 * smallest multiple of the row, times 64 cells, plus the row's scroll cell) when that is free, otherwise the nearest free place. Cell rows are independent of each other. Everything lives in one run of 256
 * window columns (two windows of 128), so the cover is exact whatever the bands do. A frame that does not fit (more groups than room) is refused honestly, never answered half-way. Returns 0 on success. */
#define PLACE_COLS 256
#define MAX_GROUPS 12
static int build_plane_windows(const SegaGenesisRenderApi *r, const Sonic3kFrame *f, unsigned plane, unsigned left_px, unsigned margin_px, uint8_t mask[28], unsigned *any_mask, unsigned *any_delta) {
  const unsigned right_px = 2U * margin_px - left_px, height = f->height;
  int rmin = 0, rmax = 0, rows, rr, have = 0, w1 = 0, nwin, used_max = -1;
  unsigned l;
  int kbase[MAX_WIN_ROWS], shift[MAX_WIN_ROWS], ngroups[MAX_WIN_ROWS];
  int gq[MAX_WIN_ROWS][MAX_GROUPS], gkx[MAX_WIN_ROWS][MAX_GROUPS], gky[MAX_WIN_ROWS][MAX_GROUPS], gd[MAX_WIN_ROWS][MAX_GROUPS];
  int pal[S3K_HSCROLL_LINES], pbl[S3K_HSCROLL_LINES], par[S3K_HSCROLL_LINES], pbr[S3K_HSCROLL_LINES], grp[S3K_HSCROLL_LINES], rowof[S3K_HSCROLL_LINES];
  for (l = 0U; l < 28U; ++l) mask[l] = 0U;
  for (l = 0U; l < S3K_HSCROLL_LINES; ++l) g_delta[plane][l] = 0;
  for (l = 0U; l < MAX_WIN_ROWS; ++l) { kbase[l] = 0x7FFFFFFF; shift[l] = 0x7FFFFFFF; ngroups[l] = 0; }
  /* Pass 1: the cell rows asked; per row the smallest registered multiple (kbase) and the scroll cell of its first line (shift) */
  for (l = 0U; l < height; ++l) {
    const int row = floor_div((int)l + f->vsh[l][plane], 8);
    if (f->own_plane[l][plane] != 0U) {   /* answered by the VDP's own plane: marks the screen row, asks the windows nothing */
      mask[l >> 3] = (uint8_t)(mask[l >> 3] | (1U << (l & 7U)));
      *any_mask = 1U;
      continue;
    }
    if (!have || row < rmin) rmin = row;
    if (!have || row > rmax) rmax = row;
    have = 1;
  }
  if (!have) return 0;   /* every line of this plane is answered by the VDP: no window */
  rows = rmax - rmin + 1;
  if (rows < 1 || rows > (int)MAX_WIN_ROWS) return 1;
  for (l = 0U; l < height; ++l) {
    int row;
    if (f->own_plane[l][plane] != 0U) continue;
    row = floor_div((int)l + f->vsh[l][plane], 8) - rmin;
    rowof[l] = row;
    if (plane == 1U && f->kx[l] < kbase[row]) kbase[row] = f->kx[l];
    if (shift[row] == 0x7FFFFFFF) shift[row] = plane == 1U ? floor_div(f->hs[l][1], 8) : 0;
  }
  /* Pass 2: the asked plane cells of every line, its group and the natural delta of the group */
  for (l = 0U; l < height; ++l) {
    int row, q, g, nat;
    if (f->own_plane[l][plane] != 0U) continue;
    row = rowof[l];
    q = f->hs[l][plane] + f->off[l][plane] - (plane == 1U ? f->kx[l] * 512 : 0);   /* scroll wrap: hscroll minus the game's own scroll (0 unless the 10-bit read wrapped) */
    pal[l] = floor_div(-(int)left_px - f->hs[l][plane], 8);   /* the host asks ONLY the off-picture pixels of a line: x = -left_px .. -1 and x = 320 .. 319 + right_px */
    pbl[l] = floor_div(-1 - f->hs[l][plane], 8);
    par[l] = floor_div(320 - f->hs[l][plane], 8);
    pbr[l] = floor_div(319 + (int)right_px - f->hs[l][plane], 8);
    for (g = 0; g < ngroups[row]; ++g) if (gq[row][g] == q && gkx[row][g] == (plane == 1U ? f->kx[l] : 0) && gky[row][g] == (plane == 1U ? f->bgy[l] - (int)l - f->vs[1] : 0)) break;
    if (g == ngroups[row]) {
      if (g == MAX_GROUPS) { return 3; }
      gq[row][g] = q; gkx[row][g] = plane == 1U ? f->kx[l] : 0; gky[row][g] = plane == 1U ? f->bgy[l] - (int)l - f->vs[1] : 0;
      nat = plane == 1U ? (f->kx[l] - kbase[row]) * 64 + shift[row] : 0;
      gd[row][g] = nat;
      ngroups[row] = g + 1;
    }
    grp[l] = g;
  }
  /* the run of window columns starts at the smallest natural column of any row's first group */
  for (rr = 0, have = 0; rr < rows; ++rr) {
    for (l = 0U; l < height; ++l) {
      if (f->own_plane[l][plane] != 0U || rowof[l] != rr) continue;
      if (!have || pal[l] + gd[rr][grp[l]] < w1) w1 = pal[l] + gd[rr][grp[l]];
      have = 1;
    }
  }
  for (rr = 0; rr < rows; ++rr) for (int c = 0; c < PLACE_COLS; ++c) g_cell[rr][c] = -1;
  /* Pass 3: place every group of every row (the first group of a row at its natural place whenever it is free) */
  for (rr = 0; rr < rows; ++rr) {
    for (int g = 0; g < ngroups[rr]; ++g) {
      int placed = 0;
      for (int step = 0; step <= 2 * PLACE_COLS && !placed; ++step) {
        const int s = (step & 1) ? (step + 1) / 2 : -(step / 2), d = gd[rr][g] + s;
        int ok = 1;
        for (l = 0U; l < height && ok; ++l) {
          if (f->own_plane[l][plane] != 0U || rowof[l] != rr || grp[l] != g) continue;
          for (unsigned side = 0U; side < 2U && ok; ++side)
            for (int p = side == 0U ? pal[l] : par[l]; p <= (side == 0U ? pbl[l] : pbr[l]) && ok; ++p) {
              const int col = p + d - w1;
              int32_t cur;
              if (col < 0 || col >= PLACE_COLS) { ok = 0; break; }
              cur = g_cell[rr][col];
              if (cur >= 0) {
                const int wy = plane == 0U ? (int)l + f->vs[0] : f->bgy[l];
                if (cur != (int32_t)world_cell(f, plane, p * 8 + f->hs[l][plane] + f->off[l][plane], wy)) ok = 0;
              }
            }
        }
        if (!ok) continue;
        for (l = 0U; l < height; ++l) {
          if (f->own_plane[l][plane] != 0U || rowof[l] != rr || grp[l] != g) continue;
          for (unsigned side = 0U; side < 2U; ++side)
            for (int p = side == 0U ? pal[l] : par[l]; p <= (side == 0U ? pbl[l] : pbr[l]); ++p) {
              const int wy = plane == 0U ? (int)l + f->vs[0] : f->bgy[l], col = p + d - w1;
              g_cell[rr][col] = (int32_t)world_cell(f, plane, p * 8 + f->hs[l][plane] + f->off[l][plane], wy);
              if (col > used_max) used_max = col;
            }
        }
        gd[rr][g] = d;
        placed = 1;
      }
      if (!placed) { return 3; }
    }
  }
  for (l = 0U; l < height; ++l) {
    if (f->own_plane[l][plane] != 0U) continue;
    g_delta[plane][l] = (int16_t)gd[rowof[l]][grp[l]];
    if (g_delta[plane][l] != 0) *any_delta = 1U;
  }
  if (used_max < 0) return 0;
  nwin = used_max >= (int)MAX_COLS ? 2 : 1;
  for (int w = 0; w < nwin; ++w) {
    const int c0 = w * (int)MAX_COLS, cols = (w == 0 && nwin == 1) ? used_max + 1 : (w == 0 ? (int)MAX_COLS : used_max + 1 - (int)MAX_COLS);
    for (rr = 0; rr < rows; ++rr)
      for (int c = 0; c < cols; ++c) {
        const int32_t word = g_cell[rr][c0 + c];
        g_words[plane][(unsigned)rr * (unsigned)cols + (unsigned)c] = (uint16_t)(word < 0 ? 0 : word);   /* a cell no line asks is never read */
      }
    if (r->scenery_window(plane, w1 + c0, rmin, (uint32_t)cols, (uint32_t)rows, g_words[plane]) != 0) return 4;
  }
  return 0;
}

/* ---------------------------------------------------------------------------------------------------------------- HUD */
/* The game's own one-player HUD, relocated (see the ABI 1 provider): the package's BPS moves the HUD's Y base off the visible window and this draws the same pieces from the frame's own VRAM and CRAM. */
#define HUD_X0 16U    /* picture column of the HUD's left edge at rest (slide offset 1) */
#define HUD_W 104U    /* picture columns 16..119 */
#define HUD_H 216U    /* picture rows 0..215 (the lives row ends at 215) */
#define HUD_PAD 8U    /* transparent left margin of the overlay: keeps the HUD off the very edge of the screen beside the picture; the in-picture position is unchanged */
#define HUD_OW (HUD_W + HUD_PAD)

static uint8_t g_hud_bitmap[HUD_OW * HUD_H * 4U];

typedef struct HudPiece { int8_t x; uint8_t y; uint8_t cells_w, cells_h; uint16_t tile; uint8_t line; uint8_t frames; } HudPiece;
/* frames: bit n set = the piece is in mapping frame n */
static const HudPiece k_hud_pieces[] = {
    {0, 8, 4, 2, 0x6CAU, 1, 0x0F}, {32, 8, 4, 2, 0x6E2U, 1, 0x0F}, {64, 8, 4, 2, 0x6EAU, 1, 0x0F},   /* SCORE and its digits */
    {0, 24, 4, 2, 0x6DAU, 1, 0x03}, {40, 24, 4, 2, 0x6F2U, 1, 0x0F},                                 /* TIME (omitted in frames 2, 3) and its digits */
    {0, 40, 4, 2, 0x6D2U, 1, 0x05}, {32, 40, 1, 2, 0x6CAU, 1, 0x05}, {48, 40, 3, 2, 0x6FAU, 1, 0x0F}, /* RINGS (omitted in frames 1, 3) and its digits */
    {0, 200, 2, 2, 0x7D4U, 0, 0x0F}, {16, 200, 4, 2, 0x7D8U, 1, 0x0F},                              /* the character icon, and the name and lives */
};

static int hud_state(const uint8_t *ram) {
  return (ram[S3K_GAMEMODE] == 0x0CU || ram[S3K_GAMEMODE] == 0x8CU) && ram[S3K_HUD_X] != 0U && u16(ram, S3K_COMPETITION) == 0U && scenery_scope(ram[S3K_ZONE], ram[S3K_ZONE + 1U]);
}

static unsigned hud_frame_of(const uint8_t *ram) {
  unsigned frame = 0U;
  if ((ram[S3K_FLASH] & 0x08U) != 0U) return 0U;
  if (u16(ram, S3K_RINGS) == 0U) frame += 1U;
  if (ram[S3K_MINUTES] == 9U) frame += 2U;
  return frame;
}

static void draw_hud(const Sonic3kFrame *f, const SegaGenesisFrameView *v, const SegaGenesisVdpHelpers *vdp) {
  for (unsigned i = 0U; i < (unsigned)sizeof(g_hud_bitmap); ++i) g_hud_bitmap[i] = 0U;   /* fully transparent: no panel */
  for (unsigned n = 0U; n < sizeof(k_hud_pieces) / sizeof(k_hud_pieces[0]); ++n) {
    const HudPiece *pc = &k_hud_pieces[n];
    if ((pc->frames & (1U << f->hud_frame)) == 0U) continue;
    for (unsigned cx = 0U; cx < pc->cells_w; ++cx)
      for (unsigned cy = 0U; cy < pc->cells_h; ++cy) {
        const unsigned tile = pc->tile + cx * pc->cells_h + cy;   /* a sprite's cells are numbered down each column */
        for (unsigned row = 0U; row < 8U; ++row) {
          const unsigned py = pc->y + cy * 8U + row;
          if (py >= HUD_H) continue;
          for (unsigned col = 0U; col < 8U; ++col) {
            const int ox = (int)HUD_PAD + (f->hud_x - 1) + pc->x + (int)(cx * 8U + col);   /* picture column 15 + slide + piece x, relative to HUD_X0, plus the pad */
            const uint8_t byte = v->vram[(tile * 32U + row * 4U + col / 2U) & 0xFFFFU];
            const unsigned index = (col & 1U) == 0U ? (unsigned)(byte >> 4) : (unsigned)(byte & 0x0FU);
            uint8_t c[3];
            uint8_t *d;
            if (index == 0U || ox < (int)HUD_PAD || ox >= (int)HUD_OW) continue;
            if (vdp->cram_rgb(v->lines[py].cram, pc->line * 16U + index, c) != 0) continue;
            d = g_hud_bitmap + ((size_t)py * HUD_OW + (unsigned)ox) * 4U;
            d[0] = c[0]; d[1] = c[1]; d[2] = c[2]; d[3] = 255U;
          }
        }
      }
  }
}

/* ---------------------------------------------------------------------------------------------------------------- the exact-frame render */

static void refuse(const SegaGenesisRenderApi *r, uint32_t requested, uint32_t reason) {
  const uint32_t components = requested & (SEGA_GEN_COMPONENT_HUD | SEGA_GEN_COMPONENT_SCENERY);
  if (components != 0U) (void)r->decline(components, reason);   /* a refusal, never a fault: the host serves the frame generically */
}

static void render_frame(const SegaModHost *host) {
  const SegaGenesisFeatures *feat = (const SegaGenesisFeatures *)host->platform_features;
  const SegaGenesisRenderApi *r;
  const SegaGenesisFrameView *v;
  const SegaGenesisVdpHelpers *vdp;
  const uint8_t *ram;
  Sonic3kFrame *f = &g_frame;
  unsigned reason = REASON_UNSUPPORTED_SCENE, accepted = 0U, margin_px, left_px;
  uint32_t requested;
  if (feat == NULL || feat->render == NULL || feat->frame == NULL || feat->vdp == NULL || feat->size < sizeof(SegaGenesisFeatures)) return;
  r = feat->render;
  v = feat->frame;
  vdp = feat->vdp;
  ram = v->work_ram;
  requested = v->requested;
  for (unsigned i = 0U; i < (unsigned)sizeof(*f); ++i) ((uint8_t *)f)[i] = 0U;
  if (ram == NULL || v->lines == NULL || v->vram == NULL || v->height == 0U || v->height > 448U || v->line_count < v->height) { refuse(r, requested, REASON_BAD_STATE); return; }
  /* scope: a running level of the single-player campaign inventory (scenery_scope). Every other screen (title, menus, special and bonus stages, competition) is declined. */
  if ((ram[S3K_GAMEMODE] != 0x0CU && ram[S3K_GAMEMODE] != 0x8CU) || !scenery_scope(ram[S3K_ZONE], ram[S3K_ZONE + 1U])) { refuse(r, requested, REASON_UNSUPPORTED_SCENE); return; }
  margin_px = v->side != 0U ? v->side : 64U;   /* the baseline keeps the picture centred (left_px == margin_px) and declares no placement */
  left_px = margin_px;
  if ((requested & SEGA_GEN_COMPONENT_HUD) != 0U && hud_state(ram) && v->height == 224U) {
    f->hud_frame = hud_frame_of(ram);
    f->hud_x = (int8_t)ram[S3K_HUD_X];
    accepted |= SEGA_GEN_COMPONENT_HUD;
  }
  if ((requested & SEGA_GEN_COMPONENT_SCENERY) != 0U) {
    reason = scenery_check(f, v, vdp, ram);
    if (reason == REASON_OK) accepted |= SEGA_GEN_COMPONENT_SCENERY;
  }
  if (accepted == 0U) { refuse(r, requested, reason); return; }
  (void)r->scene("level", 5U);
  if ((accepted & SEGA_GEN_COMPONENT_SCENERY) != 0U) {
    uint8_t mask[2][28];
    unsigned any[2] = {0U, 0U}, anyd[2] = {0U, 0U};
    int e0 = build_plane_windows(r, f, 0U, left_px, margin_px, mask[0], &any[0], &anyd[0]), e1 = build_plane_windows(r, f, 1U, left_px, margin_px, mask[1], &any[1], &anyd[1]);
    if (e0 != 0 || e1 != 0) {
      (void)r->decline(SEGA_GEN_COMPONENT_SCENERY, REASON_BAD_STATE);   /* the windows cannot express this frame's answers: never served half-way */
    } else {
      for (unsigned p = 0U; p < 2U; ++p) {
        if (any[p] != 0U) (void)r->scenery_generic_rows(p, mask[p], 224U, 28U);
        if (anyd[p] != 0U) (void)r->scenery_row_origin(p, g_delta[p], f->height, f->height * 2U);
      }
    }
  }
  if ((accepted & SEGA_GEN_COMPONENT_HUD) != 0U) {
    draw_hud(f, v, vdp);
    (void)r->overlay_fallback(HUD_X0 - HUD_PAD, 0U);
    (void)r->overlay_bitmap(0, 0, HUD_OW, HUD_H, g_hud_bitmap, HUD_OW * 4U);
  }
}

/* ---------------------------------------------------------------------------------------------------------------- cross-frame state (state.mod) */
static int provider_save(void *state, uint8_t *out, uint32_t cap, uint32_t *len) {
  (void)state;
  if (cap < 2U * S3K_HSCROLL_LINES) return 1;
  for (unsigned l = 0U; l < S3K_HSCROLL_LINES; ++l) { out[l] = (uint8_t)g_prev_kx[l]; out[S3K_HSCROLL_LINES + l] = (uint8_t)g_prev_ky[l]; }
  *len = 2U * S3K_HSCROLL_LINES;
  return 0;
}

static int provider_load(void *state, const uint8_t *in, uint32_t len) {
  (void)state;
  if (len != 2U * S3K_HSCROLL_LINES) return 1;
  for (unsigned l = 0U; l < S3K_HSCROLL_LINES; ++l) if (in[l] > 63U || in[S3K_HSCROLL_LINES + l] > 31U) return 1;   /* a multiple is below the plane count of the layout (at most 64 x 32) */
  for (unsigned l = 0U; l < S3K_HSCROLL_LINES; ++l) { g_prev_kx[l] = in[l]; g_prev_ky[l] = in[S3K_HSCROLL_LINES + l]; }
  return 0;
}

static int provider_init(void *state, const SegaModHost *host) {
  (void)state;
  return host->platform == SEGA_MOD_PLATFORM && host->platform_features != NULL ? 0 : 1;
}

static void provider_phase(void *state, const SegaModHost *host) {
  (void)state;
  if (host->phase == SEGA_MOD_PHASE_RENDER) render_frame(host);
}

static const SegaModProvider provider = {sizeof(SegaModProvider), SEGA_MOD_ABI_MAJOR, 3U, SEGA_MOD_PLATFORM, "sonic3k.native-widescreen", 9U, provider_init, provider_phase, NULL, provider_save, provider_load,
                                         {NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL}};

const SegaModProvider *segarecomp_mod_provider(void **state_out) {
  if (state_out != NULL) *state_out = NULL;
  return &provider;
}
