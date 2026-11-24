/*
 * Sonic the Hedgehog 2 (Genesis) native widescreen provider for the schema 3 / native ABI 2 SDK (segarecomp_mod_genesis.h, minor 2): the port of the ABI 1 provider of
 * patches/genesis/sonic-2/native-widescreen with the SAME game knowledge, constants and verification logic (SEG-152-T010, ADR 0320). One source serves both supported images (World REV00 and JUE REV01;
 * the identity is enforced by the package: each revision is its own project and package, as in ABI 1).
 *
 * What changes is only how the answers are delivered: the per-cell scenery callback becomes bounded scenery WINDOWS built from the exact-frame view plus the per-row generic mask for the lines the ABI 1 provider
 * answered from the VDP's own plane, the HUD overlay becomes one RGBA bitmap, and a frame the provider does not serve is refused with the ABI 1 diagnostic reason (a refusal, never a fault).
 * The state map was derived independently for this image (it is NOT the Sonic 1 map).
 */
#include <segarecomp_mod_genesis.h>

/* Work-RAM map (offsets into the 64 KiB work RAM) */
#define S2_CHUNKS 0x0000U      /* chunk table: 256 chunks of 0x80 bytes = 8x8 block words (16x16 px blocks), a chunk covers 128x128 px; chunk 0 is an ordinary chunk (NOT empty, unlike Sonic 1) */
#define S2_CHUNK_BYTES 0x80U
#define S2_LAYOUT 0x8000U      /* level layout: 16 interleaved row pairs of 0x100 bytes: foreground row r at +r*0x100, background row r at +r*0x100+0x80; one byte = chunk index (all 8 bits) */
#define S2_LAYOUT_ROWS 16U
#define S2_LAYOUT_COLS 128U
#define S2_BLOCKS 0x9000U      /* block table: 8 bytes (4 name-table words: TL TR BL BR) per 16x16 block, indexed by the low 10 bits of a chunk word */
#define S2_BLOCK_MASK 0x3FFU
#define S2_GAMEMODE 0xF600U    /* byte: 0x0C = running level */
#define S2_ZONE 0xFE10U        /* bytes: zone, act (zone 0 = Emerald Hill) */
#define S2_CAMX 0xEE00U        /* words: foreground camera x, y (world pixels) */
#define S2_CAMY 0xEE04U
#define S2_VSCROLL_FG 0xF616U  /* words: the vertical scroll the game hands to the VDP at VBlank (foreground, background), unwrapped: the camera plus any screen shake. The background's x scroll is the unwrapped per-line value in the scroll buffer */
#define S2_VSCROLL_BG 0xF618U
#define S2_HSCROLL 0xE000U     /* per-line scroll buffer copied to the VDP at VBlank: 224 x (foreground word, background word), signed, NOT wrapped */
#define S2_HSCROLL_LINES 224U
#define S2_LEVEL_STARTED 0xF711U /* byte: non-zero once the title card is over; the game builds its HUD sprites only then */
#define S2_TWO_PLAYER 0xFFD8U  /* word: split-screen mode (its own HUD builders, which the BPS does not touch) */
#define S2_RINGS 0xFE20U       /* word: ring count */
#define S2_MINUTES 0xFE23U     /* byte: timer minutes */
#define S2_FLASH 0xFE05U       /* byte: bit 3 is the HUD flash phase */
#define S2_EDGE 48U            /* width in pixels of the picture's left and right edge bands whose cells are judged apart from the centre (the original leaves them stale while it streams) */
#define S2_OWN_MAX 32U         /* most lines per plane that may be answered from the VDP's own plane in one frame */
#define S2_WORLD_W (S2_LAYOUT_COLS * 128)
#define S2_WORLD_H (S2_LAYOUT_ROWS * 128)

#define HUD_X0 16U
#define HUD_W 96U     /* picture columns 16..111 */
#define HUD_H 216U    /* picture rows 0..215 (the lives row ends at 215) */
#define HUD_PAD 8U    /* transparent left margin of the overlay (one letter): keeps the HUD off the very edge of the screen when it is drawn beside the picture; the in-picture position is unchanged */
#define HUD_OW (HUD_W + HUD_PAD)


#define REASON_OK 0U
#define REASON_UNSUPPORTED_SCENE SEGA_GEN_REASON_UNSUPPORTED_SCENE
#define REASON_BAD_STATE SEGA_GEN_REASON_BAD_STATE
#define REASON_BAD_SCROLL SEGA_GEN_REASON_BAD_SCROLL
#define REASON_MISMATCH SEGA_GEN_REASON_MISMATCH
#define MAX_COLS 128U
#define MAX_WIN_ROWS 32U
#define SPAN_MAX 256
#define RENDER_LAG 1U   /* the exact-frame render of produced frame N receives the RAM of the end of guest frame N - 1 */

/* The background layout is toroidal (positions outside it wrap); the foreground outside the level is blank. How many pixels the background repeats is zone-specific: Emerald Hill, Hill Top, Oil Ocean and
 * Death Egg draw their background from the first four chunk columns only (verified against the VDP in every sampled frame: any wider period disagrees), every other zone from the whole 128-column layout. */
static int wrap_to(int v, int size) { const int m = v % size; return m < 0 ? m + size : m; }

/* Metropolis (zone ids 4 and 5) is a vertically wrapping level: the camera runs above the top and below the bottom of the layout and the foreground wraps too (verified against the VDP). Every other zone is blank outside the level. */
static int fg_wraps_vertically(unsigned zone) { return zone == 4U || zone == 5U; }

/* Hill Top is the one zone whose background wraps per layout row: its first two chunk rows (the sky and mountains, world y < 256) repeat every four chunks, the lower rows (the lava / cave band the camera reaches
 * near the bottom of the act) use the whole layout (verified row by row against the VDP in sampled frames of both acts). */
static int bg_period_at(unsigned zone, int wy) {
  if (zone == 7U) return wy < 256 ? 512 : (int)S2_WORLD_W;
  return (zone == 0U || zone == 10U || zone == 14U) ? 512 : (int)S2_WORLD_W;
}

static unsigned u16(const uint8_t *r, unsigned a) { return ((unsigned)r[a & 0xFFFFU] << 8) | r[(a + 1U) & 0xFFFFU]; }

/* Name-table word of the 8x8 cell containing world pixel (wx, wy) of layout `plane` (0 foreground, 1 background). Every address is bounded by construction (< 0x10000). */
static unsigned world_cell(const uint8_t *ram, unsigned plane, unsigned wx, unsigned wy) {
  const unsigned chunk = ram[S2_LAYOUT + (wy >> 7) * 0x100U + plane * 0x80U + (wx >> 7)];
  unsigned bw, block, fx, fy, col, row, word;
  bw = u16(ram, S2_CHUNKS + chunk * S2_CHUNK_BYTES + ((((wy & 127U) >> 4) * 8U) + ((wx & 127U) >> 4)) * 2U);
  block = bw & S2_BLOCK_MASK;
  fx = (bw >> 10) & 1U;
  fy = (bw >> 11) & 1U;
  col = ((wx & 15U) >> 3) ^ fx;
  row = ((wy & 15U) >> 3) ^ fy;
  word = u16(ram, S2_BLOCKS + block * 8U + (row * 2U + col) * 2U);
  return word ^ (fx ? 0x0800U : 0U) ^ (fy ? 0x1000U : 0U);
}


#define HUD_X0 16U
#define HUD_W 96U     /* picture columns 16..111 */
#define HUD_H 216U    /* picture rows 0..215 (the lives row ends at 215) */
#define HUD_PAD 8U    /* transparent left margin of the overlay (one letter): keeps the HUD off the very edge of the screen when it is drawn beside the picture; the in-picture position is unchanged */
#define HUD_OW (HUD_W + HUD_PAD)

typedef struct Sonic2Frame {
  unsigned accepted;
  int camy;
  int bgy;
  int fg_wrap_y;                  /* 1: the foreground layout wraps vertically (Metropolis) */
  unsigned zone;                  /* the zone id the frame was verified for */
  int off_fg[S2_HSCROLL_LINES];   /* world x of screen column 0 per output line (the game's own unwrapped foreground scroll) */
  int off_bg[S2_HSCROLL_LINES];   /* the same for the background (its own parallax per line) */
  int hs[2][S2_HSCROLL_LINES];    /* the horizontal scroll the VDP applies to each line of each plane, as the host reads it */
  int vs[2][S2_HSCROLL_LINES];    /* the vertical scroll of each plane, as the host reads it */
  unsigned height;                /* valid output lines */
  uint8_t own_plane[S2_HSCROLL_LINES][2];   /* 1: this line of this plane is answered by the VDP's own plane (identity check, see scenery_check) */
  uint8_t own[S2_HSCROLL_LINES];  /* 1: the game scrolls this line differently from the camera (the last two lines carry scroll 0): answered by the VDP's own plane, not the world */
  unsigned hud_frame;             /* HUD: the game's label-frame selection (bit 0: RINGS label red, bit 1: TIME label red) */
} Sonic2Frame;

static Sonic2Frame g_frame;
static uint16_t g_words[2][2][MAX_COLS * MAX_WIN_ROWS];   /* [plane][window] */
static int32_t g_cell[MAX_WIN_ROWS][SPAN_MAX];            /* the answer of a plane cell as the lines that ask it want it, or -1 while no line asked */
static uint8_t g_hud_rgba[HUD_OW * HUD_H * 4U];

static int floor_div(int a, int b) { return a >= 0 ? a / b : -((-a + b - 1) / b); }

/* Zone ids (the game's internal numbering) and acts the provider is verified for: the single-player campaign. Every frame is additionally identity-checked against the VDP, so membership alone never
 * accepts anything. 0 Emerald Hill, 4 Metropolis (acts 1-2), 5 Metropolis act 3, 6 Wing Fortress, 7 Hill Top, 10 Oil Ocean, 11 Mystic Cave, 12 Casino Night, 13 Chemical Plant, 14 Death Egg, 15 Aquatic
 * Ruin, 16 Sky Chase. */
static int scenery_scope(unsigned zone, unsigned act) {
  switch (zone) {
    case 0U: case 4U: case 7U: case 10U: case 11U: case 12U: case 13U: case 15U: return act <= 1U;
    case 5U: case 6U: case 14U: case 16U: return act == 0U;
    default: return 0;
  }
}

static unsigned scenery_check(Sonic2Frame *f, const SegaGenesisFrameView *v, const SegaGenesisVdpHelpers *vdp, const uint8_t *ram) {
  unsigned fg_total = 0U, fg_bad = 0U, bg_total = 0U, bg_bad = 0U, own_lines[2] = {0U, 0U}, edge_total = 0U, edge_bad = 0U;
  if (!scenery_scope(ram[S2_ZONE], ram[S2_ZONE + 1U])) return REASON_UNSUPPORTED_SCENE;
  f->camy = (int16_t)u16(ram, S2_VSCROLL_FG);
  if (v->height > S2_HSCROLL_LINES || u16(ram, S2_CAMX) >= S2_WORLD_W || (f->camy >= (int)S2_WORLD_H && !fg_wraps_vertically(ram[S2_ZONE]))) return REASON_BAD_STATE;
  if (v->width != 320U) return REASON_BAD_STATE;
  f->bgy = (int16_t)u16(ram, S2_VSCROLL_BG);
  f->zone = ram[S2_ZONE];
  f->fg_wrap_y = fg_wraps_vertically(ram[S2_ZONE]);
  /* The display must be the verified configuration (64x32 planes, per-line horizontal scroll, full-screen vertical scroll, 320 wide, no interlace) and the scroll the VDP applies (copied from the
   * game's buffer at the previous VBlank) must equal the game's own unwrapped values line by line: then RAM and VDP describe the same frame. */
  for (unsigned l = 0U; l < v->height; ++l) {
    const SegaGenesisFrameLine *line = &v->lines[l];
    int32_t ha = 0, hb = 0, va = 0, vb = 0;
    const int ram_a = (int16_t)u16(ram, S2_HSCROLL + l * 4U), ram_b = (int16_t)u16(ram, S2_HSCROLL + l * 4U + 2U);
    if ((line->registers[16] & 0x33U) != 0x01U || (line->registers[11] & 7U) != 3U || (line->registers[12] & 0x87U) != 0x81U || line->registers[17] != 0U || line->registers[18] != 0U ||
        vdp->vscroll_is_per_column(line->registers))
      return REASON_BAD_SCROLL;
    if (vdp->read_hscroll(v->vram, line->registers, 0U, l, &ha) != 0 || vdp->read_hscroll(v->vram, line->registers, 1U, l, &hb) != 0 ||
        vdp->read_vscroll(line->vsram, line->registers, 0U, 0U, &va) != 0 || vdp->read_vscroll(line->vsram, line->registers, 1U, 0U, &vb) != 0)
      return REASON_BAD_SCROLL;
    if ((((int)ha - ram_a) & 0x3FF) != 0 || (((int)hb - ram_b) & 0x3FF) != 0 || (((int)va - f->camy) & 0x3FF) != 0 || (((int)vb - f->bgy) & 0x3FF) != 0) return REASON_BAD_SCROLL;
    f->off_fg[l] = -ram_a;
    f->off_bg[l] = -ram_b;
    f->hs[0][l] = (int)ha;
    f->hs[1][l] = (int)hb;
    f->vs[0][l] = (int)va;
    f->vs[1][l] = (int)vb;
  }
  /* The game's buffer holds the camera scroll on every line except the last two, which carry 0 (verified in the live game). Those lines are not world-scrolled: they are answered by the VDP's own
   * plane (never claimed as reconstruction beyond what the VDP shows). Any other disagreement between lines is not the verified configuration. */
  for (unsigned l = 0U; l < v->height; ++l) {
    if (f->off_fg[l] == f->off_fg[0]) continue;
    if (l + 2U >= v->height && f->off_fg[l] == 0) { f->own[l] = 1U; continue; }
    return REASON_BAD_SCROLL;
  }
  f->height = v->height;
  /* Frame identity: the provider's own cells for the part of the world the picture shows must agree with what the VDP name tables hold there. A gross disagreement (a fade, a transition, another
   * level than the state claims) declines the frame; it is never half-served. A single line of one plane that the game itself leaves unlike the world (the VDP shows blanks above a background the layout
   * says is there, for instance) is answered by the VDP's own plane for that line and plane - what the unextended game shows - and never claimed as reconstruction; at most OWN_MAX such lines
   * per plane are tolerated in one frame. */
  for (unsigned l = 0U; l < v->height; ++l) {
    const SegaGenesisFrameLine *line = &v->lines[l];
    int32_t hs[2] = {0, 0}, vs[2] = {0, 0};
    (void)vdp->read_hscroll(v->vram, line->registers, 0U, l, &hs[0]);
    (void)vdp->read_hscroll(v->vram, line->registers, 1U, l, &hs[1]);
    (void)vdp->read_vscroll(line->vsram, line->registers, 0U, 0U, &vs[0]);
    (void)vdp->read_vscroll(line->vsram, line->registers, 1U, 0U, &vs[1]);
    if (f->own[l] != 0U) continue;
    for (unsigned plane = 0U; plane < 2U; ++plane) {
      const unsigned base = plane == 0U ? (unsigned)(line->registers[2] & 0x38U) << 10 : (unsigned)(line->registers[4] & 7U) << 13;
      unsigned total = 0U, bad = 0U;
      for (int x = 0; x < (int)v->width; x += 8) {
        const int edge = x < (int)S2_EDGE || x >= (int)v->width - (int)S2_EDGE;
        int wx = x + (plane == 0U ? f->off_fg[l] : f->off_bg[l]);
        int wy = (int)l + (plane == 0U ? f->camy : f->bgy);
        const unsigned px = (unsigned)(x - (int)hs[plane]) & 511U, py = (unsigned)((int)l + (int)vs[plane]) & 255U;
        const unsigned a = base + ((py >> 3) * 64U + (px >> 3)) * 2U;
        const unsigned vw = ((unsigned)v->vram[a & 0xFFFFU] << 8) | v->vram[(a + 1U) & 0xFFFFU];
        unsigned w = 0U;
        if (plane == 1U) { wy = wrap_to(wy, (int)S2_WORLD_H); wx = wrap_to(wx, bg_period_at(f->zone, wy)); }
        else if (f->fg_wrap_y) wy = wrap_to(wy, (int)S2_WORLD_H);
        if (wx >= 0 && wy >= 0 && wx < (int)S2_WORLD_W && wy < (int)S2_WORLD_H) w = world_cell(ram, plane, (unsigned)wx, (unsigned)wy);
        if (edge) {   /* the outermost cells of the picture are the ones the game's streaming leaves stale: accounted separately */
          ++edge_total;
          if (w != vw && !((vw & 0x7FFU) == 0U && (w & 0x7FFU) == 0U)) ++edge_bad;
          continue;
        }
        ++total;
        if (w != vw && !((vw & 0x7FFU) == 0U && (w & 0x7FFU) == 0U)) ++bad;
      }
      if (bad * 10U > total) {   /* this line of this plane is not the world the layout describes: the VDP's own plane answers it */
        f->own_plane[l][plane] = 1U;
        if (++own_lines[plane] > S2_OWN_MAX) return REASON_MISMATCH;
      } else if (plane == 0U) { fg_total += total; fg_bad += bad; }
      else { bg_total += total; bg_bad += bad; }
    }
  }
  if (fg_total == 0U || fg_bad * 50U > fg_total || bg_bad * 50U > bg_total || edge_bad * 2U > edge_total) return REASON_MISMATCH;
  return REASON_OK;
}

/* The answer of the ABI 1 `scenery_word` for world pixel column `wx` (already in world coordinates, unwrapped) and plane row `wy`: the world cell the layout describes, wrapped as the zone wraps. */
static unsigned world_answer(const uint8_t *ram, const Sonic2Frame *f, unsigned plane, int wx, int wy) {
  if (plane == 1U) { wy = wrap_to(wy, (int)S2_WORLD_H); wx = wrap_to(wx, bg_period_at(f->zone, wy)); }
  else if (f->fg_wrap_y) wy = wrap_to(wy, (int)S2_WORLD_H);
  if (wx < 0 || wy < 0 || wx >= (int)S2_WORLD_W || wy >= (int)S2_WORLD_H) return 0U;   /* outside the level: no world, a blank cell */
  return world_cell(ram, plane, (unsigned)wx, (unsigned)wy);
}

/* The scenery of one plane as bounded windows plus the per-row generic mask (the lines the ABI 1 provider answered from the VDP's own plane). The host looks a column outside the picture up at plane x = screen x - hscroll,
 * plane y = line + vscroll; the ABI 1 provider answered the same lookup with the world cell at world x = screen x + off(line). Plane cell (c, r) of line l holds the world cell at world pixel x = 8c + hscroll(l) + off(l).
 * Two lines that need DIFFERENT words for one plane cell cannot be expressed by one window word: reported (return 2) and the frame's scenery is refused honestly instead of serving wrong cells. Returns 0 on success.
 * `left_px` / `margin_px`: the planned per-side margin and the number of planned columns left of the picture (the centred baseline: left_px == margin_px). */
static int build_plane_windows(const SegaGenesisRenderApi *r, const Sonic2Frame *f, const uint8_t *ram, unsigned plane, unsigned left_px, unsigned margin_px, uint8_t mask[28], unsigned *any_mask) {
  const unsigned right_px = 2U * margin_px - left_px, height = f->height;
  const int *off = plane == 0U ? f->off_fg : f->off_bg;
  const int camy = plane == 0U ? f->camy : f->bgy;
  int cmin = 0, cmax = 0, rmin = 0, rmax = 0, rows, span, c, rr, have = 0;
  unsigned l, windows;
  int al_[S2_HSCROLL_LINES], bl_[S2_HSCROLL_LINES], ar_[S2_HSCROLL_LINES], br_[S2_HSCROLL_LINES];
  for (l = 0U; l < 28U; ++l) mask[l] = 0U;
  for (l = 0U; l < height; ++l) {
    const int a = floor_div(-(int)left_px - f->hs[plane][l], 8), b = floor_div(319 + (int)right_px - f->hs[plane][l], 8), row = floor_div((int)l + f->vs[plane][l], 8);
    if (f->own[l] != 0U || f->own_plane[l][plane] != 0U) {   /* answered by the VDP's own plane: marks the screen row, asks the windows nothing */
      mask[l >> 3] = (uint8_t)(mask[l >> 3] | (1U << (l & 7U)));
      *any_mask = 1U;
      al_[l] = 1; bl_[l] = 0; ar_[l] = 1; br_[l] = 0;
      continue;
    }
    al_[l] = a;   /* the host asks ONLY the off-picture pixels of a line: x = -left_px .. -1 and x = 320 .. 319 + right_px */
    bl_[l] = floor_div(-1 - f->hs[plane][l], 8);
    ar_[l] = floor_div(320 - f->hs[plane][l], 8);
    br_[l] = b;
    if (!have || a < cmin) cmin = a;
    if (!have || b > cmax) cmax = b;
    if (!have || row < rmin) rmin = row;
    if (!have || row > rmax) rmax = row;
    have = 1;
  }
  if (!have) return 0;   /* every line of this plane is answered by the VDP: no window */
  rows = rmax - rmin + 1;
  span = cmax - cmin + 1;
  if (rows < 1 || rows > (int)MAX_WIN_ROWS || span > SPAN_MAX) return 1;
  for (rr = 0; rr < rows; ++rr)
    for (c = 0; c < span; ++c) g_cell[rr][c] = -1;
  for (l = 0U; l < height; ++l) {
    const int row = floor_div((int)l + f->vs[plane][l], 8) - rmin;
    const int wrow = rmin + row + (camy - f->vs[plane][0]) / 8;
    if (al_[l] > bl_[l] && ar_[l] > br_[l]) continue;
    for (unsigned side = 0U; side < 2U; ++side)
      for (c = side == 0U ? al_[l] : ar_[l]; c <= (side == 0U ? bl_[l] : br_[l]); ++c) {
        int32_t *o = &g_cell[row][c - cmin];
        const int word = (int)world_answer(ram, f, plane, c * 8 + f->hs[plane][l] + off[l], wrow * 8);
        if (*o < 0) *o = word;
        else if (*o != word) return 2;   /* one plane cell asked by two lines that need different words */
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
/* The game's own one-player HUD, relocated. The package's BPS removes the single call that queues the HUD's ten sprite pieces (counters, timers and the HUD art updates are untouched); this draws the same
 * pieces (same tiles, same palette lines, same rows) from the frame's own VRAM and CRAM, so the font, the layout (SCORE / TIME / RINGS on top, the character icon and the lives at the bottom) and the digits are
 * the original's and there is no panel behind them. Only the horizontal position differs: the host anchors the overlay at the left edge of the visible surface (or at the original place when there is no side).
 * The overlay covers the picture rows 1:1 and the picture columns from HUD_X0. Layout and palette selection were read from the game's HUD mapping frames and checked frame by frame against the unmodified game. */

/* group: 1 = TIME label (red in the frame's bit 1), 2 = RINGS label and its extra cell (red in bit 0). The normal palette line is 1, the red one 0; the character icon always uses line 0. */
typedef struct HudPiece { uint8_t x, y; uint8_t cells_w, cells_h; uint16_t tile; uint8_t group, line; } HudPiece;
static const HudPiece k_hud_pieces[] = {
    {16, 8, 4, 2, 0x6CAU, 0, 1}, {48, 8, 4, 2, 0x6E2U, 0, 1}, {80, 8, 4, 2, 0x6EAU, 0, 1},   /* SCORE and its digits */
    {16, 24, 4, 2, 0x6DAU, 1, 1}, {56, 24, 4, 2, 0x6F2U, 0, 1},                              /* TIME and its digits */
    {16, 40, 4, 2, 0x6D2U, 2, 1}, {48, 40, 1, 2, 0x6CAU, 2, 1}, {64, 40, 3, 2, 0x6FAU, 0, 1}, /* RINGS and its digits */
    {16, 200, 2, 2, 0x7D4U, 0, 0}, {32, 200, 4, 2, 0x7D8U, 0, 1},                           /* the character icon, and the name and lives */
};


static void draw_hud(const Sonic2Frame *f, const SegaGenesisFrameView *v, const SegaGenesisVdpHelpers *vdp) {
  for (unsigned i = 0U; i < (unsigned)sizeof(g_hud_rgba); ++i) g_hud_rgba[i] = 0U;   /* fully transparent: no background */
  for (unsigned n = 0U; n < sizeof(k_hud_pieces) / sizeof(k_hud_pieces[0]); ++n) {
    const HudPiece *pc = &k_hud_pieces[n];
    const unsigned pal = (pc->group == 1U && (f->hud_frame & 2U) != 0U) || (pc->group == 2U && (f->hud_frame & 1U) != 0U) ? 0U : pc->line;
    for (unsigned cx = 0U; cx < pc->cells_w; ++cx)
      for (unsigned cy = 0U; cy < pc->cells_h; ++cy) {
        const unsigned tile = pc->tile + cx * pc->cells_h + cy;   /* a sprite's cells are numbered down each column */
        for (unsigned row = 0U; row < 8U; ++row) {
          const unsigned py = pc->y + cy * 8U + row;
          const SegaGenesisFrameLine *line;
          if (py >= HUD_H) continue;
          line = &v->lines[py];
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
}

/* ---------------------------------------------------------------------------------------------------------------- the exact-frame render */

/* game modes in which the level engine runs: 0x0C a level, 0x08 an attract-mode demo (the same engine, replaying recorded input) */
static int level_mode(const uint8_t *ram) { return ram[S2_GAMEMODE] == 0x0CU || ram[S2_GAMEMODE] == 0x08U; }

/* Whether the game builds its one-player HUD this frame: a running level or demo (game mode 0x0C or 0x08; 0x8C is the level-restart fade after a death, during which the HUD is still built) after the title card, not split-screen. */
static int hud_state(const uint8_t *ram) { return (level_mode(ram) || ram[S2_GAMEMODE] == 0x8CU) && ram[S2_LEVEL_STARTED] != 0U && u16(ram, S2_TWO_PLAYER) == 0U; }

/* ---------------------------------------------------------------------------------------------------------------- cross-frame state (ADR 0320 decision 3)
 * The ABI 1 provider kept two values across frames, both written at presentation time: `g_prev_level` (the HUD is accepted only when the previous produced frame was also a level frame: the work-RAM snapshot is
 * one frame AHEAD of the sprite table on the first level frame) and `g_hud_frame` (the label-frame selection of the last frame the game really built, shown unchanged during the level-restart fade after a death).
 * Classification, with the test of the decision: clearing either before every presented frame would decline the HUD on every frame (`g_prev_level`) or lose the held label frame (`g_hud_frame`), so BOTH are ESSENTIAL
 * state, not caches. They are therefore maintained in the `frame-end` phase, which runs for every guest frame whether or not it is presented, and serialized through `state.mod`: after save/load, rewind and any
 * skipped presentation the provider accepts exactly the frames an uninterrupted run accepts. `frame-end(K)` sees the live RAM of the end of frame K, which is the work-RAM copy the exact-frame `render` of the frame
 * produced one guest frame later receives, so the record of guest frame K describes that copy exactly and the one before it (K - 1) is the "previous produced frame" of the ABI 1 rule. */
#define RING 4U
typedef struct Rec { uint32_t frame; uint32_t valid, hud, label; } Rec;   /* hud: the game builds its HUD in this frame; label: g_hud_frame as of this frame */
static Rec g_ring[RING];

static int rd8(const SegaModHost *h, unsigned off, unsigned *v) { uint32_t x = 0U; if (h->read == NULL || h->read(SEGA_GEN_SPACE_M68K_WORK_RAM, off, 1U, &x) != 0) return 0; *v = x; return 1; }
static int rd16(const SegaModHost *h, unsigned off, unsigned *v) { uint32_t x = 0U; if (h->read == NULL || h->read(SEGA_GEN_SPACE_M68K_WORK_RAM, off, 2U, &x) != 0) return 0; *v = x; return 1; }

static const Rec *rec_at(uint64_t frame) {
  const Rec *r = &g_ring[(unsigned)(frame & (RING - 1U))];
  return r->valid != 0U && r->frame == (uint32_t)frame ? r : NULL;
}

static void frame_end(const SegaModHost *h) {
  unsigned mode, started, two, flash, rings, minutes;
  const uint32_t k = (uint32_t)h->frame;
  Rec *r = &g_ring[k & (RING - 1U)];
  const Rec *prev = h->frame > 0U ? rec_at(h->frame - 1U) : NULL;
  int cur, lvl;
  if (!rd8(h, S2_GAMEMODE, &mode) || !rd8(h, S2_LEVEL_STARTED, &started) || !rd16(h, S2_TWO_PLAYER, &two) || !rd8(h, S2_FLASH, &flash) || !rd16(h, S2_RINGS, &rings) || !rd8(h, S2_MINUTES, &minutes)) {
    r->valid = 0U;
    return;
  }
  lvl = mode == 0x0CU || mode == 0x08U;
  cur = (lvl || mode == 0x8CU) && started != 0U && two == 0U;
  r->frame = k;
  r->valid = 1U;
  r->hud = (uint32_t)cur;
  r->label = prev != NULL ? prev->label : 0U;
  if (cur && prev != NULL && prev->hud != 0U && lvl) r->label = ((flash >> 3) & 1U) != 0U ? 0U : ((rings == 0U ? 1U : 0U) | (minutes == 9U ? 2U : 0U));
}

static int provider_save(void *state, uint8_t *out, uint32_t cap, uint32_t *len) {
  uint32_t i;
  (void)state;
  if (cap < RING * 16U) return 1;
  for (i = 0U; i < RING; ++i) {
    const uint32_t v[4] = {g_ring[i].frame, g_ring[i].valid, g_ring[i].hud, g_ring[i].label};
    for (unsigned j = 0U; j < 16U; ++j) out[i * 16U + j] = (uint8_t)(v[j / 4U] >> (24U - 8U * (j % 4U)));
  }
  *len = RING * 16U;
  return 0;
}

static int provider_load(void *state, const uint8_t *in, uint32_t len) {
  Rec tmp[RING];
  (void)state;
  if (len != RING * 16U) return 1;
  for (unsigned i = 0U; i < RING; ++i) {
    uint32_t v[4];
    for (unsigned q = 0U; q < 4U; ++q) v[q] = ((uint32_t)in[i * 16U + 4U * q] << 24U) | ((uint32_t)in[i * 16U + 4U * q + 1U] << 16U) | ((uint32_t)in[i * 16U + 4U * q + 2U] << 8U) | (uint32_t)in[i * 16U + 4U * q + 3U];
    if (v[1] > 1U || v[2] > 1U || v[3] > 3U) return 1;
    tmp[i].frame = v[0]; tmp[i].valid = v[1]; tmp[i].hud = v[2]; tmp[i].label = v[3];
  }
  for (unsigned i = 0U; i < RING; ++i) g_ring[i] = tmp[i];
  return 0;
}

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
  Sonic2Frame *f = &g_frame;
  unsigned reason = REASON_UNSUPPORTED_SCENE, accepted = 0U, margin_px, left_px;
  uint32_t requested;
  const Rec *cur_rec, *prev_rec;
  int prev_level = 0, hud_now;
  if (feat == NULL || feat->render == NULL || feat->frame == NULL || feat->vdp == NULL || feat->size < sizeof(SegaGenesisFeatures)) return;
  r = feat->render;
  v = feat->frame;
  vdp = feat->vdp;
  ram = v->work_ram;
  requested = v->requested;
  for (unsigned i = 0U; i < (unsigned)sizeof(*f); ++i) ((uint8_t *)f)[i] = 0U;
  if (ram == NULL || v->lines == NULL || v->vram == NULL || v->height == 0U || v->height > 448U || v->line_count < v->height) { refuse(r, requested, REASON_BAD_STATE); return; }
  hud_now = hud_state(ram);
  cur_rec = host->frame >= RENDER_LAG ? rec_at(host->frame - RENDER_LAG) : NULL;       /* the record of the guest frame whose end-of-frame RAM is this view's copy */
  prev_rec = host->frame >= RENDER_LAG + 1U ? rec_at(host->frame - RENDER_LAG - 1U) : NULL;
  prev_level = prev_rec != NULL && prev_rec->hud != 0U;
  /* verified scope: a running level or attract-mode demo. The title card/start sequence, menus, bonus and special stages, split-screen play and every other screen are declined (the HUD alone may still be served). */
  if (!hud_state(ram) && !level_mode(ram)) { refuse(r, requested, REASON_UNSUPPORTED_SCENE); return; }
  margin_px = v->side != 0U ? v->side : 64U;   /* the baseline keeps the picture centred (left_px == margin_px) and declares no placement */
  left_px = margin_px;
  if ((requested & SEGA_GEN_COMPONENT_HUD) != 0U && prev_level && hud_now && v->height == 224U) {
    const unsigned flash = (ram[S2_FLASH] >> 3) & 1U;
    f->hud_frame = cur_rec != NULL ? cur_rec->label : (level_mode(ram) ? (flash ? 0U : ((u16(ram, S2_RINGS) == 0U ? 1U : 0U) | (ram[S2_MINUTES] == 9U ? 2U : 0U))) : 0U);
    accepted |= SEGA_GEN_COMPONENT_HUD;
  }
  if ((requested & SEGA_GEN_COMPONENT_SCENERY) != 0U && level_mode(ram) && u16(ram, S2_TWO_PLAYER) == 0U) {
    reason = scenery_check(f, v, vdp, ram);
    if (reason == REASON_OK) accepted |= SEGA_GEN_COMPONENT_SCENERY;
  }
  if (accepted == 0U) { refuse(r, requested, reason); return; }
  (void)r->scene("level", 5U);
  if ((accepted & SEGA_GEN_COMPONENT_SCENERY) != 0U) {
    uint8_t mask[2][28];
    unsigned any[2] = {0U, 0U};
    int e0 = build_plane_windows(r, f, ram, 0U, left_px, margin_px, mask[0], &any[0]), e1 = build_plane_windows(r, f, ram, 1U, left_px, margin_px, mask[1], &any[1]);
    if (e0 != 0 || e1 != 0) {
      (void)r->decline(SEGA_GEN_COMPONENT_SCENERY, REASON_BAD_STATE);   /* the windows cannot express this frame's answers: never served half-way */
    } else {
      for (unsigned p = 0U; p < 2U; ++p) if (any[p] != 0U) (void)r->scenery_generic_rows(p, mask[p], 224U, 28U);
    }
  }
  if ((accepted & SEGA_GEN_COMPONENT_HUD) != 0U) {
    draw_hud(f, v, vdp);
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
  else if (host->phase == SEGA_MOD_PHASE_FRAME_END) frame_end(host);
}

static const SegaModProvider provider = {sizeof(SegaModProvider), SEGA_MOD_ABI_MAJOR, 2U, SEGA_MOD_PLATFORM, "sonic2.native-widescreen", 3U, provider_init, provider_phase, NULL, provider_save, provider_load,
                                         {NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL}};

const SegaModProvider *segarecomp_mod_provider(void **state_out) {
  if (state_out != NULL) *state_out = NULL;
  return &provider;
}
