/*
 * Sonic the Hedgehog (Genesis, REV00) native widescreen provider for the schema 3 / native ABI 2 SDK (segarecomp_mod_genesis.h, minor 2): the port of the ABI 1 provider of
 * patches/genesis/sonic-1/native-widescreen with the SAME game knowledge, constants and verification logic (SEG-152-T009, ADR 0320). Original image SHA-256
 * 46160baa06362c711c9f1a5017cb7371026444936c8af5e93a78996cf32ff2a6.
 *
 * What changes is only how the answers are delivered: the ABI 1 per-cell scenery callback becomes bounded scenery WINDOWS built from the frame view (plus the per-row generic mask for the special
 * stage's own wrapped plane), the ABI 1 HUD overlay becomes one RGBA bitmap, and a frame the provider does not serve is refused with the ABI 1 diagnostic reason (a refusal, never a fault).
 * The provider is an exact-frame provider (capability frame.vdp): `render` runs once per produced frame against the frame's own copies. It keeps no state across frames.
 */
#include <segarecomp_mod_genesis.h>

/* Work-RAM map of the verified image (offsets into the 64 KiB work RAM; verified against the unmodified image's level code and a live generated run, class-level). */
#define S1_CHUNKS 0x0000U       /* 256x256 chunk table: 0x200 bytes per chunk (16x16 block words) */
#define S1_CHUNK_COUNT 0x52U    /* 0xA400 / 0x200 */
#define S1_LAYOUT 0xA400U       /* level layout: 8 rows of 0x80 bytes; foreground = first 0x40, background = next 0x40; low 7 bits = chunk index + 1 */
#define S1_LAYOUT_ROWS 8U
#define S1_BLOCKS 0xB000U       /* 16x16 block table: 8 bytes (4 name words: TL TR BL BR) */
#define S1_BLOCK_MAX 0x3FFU
#define S1_GAMEMODE 0xF600U     /* byte: 0x0C running level (0x8C = the level start sequence) */
#define S1_CAMX 0xF700U         /* words: foreground camera x/y */
#define S1_CAMY 0xF704U
#define S1_BGX 0xF708U          /* background camera x/y */
#define S1_BGY 0xF70CU
#define S1_HSCROLL 0xCC00U      /* per-line horizontal scroll buffer the game copies to the VDP at VBlank: 224 x (foreground word, background word), signed, NOT wrapped */
#define S1_HSCROLL_LINES 224U
#define S1_FRAMECOUNT_FLASH 0xFE05U  /* byte: bit 3 is the flash phase the original HUD uses */
#define S1_TIME 0xFE22U         /* long: 0, minutes (binary), seconds (binary), frames (binary) */
#define S1_SCORE 0xFE26U        /* long, binary */
#define S1_BG2X 0xF710U         /* word: the second background camera (the lower background region is streamed from it) */
#define S1_BG_SPLIT 0xF7F0U     /* word: world y (background layout) where the lower background region starts */
#define S1_ZONE 0xFE10U         /* bytes: zone, act */
#define S1_LIVES 0xFE12U        /* byte */
#define S1_RINGS 0xFE20U        /* word */
#define S1_WORLD_W 0x4000       /* 64 chunks of 256 px */

/* The reasons of a refusal are the ABI 1 diagnostics (SEGA_GEN_REASON_* are the host's GENESIS_COMPAT_* values). */
#define REASON_OK 0U
#define REASON_UNSUPPORTED_SCENE SEGA_GEN_REASON_UNSUPPORTED_SCENE
#define REASON_BAD_STATE SEGA_GEN_REASON_BAD_STATE
#define REASON_BAD_SCROLL SEGA_GEN_REASON_BAD_SCROLL
#define REASON_MISMATCH SEGA_GEN_REASON_MISMATCH

#define MAX_COLS 128U           /* one scenery window: at most 128 x 32 words (4096), at most two windows per plane */
#define MAX_WIN_ROWS 32U
#define SPAN_MAX 256            /* the two windows of a plane together cover at most this many columns */

static unsigned u16(const uint8_t *r, unsigned a) { return ((unsigned)r[a & 0xFFFFU] << 8) | r[(a + 1U) & 0xFFFFU]; }

/* Name-table word of 8x8 cell (cx, cy) of layout `plane` (0 fg, 1 bg). Bounded: every address below is < 0x10000 by construction. */
static int world_cell(const uint8_t *ram, unsigned plane, int cx, int cy) {
  unsigned x, y, chunk, block_word, block, flip_x, flip_y, col, row, word;
  if (ram == NULL || plane > 1U) return -1;
  if (cx < 0 || cy < 0 || cx >= S1_WORLD_W / 8 || cy >= (int)(S1_LAYOUT_ROWS * 32U)) return 0;   /* outside the level: no world, a blank cell */
  x = (unsigned)cx * 8U;
  y = (unsigned)cy * 8U;
  chunk = ram[S1_LAYOUT + plane * 0x40U + (y >> 8) * 0x80U + (x >> 8)] & 0x7FU;
  if (chunk == 0U) return 0;
  if (chunk > S1_CHUNK_COUNT) return -1;
  block_word = u16(ram, S1_CHUNKS + (chunk - 1U) * 0x200U + (((y & 0xFFU) >> 4) * 16U + ((x & 0xFFU) >> 4)) * 2U);
  block = block_word & S1_BLOCK_MAX;
  flip_x = (block_word >> 11) & 1U;
  flip_y = (block_word >> 12) & 1U;
  col = (x & 15U) >> 3;
  row = (y & 15U) >> 3;
  if (flip_x) col ^= 1U;
  if (flip_y) row ^= 1U;
  word = u16(ram, S1_BLOCKS + block * 8U + (row * 2U + col) * 2U);
  if (flip_x) word ^= 0x0800U;
  if (flip_y) word ^= 0x1000U;
  return (int)word;
}

/* ---------------------------------------------------------------------------------------------------------------- per-frame state (a scratch of one render call) */

typedef struct Sonic1Frame {
  int camy, bgy;
  int off_fg[S1_HSCROLL_LINES], off_bg[S1_HSCROLL_LINES];   /* world x of screen column 0 per output line (exact: the game's own unwrapped scroll) */
  int hs[2][S1_HSCROLL_LINES];                              /* the horizontal scroll the VDP applies to each line of each plane, as the host reads it */
  int vs[2][S1_HSCROLL_LINES];                              /* the vertical scroll (full screen) of each plane, as the host reads it */
  unsigned rings, lives, score, minutes, seconds, flash;
  unsigned ss_rows;                       /* the special stage: plane height in cells (width is always 64) */
} Sonic1Frame;

static Sonic1Frame g_frame;
static uint16_t g_words[2][2][MAX_COLS * MAX_WIN_ROWS];   /* [plane][window] */
static int32_t g_cell[MAX_WIN_ROWS][SPAN_MAX];            /* the answer (a name-table word) of a plane cell as the lines that ask it want it, or -1 while no line asked */
static uint8_t g_hud_rgba[104U * 224U * 4U];

/* Congruent value of `v` (mod `period`) nearest to `ref` within [ref - period/2, ref + period/2). */
static int unwrap(int v, int ref, int period) {
  int d = (v - ref) % period;
  if (d < 0) d += period;
  if (d >= period / 2) d -= period;
  return ref + d;
}

static int floor_div(int a, int b) { return a >= 0 ? a / b : -((-a + b - 1) / b); }

/* The zones and acts the scenery component is validated for: bit `act` of entry `zone` (zone ids: 0 Green Hill, 1 Labyrinth, 2 Marble, 3 Star Light, 4 Spring Yard, 5 Scrap Brain; Labyrinth's
 * act 3 slot is the third Scrap Brain act). Every frame is additionally identity-checked, so an entry only widens the scope; it never relaxes a check. */
static const uint8_t k_scenery_acts[6] = {0x07, 0x0F, 0x07, 0x07, 0x07, 0x07};   /* Green Hill acts 1-3 */

static int scenery_scope(unsigned zone, unsigned act) { return zone < 6U && act < 8U && ((k_scenery_acts[zone] >> act) & 1U) != 0U; }

static int layout_valid(const uint8_t *ram) {
  for (unsigned row = 0U; row < S1_LAYOUT_ROWS; ++row)
    for (unsigned i = 0U; i < 0x80U; ++i)
      if ((ram[S1_LAYOUT + row * 0x80U + i] & 0x7FU) > S1_CHUNK_COUNT) return 0;
  return 1;
}

/* Scenery verification: returns REASON_OK or the reason it is declined. Identical to the ABI 1 provider's check (same registers, same RAM, same tolerances). */
static unsigned scenery_check(Sonic1Frame *f, const SegaGenesisFrameView *v, const SegaGenesisVdpHelpers *vdp, const uint8_t *ram) {
  if (!scenery_scope(ram[S1_ZONE], ram[S1_ZONE + 1U])) return REASON_UNSUPPORTED_SCENE;
  f->camy = (int)u16(ram, S1_CAMY);
  f->bgy = (int)u16(ram, S1_BGY);
  if (v->height > S1_HSCROLL_LINES || f->camy >= (int)(S1_LAYOUT_ROWS * 256U) || f->bgy >= (int)(S1_LAYOUT_ROWS * 256U) || u16(ram, S1_CAMX) >= S1_WORLD_W || u16(ram, S1_BGX) >= S1_WORLD_W || u16(ram, S1_BG2X) >= S1_WORLD_W)
    return REASON_BAD_STATE;
  if (!layout_valid(ram)) return REASON_BAD_STATE;
  /* The display must be the verified configuration (64x32 planes, per-line scroll, full-screen vertical scroll) and the scroll the VDP applies (copied from the game's buffer at the
   * previous VBlank) must equal the game's own unwrapped values in work RAM line by line: RAM and VDP then describe the same frame. A level that is still being set up, or any
   * other disagreement, is declined. */
  for (unsigned l = 0U; l < v->height; ++l) {
    const SegaGenesisFrameLine *line = &v->lines[l];
    int32_t ha = 0, hb = 0, va = 0, vb = 0;
    const int ram_a = (int16_t)u16(ram, S1_HSCROLL + l * 4U), ram_b = (int16_t)u16(ram, S1_HSCROLL + l * 4U + 2U);
    if ((line->registers[16] & 0x33U) != 0x01U || vdp->vscroll_is_per_column(line->registers)) return REASON_BAD_SCROLL;
    if (vdp->read_hscroll(v->vram, line->registers, 0U, l, &ha) != 0 || vdp->read_hscroll(v->vram, line->registers, 1U, l, &hb) != 0 ||
        vdp->read_vscroll(line->vsram, line->registers, 0U, 0U, &va) != 0 || vdp->read_vscroll(line->vsram, line->registers, 1U, 0U, &vb) != 0)
      return REASON_BAD_SCROLL;
    if ((((int)ha - ram_a) & 0x3FF) != 0 || (((int)hb - ram_b) & 0x3FF) != 0 || (((int)va - f->camy) & 0x3FF) != 0 || (((int)vb - f->bgy) & 0x3FF) != 0) return REASON_BAD_SCROLL;
    f->hs[0][l] = (int)ha;
    f->hs[1][l] = (int)hb;
    f->vs[0][l] = (int)va;
    f->vs[1][l] = (int)vb;
    f->off_fg[l] = -ram_a;                                       /* the foreground scrolls exactly with the camera */
    /* A background band is only defined modulo the 512-pixel plane. The game streams the upper background region from the first background camera and the region below
     * `S1_BG_SPLIT` from the second one, so the band's world position is the alias nearest the camera of ITS region. */
    f->off_bg[l] = unwrap(-ram_b, (int)(((int)l + f->bgy) >= (int)u16(ram, S1_BG_SPLIT) ? u16(ram, S1_BG2X) : u16(ram, S1_BGX)), 512);
  }
  /* Frame identity: the provider's own cells for the part of the world the picture shows must agree with what the VDP nametables hold there (the game drew them). A gross disagreement
   * (a fade, a level transition, another level than the state claims) means RAM and picture are not the same scene: the frame is declined, never half-served. Cells the game has not (yet)
   * streamed (a background band beyond its window, left of the layout) are not compared. */
  {
    unsigned fg_total = 0U, fg_bad = 0U, bg_total = 0U, bg_bad = 0U;
    for (unsigned l = 0U; l < v->height; l += 8U) {
      const SegaGenesisFrameLine *line = &v->lines[l];
      int32_t hs[2] = {0, 0};
      (void)vdp->read_hscroll(v->vram, line->registers, 0U, l, &hs[0]);
      (void)vdp->read_hscroll(v->vram, line->registers, 1U, l, &hs[1]);
      for (unsigned plane = 0U; plane < 2U; ++plane) {
        const unsigned base = plane == 0U ? (unsigned)(line->registers[2] & 0x38U) << 10 : (unsigned)(line->registers[4] & 7U) << 13;
        const int off = plane == 0U ? f->off_fg[l] : f->off_bg[l];
        const int ycam = plane == 0U ? f->camy : f->bgy;
        const int cam = plane == 0U ? (int)u16(ram, S1_CAMX) : (((int)l + f->bgy) >= (int)u16(ram, S1_BG_SPLIT) ? (int)u16(ram, S1_BG2X) : (int)u16(ram, S1_BGX));
        for (int x = 0; x < (int)v->width; x += 8) {
          const int wx = x + off, wy = (int)l + ycam;
          unsigned px = (unsigned)(x - (int)hs[plane]) & 511U, py = (unsigned)(wy) & 255U, vw;
          int w;
          if (wx < 0 || wx < cam - 16 || wx >= cam + 336) continue;   /* outside what the game streams for this plane/region */
          w = world_cell(ram, plane, wx / 8, wy / 8);
          vw = ((unsigned)v->vram[(base + ((py >> 3) * 64U + (px >> 3)) * 2U) & 0xFFFFU] << 8) | v->vram[(base + ((py >> 3) * 64U + (px >> 3)) * 2U + 1U) & 0xFFFFU];
          if (w < 0) return REASON_BAD_STATE;
          if (plane == 0U) { ++fg_total; if ((unsigned)w != vw && !((vw & 0x7FFU) == 0U && ((unsigned)w & 0x7FFU) == 0U)) ++fg_bad; }
          else { ++bg_total; if ((unsigned)w != vw && !((vw & 0x7FFU) == 0U && ((unsigned)w & 0x7FFU) == 0U)) ++bg_bad; }
        }
      }
    }
    if (fg_total == 0U || fg_bad * 10U > fg_total || bg_bad * 7U > bg_total) return REASON_MISMATCH;
  }
  return REASON_OK;
}

/* Special stage (game mode 0x10), 16:9: the stage background is two fully populated 64-cell-wide name tables that the game scrolls (per-line horizontal scroll) and that the VDP wraps; nothing is
 * streamed. The world beyond the 320-pixel picture is therefore exactly the wrapped plane, which is what a wider display would show. The provider verifies the one configuration the stage uses
 * (both planes 64 wide, bases and height constant over the frame, per-line horizontal + full-screen vertical scroll, no window, no interlace) on every line; the host then answers the cells of every
 * row from the plane's own name table (the per-row generic mask). The maze itself is sprites and is not affected. Anything else is declined. */
static unsigned ss_check(Sonic1Frame *f, const SegaGenesisFrameView *v) {
  unsigned rows = 0U, base_a = 0U, base_b = 0U;
  if (v->height > S1_HSCROLL_LINES) return REASON_BAD_STATE;
  for (unsigned l = 0U; l < v->height; ++l) {
    const uint16_t *r = v->lines[l].registers;
    const unsigned h = (unsigned)(r[16] >> 4) & 3U, w = (unsigned)r[16] & 3U;
    if ((r[11] & 7U) != 3U || (r[12] & 6U) != 0U || r[17] != 0U || r[18] != 0U || w != 1U || (h != 0U && h != 1U)) return REASON_BAD_SCROLL;
    if (l == 0U) {
      rows = h == 0U ? 32U : 64U;
      base_a = (unsigned)(r[2] & 0x38U) << 10;
      base_b = (unsigned)(r[4] & 7U) << 13;
    } else if ((h == 0U ? 32U : 64U) != rows || ((unsigned)(r[2] & 0x38U) << 10) != base_a || ((unsigned)(r[4] & 7U) << 13) != base_b) {
      return REASON_BAD_SCROLL;   /* the layout changes within the frame: not the stage's own steady configuration */
    }
  }
  f->ss_rows = rows;
  return REASON_OK;
}

/* ---------------------------------------------------------------------------------------------------------------- scenery windows */

/* The scenery of one plane as bounded windows. The host looks a column outside the picture up at plane x = screen x - hscroll, plane y = line + vscroll of that line; the ABI 1 provider answered
 * the same lookup with the world cell at world x = screen x + off(line) (off(line) is -hscroll up to a multiple of 512, verified per line). A plane cell (c, r) therefore holds the world cell
 * (c + k, r + dy) where k = (hscroll + off) / 8 is the line's own whole-plane shift. Lines of one plane cell row that need DIFFERENT shifts for the same plane cell cannot be expressed by one window
 * word; that (and a span wider than two windows) is reported to the caller, which then refuses the frame's scenery honestly instead of serving wrong cells.
 * `left_px` / `margin_px`: the planned per-side margin and the number of planned columns left of the picture (the centred baseline: left_px == margin_px). The windows are built for exactly that
 * pair; a placement is a different `left_px` and nothing else changes. Returns 0 on success. */
static int build_plane_windows(const SegaGenesisRenderApi *r, const Sonic1Frame *f, const uint8_t *ram, unsigned plane, unsigned height, unsigned left_px, unsigned margin_px) {
  const unsigned right_px = 2U * margin_px - left_px;
  const int *off = plane == 0U ? f->off_fg : f->off_bg;
  const int camy = plane == 0U ? f->camy : f->bgy;
  int cmin = 0, cmax = 0, rmin, rmax, rows, span, c, rr;
  unsigned l, windows;
  int16_t a_[S1_HSCROLL_LINES], b_[S1_HSCROLL_LINES], k_[S1_HSCROLL_LINES];
  for (l = 0U; l < height; ++l) {
    const int a = floor_div(-(int)left_px - f->hs[plane][l], 8), b = floor_div(319 + (int)right_px - f->hs[plane][l], 8);
    a_[l] = (int16_t)a;
    b_[l] = (int16_t)b;
    k_[l] = (int16_t)((f->hs[plane][l] + off[l]) / 8);
    if (l == 0U || a < cmin) cmin = a;
    if (l == 0U || b > cmax) cmax = b;
  }
  rmin = floor_div(f->vs[plane][0], 8);
  rmax = floor_div((int)height - 1 + f->vs[plane][0], 8);
  rows = rmax - rmin + 1;
  span = cmax - cmin + 1;
  if (rows < 1 || rows > (int)MAX_WIN_ROWS || span > SPAN_MAX) return 1;
  for (rr = 0; rr < rows; ++rr)
    for (c = 0; c < span; ++c) g_cell[rr][c] = -1;
  for (l = 0U; l < height; ++l) {
    const int row = floor_div((int)l + f->vs[plane][l], 8) - rmin;
    const int wrow = rmin + row + (camy - f->vs[plane][0]) / 8;   /* the world cell row of this plane cell row */
    for (c = a_[l]; c <= b_[l]; ++c) {
      int32_t *o = &g_cell[row][c - cmin];
      const int word = world_cell(ram, plane, c + k_[l], wrow);
      if (word < 0) return 3;
      if (*o < 0) *o = word;
      else if (*o != word) return 2;   /* one plane cell asked by two lines that need different words (per-line origins that differ by a multiple of 512) */
    }
  }
  windows = span > (int)MAX_COLS ? 2U : 1U;
  for (unsigned w = 0U; w < windows; ++w) {
    const int c0 = (w == 0U) ? cmin : cmax - (int)MAX_COLS + 1;
    const unsigned cols = windows == 1U ? (unsigned)span : MAX_COLS;
    for (rr = 0; rr < rows; ++rr)
      for (unsigned i = 0U; i < cols; ++i) {
        const int32_t word = g_cell[rr][c0 - cmin + (int)i];
        g_words[plane][w][(unsigned)rr * cols + i] = (uint16_t)(word < 0 ? 0 : word);   /* a cell no line asks is never read */
      }
    if (r->scenery_window(plane, c0, rmin, cols, (uint32_t)rows, g_words[plane][w]) != 0) return 4;
  }
  return 0;
}

/* ---------------------------------------------------------------------------------------------------------------- HUD */
/* The game's own HUD, relocated: the patch stops the HUD object queueing its sprites, and this draws exactly the same sprite pieces (same tiles, same palette lines, same rows) from the frame's
 * own VRAM and CRAM, so the font, the layout (SCORE / TIME / RINGS on top, the Sonic icon with the lives at the bottom) and the digits are the original's and there is no panel behind them. Only the
 * horizontal position differs: the host anchors the overlay at the left edge of the visible surface (or at the original place when there is no side). The overlay covers the picture rows 1:1
 * (row y of the overlay is picture row y) and the picture columns from HUD_X0 (the original's left edge). The pieces' geometry (position, size, first tile) is the HUD object's own layout. */

#define HUD_X0 16U
#define HUD_W 96U     /* picture columns 16..111 */
#define HUD_H 224U    /* picture rows 0..223 */
#define HUD_PAD 8U    /* transparent left margin of the overlay (one letter): keeps the HUD off the very edge of the screen when it is drawn beside the picture; the in-picture position is unchanged */
#define HUD_OW (HUD_W + HUD_PAD)

typedef struct HudPiece { uint8_t x, y; uint8_t cells_w, cells_h; uint16_t tile; uint8_t red_group; } HudPiece;   /* red_group: 1 = the TIME label, 2 = the RINGS label */
static const HudPiece k_hud_pieces[] = {
    {16, 8, 4, 2, 0x6CAU, 0}, {48, 8, 4, 2, 0x6E2U, 0}, {80, 8, 4, 2, 0x6EAU, 0},    /* SCORE and its digits */
    {16, 24, 4, 2, 0x6DAU, 1}, {56, 24, 4, 2, 0x6F2U, 0},                              /* TIME and its digits */
    {16, 40, 4, 2, 0x6D2U, 2}, {48, 40, 1, 2, 0x6CAU, 2}, {64, 40, 3, 2, 0x6FAU, 0},  /* RINGS and its digits */
    {16, 200, 2, 2, 0x7D4U, 0}, {32, 200, 4, 2, 0x7D8U, 0},                            /* the Sonic icon, "SONIC x" and the lives */
};

static int draw_hud(const Sonic1Frame *f, const SegaGenesisFrameView *v, const SegaGenesisVdpHelpers *vdp) {
  /* the object's frame selection: with rings none; otherwise the labels flash red in the flash phase (TIME too at 9 minutes) */
  unsigned red = 0U;
  if (f->rings == 0U && !f->flash) red = (1U << 2) | (f->minutes == 9U ? (1U << 1) : 0U);   /* bit 2: RINGS label, bit 1: TIME label */
  for (unsigned i = 0U; i < (unsigned)sizeof(g_hud_rgba); ++i) g_hud_rgba[i] = 0U;   /* fully transparent: no background */
  for (unsigned n = 0U; n < sizeof(k_hud_pieces) / sizeof(k_hud_pieces[0]); ++n) {
    const HudPiece *pc = &k_hud_pieces[n];
    const unsigned pal = ((pc->red_group == 2U && (red & 4U) != 0U) || (pc->red_group == 1U && (red & 2U) != 0U)) ? 1U : 0U;
    for (unsigned cx = 0U; cx < pc->cells_w; ++cx)
      for (unsigned cy = 0U; cy < pc->cells_h; ++cy) {
        const unsigned tile = pc->tile + cx * pc->cells_h + cy;   /* a sprite's cells are numbered down each column */
        for (unsigned row = 0U; row < 8U; ++row) {
          const unsigned py = pc->y + cy * 8U + row;
          const SegaGenesisFrameLine *line;
          if (py >= HUD_H) continue;
          line = &v->lines[py < SEGA_GEN_FRAME_MAX_LINES ? py : SEGA_GEN_FRAME_MAX_LINES - 1U];
          for (unsigned col = 0U; col < 8U; ++col) {
            const unsigned px_ = pc->x + cx * 8U + col;
            const uint8_t byte = v->vram[(tile * 32U + row * 4U + col / 2U) & 0xFFFFU];
            const unsigned index = (col & 1U) == 0U ? (unsigned)(byte >> 4) : (unsigned)(byte & 0x0FU);
            uint8_t c[3];
            uint8_t *d;
            if (index == 0U || px_ < HUD_X0 || px_ - HUD_X0 >= HUD_W) continue;
            if (vdp->cram_rgb(line->cram, pal * 16U + index, c) != 0) continue;
            d = g_hud_rgba + ((size_t)py * HUD_OW + (px_ - HUD_X0 + HUD_PAD)) * 4U;
            d[0] = c[0]; d[1] = c[1]; d[2] = c[2]; d[3] = 255U;
          }
        }
      }
  }
  return 1;
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
  Sonic1Frame *f = &g_frame;
  unsigned scenery_reason, accepted = 0U, margin_px, left_px;
  uint32_t requested;
  if (feat == NULL || feat->render == NULL || feat->frame == NULL || feat->vdp == NULL || feat->size < sizeof(SegaGenesisFeatures)) return;
  r = feat->render;
  v = feat->frame;
  vdp = feat->vdp;
  ram = v->work_ram;
  requested = v->requested;
  if (ram == NULL || v->lines == NULL || v->vram == NULL || v->height == 0U || v->height > 448U) { refuse(r, requested, REASON_BAD_STATE); return; }
  for (unsigned i = 0U; i < (unsigned)sizeof(*f); ++i) ((uint8_t *)f)[i] = 0U;
  /* the planned margin and the placement: the baseline keeps the picture centred (left_px == margin_px) and declares no placement; the adaptive-placement tasks only change how left_px is chosen.
   * A frame with no extension shown (side 0) still offers a nominal 64 px margin: the ABI 1 provider answered whatever the host asked, and a window is cheap. */
  margin_px = v->side != 0U ? v->side : 64U;
  left_px = margin_px;
  /* verified scope: a running level (0x0C). The level start sequence (0x8C: title card over a level that is still being drawn), the title, special stage and every other screen are declined. */
  if (ram[S1_GAMEMODE] == 0x10U) {   /* special stage: wrapped background only (no HUD object runs there) */
    const unsigned reason = (requested & SEGA_GEN_COMPONENT_SCENERY) != 0U ? ss_check(f, v) : REASON_UNSUPPORTED_SCENE;
    if (reason != REASON_OK) { refuse(r, requested, reason); return; }
    {
      uint8_t mask[28];
      for (unsigned i = 0U; i < 28U; ++i) mask[i] = 0xFFU;
      (void)r->scene("special-stage", 13U);
      if (r->scenery_generic_rows(0U, mask, 224U, 28U) != 0 || r->scenery_generic_rows(1U, mask, 224U, 28U) != 0) return;   /* both planes: the VDP's own wrapped plane */
    }
    return;
  }
  if (ram[S1_GAMEMODE] != 0x0CU) { refuse(r, requested, REASON_UNSUPPORTED_SCENE); return; }
  f->rings = u16(ram, S1_RINGS);
  f->lives = ram[S1_LIVES];
  f->score = (unsigned)((u16(ram, S1_SCORE) << 16) | u16(ram, S1_SCORE + 2U));
  f->minutes = ram[S1_TIME + 1U];
  f->seconds = ram[S1_TIME + 2U];
  f->flash = (ram[S1_FRAMECOUNT_FLASH] >> 3) & 1U;
  /* The HUD only needs plausible counters (any zone). The scenery additionally needs the verified Green Hill Zone world state. */
  if (f->minutes <= 9U && f->seconds <= 59U && f->score <= 999999U) accepted |= SEGA_GEN_COMPONENT_HUD;
  scenery_reason = scenery_check(f, v, vdp, ram);
  if (scenery_reason == REASON_OK) accepted |= SEGA_GEN_COMPONENT_SCENERY;
  accepted &= requested;
  if (accepted == 0U) { refuse(r, requested, scenery_reason != REASON_OK ? scenery_reason : REASON_BAD_STATE); return; }
  (void)r->scene("level", 5U);
  if ((accepted & SEGA_GEN_COMPONENT_SCENERY) != 0U) {
    if (build_plane_windows(r, f, ram, 0U, v->height, left_px, margin_px) != 0 || build_plane_windows(r, f, ram, 1U, v->height, left_px, margin_px) != 0)
      (void)r->decline(SEGA_GEN_COMPONENT_SCENERY, REASON_BAD_STATE);   /* the windows cannot express this frame's answers: never served half-way */
  }
  if ((accepted & SEGA_GEN_COMPONENT_HUD) != 0U && draw_hud(f, v, vdp) != 0) {
    (void)r->overlay_fallback(HUD_X0 - HUD_PAD, 0U);
    (void)r->overlay_bitmap(0, 0, HUD_OW, HUD_H, g_hud_rgba, HUD_OW * 4U);
  }
}

static int provider_init(void *state, const SegaModHost *host) {
  (void)state;
  return host->platform == SEGA_MOD_PLATFORM && host->platform_features != NULL ? 0 : 1;
}

static void provider_phase(void *state, const SegaModHost *host) {
  (void)state;
  if (host->phase == SEGA_MOD_PHASE_RENDER) render_frame(host);
}

static const SegaModProvider provider = {sizeof(SegaModProvider), SEGA_MOD_ABI_MAJOR, 2U, SEGA_MOD_PLATFORM, "sonic1.native-widescreen", 2U, provider_init, provider_phase, NULL, NULL, NULL,
                                         {NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL}};

const SegaModProvider *segarecomp_mod_provider(void **state_out) {
  if (state_out != NULL) *state_out = NULL;
  return &provider;
}
