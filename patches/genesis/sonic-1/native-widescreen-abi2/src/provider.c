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

/* The scenery of one plane as bounded windows plus a per-row origin delta (ABI minor 3, `scenery_row_origin`). The host looks a column outside the picture up at plane x = screen x - hscroll, plane y =
 * line + vscroll of that line; the ABI 1 provider answered the same lookup with the world cell at world x = screen x + off(line) (off(line) is -hscroll up to a multiple of 512, verified per line).
 * A line therefore needs the world cell (c + k, r + dy) for the plane cell (c, r) it asks, k = (hscroll + off) / 8 being the line's own whole-plane shift. The provider states that shift per produced
 * row as the origin delta, so the host looks up the TRANSLATED world column c + k_row; the windows are keyed by world column and plane row, i.e. by a function of the world cell alone, and two lines of
 * one plane cell row whose shifts differ by a multiple of 64 cells no longer need different words for the same window cell. Packing: one window when the translated width is at most MAX_COLS columns,
 * else two EQUAL halves up to SPAN_MAX columns, else the plane cannot be expressed and the caller declines the scenery.
 * `left_px` / `margin_px`: the planned per-side margin and the number of planned columns left of the picture (the centred baseline: left_px == margin_px). The windows are built for exactly that
 * pair; a placement is a different `left_px` and nothing else changes. Returns 0 on success. */
static int build_plane_windows(const SegaGenesisRenderApi *r, const Sonic1Frame *f, const uint8_t *ram, unsigned plane, unsigned height, unsigned left_px, unsigned margin_px) {
  const unsigned right_px = 2U * margin_px - left_px;
  const int *off = plane == 0U ? f->off_fg : f->off_bg;
  const int camy = plane == 0U ? f->camy : f->bgy;
  int cmin = 0, cmax = 0, rmin, rmax, rows, span, c, rr;
  unsigned l, windows;
  int16_t al_[S1_HSCROLL_LINES], bl_[S1_HSCROLL_LINES], ar_[S1_HSCROLL_LINES], br_[S1_HSCROLL_LINES], k_[S1_HSCROLL_LINES];
  for (l = 0U; l < height; ++l) {
    /* The host asks ONLY the off-picture pixels of a line: x = -left_px .. -1 on the left and x = 320 .. 319 + right_px on the right (never an in-picture pixel), each at plane x = x - hscroll. */
    const int a = floor_div(-(int)left_px - f->hs[plane][l], 8), b = floor_div(319 + (int)right_px - f->hs[plane][l], 8);
    const int k = (f->hs[plane][l] + off[l]) / 8;
    al_[l] = (int16_t)a;
    bl_[l] = (int16_t)floor_div(-1 - f->hs[plane][l], 8);
    ar_[l] = (int16_t)floor_div(320 - f->hs[plane][l], 8);
    br_[l] = (int16_t)b;
    k_[l] = (int16_t)k;
    if (l == 0U || a + k < cmin) cmin = a + k;   /* translated world columns */
    if (l == 0U || b + k > cmax) cmax = b + k;
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
    for (unsigned side = 0U; side < 2U; ++side)
      for (c = side == 0U ? al_[l] : ar_[l]; c <= (side == 0U ? bl_[l] : br_[l]); ++c) {
        int32_t *o = &g_cell[row][c + k_[l] - cmin];
        if (*o < 0) {
          const int word = world_cell(ram, plane, c + k_[l], wrow);
          if (word < 0) return 3;
          *o = word;   /* a function of the world cell alone: every line that asks this translated cell wants this word */
        }
      }
  }
  windows = span > (int)MAX_COLS ? 2U : 1U;
  for (unsigned w = 0U; w < windows; ++w) {
    const unsigned n0 = windows == 1U ? (unsigned)span : ((unsigned)span + 1U) / 2U;
    const int c0 = w == 0U ? cmin : cmin + (int)n0;
    const unsigned cols = windows == 1U ? (unsigned)span : (w == 0U ? n0 : (unsigned)span - n0);
    for (rr = 0; rr < rows; ++rr)
      for (unsigned i = 0U; i < cols; ++i) {
        const int32_t word = g_cell[rr][c0 - cmin + (int)i];
        g_words[plane][w][(unsigned)rr * cols + i] = (uint16_t)(word < 0 ? 0 : word);   /* a cell no line asks is never read */
      }
    if (r->scenery_window(plane, c0, rmin, cols, (uint32_t)rows, g_words[plane][w]) != 0) return 4;
  }
  if (r->scenery_row_origin(plane, k_, height, height * 2U) != 0) return 5;
  return 0;
}


/* ---------------------------------------------------------------------------------------------------------------- special stage maze in the margins */
/* The special stage's maze is sprites, and the game only builds the sprites of the blocks inside its own 320 px view (it computes the screen position of a 16 x 16 window of 24 px blocks into a position
 * buffer and culls each block against the picture). The blocks that would be visible in the widescreen margins are therefore never drawn by the game. This reconstructs them: the game's own position
 * grid is extended to more cells (positions are linear in the cell index before one rounding, so the extension is exact and is verified against all 256 buffered positions of the frame, otherwise nothing is
 * added), the sprite pieces of each block type are learned from the sprites the game DID build this frame (they are emitted in cell order, one block after the other, and a block's pieces are centred on the
 * block), and the pieces that reach into the margins are submitted as one virtual-sprite set whose art is the frame's own VRAM/CRAM. Nothing is remembered between frames and no game art is stored here. */
#define SS_SCRX 0xF700U         /* words: the stage camera (the same variables as the level camera) */
#define SS_SCRY 0xF704U
#define SS_ANGLE 0xF780U        /* word: the rotation angle; its high byte (low 2 bits cleared) indexes the sine table */
#define SS_POSBUF 0x8000U       /* 16 x 16 x (x word, y word): the screen position of every block of the window, relative to the picture centre */
#define SS_LAYOUT_STRIDE 128U   /* the maze layout (one byte per block, 128 x 128) starts at work RAM 0 */
#define SS_TYPE_MAX 0x4EU       /* block types above this are not drawn */
#define SS_ITEMS 0x4000U        /* the game's item table: per block type 8 bytes, the mapping pointer (long), the mapping frame (word) and the art-tile base (word) */
#define SS_BLOCK 24
#define SS_MAX_PIECES 4U
#define SS_SAT_MAX 80U
typedef struct { int x, y; unsigned w, h, tile; } SsSprite;              /* screen px / px / name-table-style tile word */
typedef struct { uint8_t n; int16_t x[SS_MAX_PIECES], y[SS_MAX_PIECES]; uint8_t wc[SS_MAX_PIECES], hc[SS_MAX_PIECES]; uint16_t tile[SS_MAX_PIECES]; } SsType;   /* pieces relative to the block centre */
typedef struct { uint8_t type; int cx, cy; } SsCell;
static SsType g_sstype[SS_TYPE_MAX + 1U];
static uint8_t g_ssblank[SS_TYPE_MAX + 1U];   /* 1: this type drew no sprite in this frame (it is learned as having no pieces) */
static SsSprite g_sat[SS_SAT_MAX];
static SsCell g_sscell[256];
static GenesisVirtualSpriteSet g_vset;
static struct { GenesisVirtualSprite s; int dist; } g_cand[512];

static int ss_x(int c, int s, int dx, int dy, int j) { return floor_div(c * dx - s * dy + j * c * SS_BLOCK, 256); }
static int ss_y(int c, int s, int dx, int dy, int j) { return floor_div(s * dx + c * dy + j * s * SS_BLOCK, 256); }

/* Finds the sine/cosine pair (the game's table values) and offsets that reproduce the 256 buffered block positions exactly; 0 on success. */
static int ss_fit(const uint8_t *ram, int *s_out, int *c_out, int *dx0, int *dy0) {
  const int scrx = (int)u16(ram, SS_SCRX), scry = (int)u16(ram, SS_SCRY);
  const int x00 = (int16_t)u16(ram, SS_POSBUF), x015 = (int16_t)u16(ram, SS_POSBUF + 15U * 4U);
  const int y00 = (int16_t)u16(ram, SS_POSBUF + 2U), y015 = (int16_t)u16(ram, SS_POSBUF + 15U * 4U + 2U);
  const int c0 = ((x015 - x00) * 256) / (15 * SS_BLOCK), s0 = ((y015 - y00) * 256) / (15 * SS_BLOCK);
  int s, c, i, j;
  *dx0 = -180 - scrx % SS_BLOCK;
  *dy0 = -180 - scry % SS_BLOCK;
  for (s = s0 - 3; s <= s0 + 3; ++s)
    for (c = c0 - 3; c <= c0 + 3; ++c) {
      int ok = 1;
      for (i = 0; i < 16 && ok; ++i)
        for (j = 0; j < 16; ++j) {
          const unsigned o = SS_POSBUF + (unsigned)(i * 16 + j) * 4U;
          if (ss_x(c, s, *dx0, *dy0 + SS_BLOCK * i, j) != (int16_t)u16(ram, o) || ss_y(c, s, *dx0, *dy0 + SS_BLOCK * i, j) != (int16_t)u16(ram, o + 2U)) { ok = 0; break; }
        }
      if (ok) { *s_out = s; *c_out = c; return 0; }
    }
  return 1;
}

static unsigned ss_read_sat(const SegaGenesisFrameView *v) {
  const unsigned base = ((unsigned)v->lines[0].registers[5] & 0x7EU) << 9;
  unsigned link = 0U, n = 0U;
  do {
    const uint8_t *e = v->vram + ((base + link * 8U) & 0xFFFFU);
    const unsigned size = e[2] & 0xFU;
    g_sat[n].y = (int)((((unsigned)e[0] << 8) | e[1]) & 0x3FFU) - 128;
    g_sat[n].x = (int)((((unsigned)e[6] << 8) | e[7]) & 0x1FFU) - 128;
    g_sat[n].w = (((size >> 2) & 3U) + 1U) * 8U;
    g_sat[n].h = ((size & 3U) + 1U) * 8U;
    g_sat[n].tile = ((unsigned)e[4] << 8) | e[5];
    link = e[3] & 0x7FU;
    ++n;
  } while (link != 0U && n < SS_SAT_MAX);
  return n;
}

/* The number of sprites (1..SS_MAX_PIECES) starting at `p` whose bounding box is centred on block `k`, or 0 when no such group exists. */
static unsigned ss_group(unsigned p, unsigned nsat, unsigned k) {
  int xmin = 0, xmax = 0, ymin = 0, ymax = 0;
  for (unsigned g = 0U; p + g < nsat && g < SS_MAX_PIECES; ++g) {
    const SsSprite *q = &g_sat[p + g];
    if (g == 0U || q->x < xmin) xmin = q->x;
    if (g == 0U || q->y < ymin) ymin = q->y;
    if (g == 0U || q->x + (int)q->w > xmax) xmax = q->x + (int)q->w;
    if (g == 0U || q->y + (int)q->h > ymax) ymax = q->y + (int)q->h;
    if (xmin + xmax == 2 * g_sscell[k].cx && ymin + ymax == 2 * g_sscell[k].cy) return g + 1U;
  }
  return 0U;
}

/* Learns the pieces of every block type that the game drew this frame; 0 on success. The game emits the blocks' sprites in cell order. A block's pieces are normally centred on the block. A block with no sprite at
 * all (a type whose mapping has no pieces) is recognised by the NEXT block matching the current sprite; otherwise a block whose single piece is not centred takes the next sprite (at most a quarter of the blocks may
 * need this, otherwise the sequence is misaligned and the frame is refused). Every later instance of a type must agree with the first (same pieces, offsets, sizes and tiles, or blank again): any contradiction
 * refuses the frame, so nothing is ever drawn from a type the frame itself contradicts. */
static int ss_learn(unsigned nsat, unsigned ncell) {
  for (unsigned p0 = 0U; p0 < 8U && p0 < nsat; ++p0) {
    unsigned p = p0, k, t, ok = 1U, off = 0U;
    for (t = 0U; t <= SS_TYPE_MAX; ++t) { g_sstype[t].n = 0U; g_ssblank[t] = 0U; }
    for (k = 0U; k < ncell && ok != 0U; ++k) {
      unsigned g;
      if (p >= nsat) break;   /* the game ran out of sprites: the remaining blocks have none */
      g = ss_group(p, nsat, k);
      t = g_sscell[k].type;
      if (g == 0U && k + 1U < ncell && ss_group(p, nsat, k + 1U) != 0U) {   /* this block drew nothing */
        if (g_ssblank[t] == 0U && g_sstype[t].n != 0U) ok = 0U;
        g_ssblank[t] = 1U;
        continue;
      }
      if (g == 0U) {
        g = 1U;   /* a single piece that is not centred on its block */
        ++off;
        if (off * 4U > ncell + 3U) { ok = 0U; break; }
      }
      if (g_ssblank[t] != 0U) { ok = 0U; break; }
      if (g_sstype[t].n == 0U) {
        g_sstype[t].n = (uint8_t)g;
        for (unsigned q = 0U; q < g; ++q) {
          const SsSprite *sp = &g_sat[p + q];
          g_sstype[t].x[q] = (int16_t)(sp->x - g_sscell[k].cx);
          g_sstype[t].y[q] = (int16_t)(sp->y - g_sscell[k].cy);
          g_sstype[t].wc[q] = (uint8_t)(sp->w / 8U);
          g_sstype[t].hc[q] = (uint8_t)(sp->h / 8U);
          g_sstype[t].tile[q] = (uint16_t)sp->tile;
        }
      } else if (g_sstype[t].n != g) {
        ok = 0U;
      } else {
        for (unsigned q = 0U; q < g; ++q) {
          const SsSprite *sp = &g_sat[p + q];
          if (g_sstype[t].x[q] != (int16_t)(sp->x - g_sscell[k].cx) || g_sstype[t].y[q] != (int16_t)(sp->y - g_sscell[k].cy) || g_sstype[t].wc[q] != (uint8_t)(sp->w / 8U) ||
              g_sstype[t].hc[q] != (uint8_t)(sp->h / 8U) || g_sstype[t].tile[q] != (uint16_t)sp->tile) ok = 0U;
        }
      }
      p += g;
    }
    if (ok != 0U && k > 0U) return 0;
  }
  return 1;
}

/* A block type with no instance in the picture shares its mapping, and therefore its pieces, with every type that has the same mapping pointer and frame in the game's item table (verified on every group of
 * the real stage: identical geometry, and each piece's tile is the type's art-tile base plus the same offset), so only the base differs. The pieces are derived from a type that was seen, never invented. */
static void ss_derive(const uint8_t *ram) {
  uint8_t seen[SS_TYPE_MAX + 1U];
  unsigned t, u, q;
  for (t = 0U; t <= SS_TYPE_MAX; ++t) seen[t] = g_sstype[t].n != 0U || g_ssblank[t] != 0U;
  for (t = 1U; t <= SS_TYPE_MAX; ++t) {
    const unsigned ot = SS_ITEMS + t * 8U;
    if (seen[t] != 0U || (u16(ram, ot) | u16(ram, ot + 2U)) == 0U) continue;   /* (a blank type is a learned type too) */
    for (u = 1U; u <= SS_TYPE_MAX; ++u) {
      const unsigned ou = SS_ITEMS + u * 8U;
      if (seen[u] == 0U || u16(ram, ou) != u16(ram, ot) || u16(ram, ou + 2U) != u16(ram, ot + 2U) || u16(ram, ou + 4U) != u16(ram, ot + 4U)) continue;
      if (g_ssblank[u] != 0U) { g_ssblank[t] = 1U; break; }
      g_sstype[t].n = g_sstype[u].n;
      for (q = 0U; q < g_sstype[u].n; ++q) {
        g_sstype[t].x[q] = g_sstype[u].x[q];
        g_sstype[t].y[q] = g_sstype[u].y[q];
        g_sstype[t].wc[q] = g_sstype[u].wc[q];
        g_sstype[t].hc[q] = g_sstype[u].hc[q];
        g_sstype[t].tile[q] = (uint16_t)(g_sstype[u].tile[q] + u16(ram, ot + 6U) - u16(ram, ou + 6U));
      }
      break;
    }
  }
}

/* Submits the maze blocks that reach into the margins as virtual sprites (presentation space). Silent on any doubt: the frame then simply has no maze in its margins, as before. */
static void ss_margin_maze(const SegaGenesisRenderApi *r, const SegaGenesisFrameView *v, const uint8_t *ram, unsigned left_px, unsigned margin_px) {
  const int right_px = (int)(2U * margin_px - left_px), lpx = (int)left_px;
  const int scrx = (int)u16(ram, SS_SCRX), scry = (int)u16(ram, SS_SCRY);
  int s, c, dx0, dy0, i, j;
  unsigned nsat, ncell = 0U, ncand = 0U, n, q;
  if (margin_px == 0U || v->lines == NULL || v->vram == NULL) return;
  if (ss_fit(ram, &s, &c, &dx0, &dy0) != 0) return;
  /* the blocks the game drew: its own 16 x 16 window, culled against the picture exactly as the game does (position + 0x120 in [0x70, 0x1D0), position + 0xF0 in [0x70, 0x170)) */
  for (i = 0; i < 16; ++i)
    for (j = 0; j < 16; ++j) {
      const unsigned o = SS_POSBUF + (unsigned)(i * 16 + j) * 4U;
      const int px = (int16_t)u16(ram, o), py = (int16_t)u16(ram, o + 2U);
      const unsigned t = ram[(((unsigned)(scry / SS_BLOCK + i)) * SS_LAYOUT_STRIDE + (unsigned)(scrx / SS_BLOCK + j)) & 0xFFFFU];
      if (t == 0U || t > SS_TYPE_MAX || px < -176 || px >= 176 || py < -128 || py >= 128) continue;
      g_sscell[ncell].type = (uint8_t)t;
      g_sscell[ncell].cx = px + 160;
      g_sscell[ncell].cy = py + 112;
      ++ncell;
    }
  nsat = ss_read_sat(v);
  if (ss_learn(nsat, ncell) != 0) return;
  ss_derive(ram);
  for (i = -24; i < 40; ++i)
    for (j = -24; j < 40; ++j) {
      const int row = scry / SS_BLOCK + i, col = scrx / SS_BLOCK + j;
      const int cx = ss_x(c, s, dx0, dy0 + SS_BLOCK * i, j) + 160, cy = ss_y(c, s, dx0, dy0 + SS_BLOCK * i, j) + 112;
      unsigned t;
      const int kept = i >= 0 && i < 16 && j >= 0 && j < 16 && cx >= -16 && cx < 336 && cy >= -16 && cy < 240;
      if (row < 0 || row >= 128 || col < 0 || col >= 128 || cy < -16 || cy >= 240 || cx < -16 - lpx || cx >= 336 + right_px) continue;
      t = ram[(unsigned)row * SS_LAYOUT_STRIDE + (unsigned)col];
      if (t == 0U || t > SS_TYPE_MAX || g_sstype[t].n == 0U) continue;
      for (q = 0U; q < g_sstype[t].n && ncand < 512U; ++q) {
        const int x = cx + g_sstype[t].x[q], y = cy + g_sstype[t].y[q], w = (int)g_sstype[t].wc[q] * 8;
        GenesisVirtualSprite *sp = &g_cand[ncand].s;
        if ((x >= 0 && x + w <= 320) || x + w <= -lpx || x >= 320 + right_px) continue;   /* wholly inside the picture (the game drew it) or beyond what is presented */
        for (unsigned zb = 0U; zb < (unsigned)sizeof(*sp); ++zb) ((uint8_t *)sp)[zb] = 0U;
        sp->provenance = GENESIS_VSPRITE_MOD_AUTHORED;
        sp->layer = (g_sstype[t].tile[q] & 0x8000U) != 0U ? GENESIS_VSPRITE_LAYER_ABOVE_ALL : GENESIS_VSPRITE_LAYER_BETWEEN;
        sp->width_cells = g_sstype[t].wc[q];
        sp->height_cells = g_sstype[t].hc[q];
        sp->palette = (uint8_t)((g_sstype[t].tile[q] >> 13) & 3U);
        sp->v_flip = (uint8_t)((g_sstype[t].tile[q] >> 12) & 1U);
        sp->h_flip = (uint8_t)((g_sstype[t].tile[q] >> 11) & 1U);
        sp->tile_index = (uint16_t)(g_sstype[t].tile[q] & 0x7FFU);
        sp->x = (int16_t)x;
        sp->y = (int16_t)y;
        if (kept) sp->flags = GENESIS_VSPRITE_FLAG_HARDWARE_PIECE;   /* the game's own sprite table holds this piece: the host does not draw it twice where it draws that layer */
        if (x < 0 && x + w > 0) { sp->has_clip = 1U; sp->clip_x = (int16_t)(-lpx); sp->clip_y = 0; sp->clip_w = (uint16_t)(lpx > 320 ? 320 : lpx); sp->clip_h = (uint16_t)v->height; if (lpx > 320) sp->clip_x = -320; }   /* only the margin part: the picture keeps its native pixels */
        else if (x < 320 && x + w > 320) { sp->has_clip = 1U; sp->clip_x = 320; sp->clip_y = 0; sp->clip_w = (uint16_t)(right_px > 320 ? 320 : right_px); sp->clip_h = (uint16_t)v->height; }
        g_cand[ncand].dist = x < 0 ? -x : x + w - 320;
        ++ncand;
      }
    }
  if (ncand == 0U) return;
  /* at most GENESIS_VSPRITE_MAX commands: over the limit the pieces farthest from the picture are dropped one at a time; the remaining pieces keep the game's cell order (the first command wins, as in the game's
   * own sprite table), so overlapping blocks stack exactly as the game stacks them */
  while (ncand > GENESIS_VSPRITE_MAX) {
    unsigned drop = 0U;
    for (q = 1U; q < ncand; ++q) if (g_cand[q].dist >= g_cand[drop].dist) drop = q;
    for (q = drop; q + 1U < ncand; ++q) g_cand[q] = g_cand[q + 1U];
    --ncand;
  }
  for (n = 0U; n < ncand; ++n) g_vset.sprites[n] = g_cand[n].s;
  g_vset.budget_mode = GENESIS_VSPRITE_BUDGET_EXTENDED;
  g_vset.space = GENESIS_VSPRITE_SPACE_PRESENTATION;
  g_vset.count = n;
  for (q = 0U; q < GENESIS_VSPRITE_VRAM_BYTES; ++q) g_vset.authored_vram[q] = v->vram[q];
  for (q = 0U; q < GENESIS_VSPRITE_CRAM_BYTES; ++q) g_vset.authored_cram[q] = v->lines[0].cram[q];
  (void)r->virtual_sprites(&g_vset);
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
      if (v->side != 0U) ss_margin_maze(r, v, ram, left_px, margin_px);   /* the maze blocks the game culls at the picture edges, drawn into the margins */
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

static const SegaModProvider provider = {sizeof(SegaModProvider), SEGA_MOD_ABI_MAJOR, 3U, SEGA_MOD_PLATFORM, "sonic1.native-widescreen", 2U, provider_init, provider_phase, NULL, NULL, NULL,
                                         {NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL}};

const SegaModProvider *segarecomp_mod_provider(void **state_out) {
  if (state_out != NULL) *state_out = NULL;
  return &provider;
}
