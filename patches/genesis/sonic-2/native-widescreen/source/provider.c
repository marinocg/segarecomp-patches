/*
 * Sonic the Hedgehog 2 (Genesis) native widescreen provider: a PACKAGE-OWNED implementation for segarecomp's public native patch SDK (ADR 0267, ABI 1).
 * Written against segarecomp_genesis_patch.h only. The same source ships in the package of each exact image it was verified for (World REV00 and JUE REV01; identities are enforced by the package, not here).
 *
 * What it serves: (1) the scenery (both planes) of every running level and one-player attract demo of the single-player campaign inventory (zone ids listed at scenery_scope), reconstructed beyond the
 * 320-pixel picture from the game's own level layout in work RAM by WORLD coordinates (the VDP name table only holds the screen and the 64-cell wrap, so it cannot show it). Every frame is identity-checked against
 * the VDP; lines or frames the layout does not describe are answered from the VDP's own plane (never claimed as reconstruction) or declined. (2) The game's own one-player HUD (SCORE, TIME, RINGS, lives),
 * relocated to the left edge of the widescreen presentation: the package's BPS moves the HUD sprites off screen (one immediate; the HUD builder still runs, so the guest is unchanged) and this file draws the same
 * ten sprite pieces from the frame's VRAM and CRAM. Every other frame is declined. No audio, gameplay, object or other sprite is touched.
 *
 * The state map below was derived independently for this image (it is NOT the Sonic 1 map): see patches/sonic2/README.md.
 */
#include "segarecomp_genesis_patch.h"

#include <string.h>

#define S2_NAME "sonic2.native-widescreen"
#define S2_IMPLEMENTATION 2U

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

static const GenesisCompatHost *g_host;

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

typedef struct Sonic2Frame {
  const uint8_t *ram;
  unsigned accepted;
  int camy;
  int bgy;
  int fg_wrap_y;                  /* 1: the foreground layout wraps vertically (Metropolis) */
  unsigned zone;                  /* the zone id the frame was verified for */
  int off_fg[S2_HSCROLL_LINES];   /* world x of screen column 0 per output line (the game's own unwrapped foreground scroll) */
  int off_bg[S2_HSCROLL_LINES];   /* the same for the background (its own parallax per line) */
  unsigned height;                /* valid output lines */
  uint8_t own_plane[S2_HSCROLL_LINES][2];   /* 1: this line of this plane is answered from the VDP's own plane (identity check, see scenery_check) */
  uint8_t own[S2_HSCROLL_LINES];  /* 1: the game scrolls this line differently from the camera (the last two lines carry scroll 0): answered from the VDP's own plane, not the world */
  const uint8_t *vram;
  uint16_t base[S2_HSCROLL_LINES][2];   /* name-table base address >> 1 per line and plane */
  const GenesisCompatLine *lines;       /* HUD: the frame's per-line CRAM */
  unsigned hud_frame;                   /* HUD: the game's label-frame selection (bit 0: RINGS label red, bit 1: TIME label red) */
} Sonic2Frame;

static Sonic2Frame g_frame;

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

static unsigned scenery_check(Sonic2Frame *f, const GenesisCompatFrame *frame, const uint8_t *ram) {
  unsigned fg_total = 0U, fg_bad = 0U, bg_total = 0U, bg_bad = 0U, own_lines[2] = {0U, 0U}, edge_total = 0U, edge_bad = 0U;
  if (!scenery_scope(ram[S2_ZONE], ram[S2_ZONE + 1U])) return GENESIS_COMPAT_UNSUPPORTED_SCENE;
  f->camy = (int16_t)u16(ram, S2_VSCROLL_FG);
  if (frame->height > S2_HSCROLL_LINES || u16(ram, S2_CAMX) >= S2_WORLD_W || (f->camy >= (int)S2_WORLD_H && !fg_wraps_vertically(ram[S2_ZONE]))) return GENESIS_COMPAT_BAD_STATE;
  if (frame->width != 320U) return GENESIS_COMPAT_BAD_STATE;
  f->bgy = (int16_t)u16(ram, S2_VSCROLL_BG);
  f->zone = ram[S2_ZONE];
  f->fg_wrap_y = fg_wraps_vertically(ram[S2_ZONE]);
  /* The display must be the verified configuration (64x32 planes, per-line horizontal scroll, full-screen vertical scroll, 320 wide, no interlace) and the scroll the VDP applies (copied from the
   * game's buffer at the previous VBlank) must equal the game's own unwrapped values line by line: then RAM and VDP describe the same frame. */
  for (unsigned l = 0U; l < frame->height; ++l) {
    const GenesisCompatLine *line = &frame->lines[l];
    int32_t ha = 0, hb = 0, va = 0, vb = 0;
    const int ram_a = (int16_t)u16(ram, S2_HSCROLL + l * 4U), ram_b = (int16_t)u16(ram, S2_HSCROLL + l * 4U + 2U);
    if ((line->registers[16] & 0x33U) != 0x01U || (line->registers[11] & 7U) != 3U || (line->registers[12] & 0x87U) != 0x81U || line->registers[17] != 0U || line->registers[18] != 0U ||
        g_host->vscroll_is_per_column(line->registers))
      return GENESIS_COMPAT_BAD_SCROLL;
    if (g_host->read_hscroll(frame->vram, line->registers, GENESIS_COMPAT_PLANE_A, l, &ha) != 0 || g_host->read_hscroll(frame->vram, line->registers, GENESIS_COMPAT_PLANE_B, l, &hb) != 0 ||
        g_host->read_vscroll(line->vsram, line->registers, GENESIS_COMPAT_PLANE_A, 0U, &va) != 0 || g_host->read_vscroll(line->vsram, line->registers, GENESIS_COMPAT_PLANE_B, 0U, &vb) != 0)
      return GENESIS_COMPAT_BAD_SCROLL;
    if ((((int)ha - ram_a) & 0x3FF) != 0 || (((int)hb - ram_b) & 0x3FF) != 0 || (((int)va - f->camy) & 0x3FF) != 0 || (((int)vb - f->bgy) & 0x3FF) != 0) return GENESIS_COMPAT_BAD_SCROLL;
    f->off_fg[l] = -ram_a;
    f->off_bg[l] = -ram_b;
    f->base[l][0] = (uint16_t)(((unsigned)(line->registers[2] & 0x38U) << 10) >> 1);
    f->base[l][1] = (uint16_t)(((unsigned)(line->registers[4] & 7U) << 13) >> 1);
  }
  /* The game's buffer holds the camera scroll on every line except the last two, which carry 0 (verified in the live game). Those lines are not world-scrolled: they are answered from the VDP's own
   * plane (never claimed as reconstruction beyond what the VDP shows). Any other disagreement between lines is not the verified configuration. */
  for (unsigned l = 0U; l < frame->height; ++l) {
    if (f->off_fg[l] == f->off_fg[0]) continue;
    if (l + 2U >= frame->height && f->off_fg[l] == 0) { f->own[l] = 1U; continue; }
    return GENESIS_COMPAT_BAD_SCROLL;
  }
  f->height = frame->height;
  f->vram = frame->vram;
  /* Frame identity: the provider's own cells for the part of the world the picture shows must agree with what the VDP name tables hold there. A gross disagreement (a fade, a transition, another
   * level than the state claims) declines the frame; it is never half-served. A single line of one plane that the game itself leaves unlike the world (the VDP shows blanks above a background the layout
   * says is there, for instance) is answered from the VDP's own plane for that line and plane - what the unextended game shows - and never claimed as reconstruction; at most OWN_MAX such lines
   * per plane are tolerated in one frame. */
  for (unsigned l = 0U; l < frame->height; ++l) {
    const GenesisCompatLine *line = &frame->lines[l];
    int32_t hs[2] = {0, 0}, vs[2] = {0, 0};
    (void)g_host->read_hscroll(frame->vram, line->registers, GENESIS_COMPAT_PLANE_A, l, &hs[0]);
    (void)g_host->read_hscroll(frame->vram, line->registers, GENESIS_COMPAT_PLANE_B, l, &hs[1]);
    (void)g_host->read_vscroll(line->vsram, line->registers, GENESIS_COMPAT_PLANE_A, 0U, &vs[0]);
    (void)g_host->read_vscroll(line->vsram, line->registers, GENESIS_COMPAT_PLANE_B, 0U, &vs[1]);
    if (f->own[l] != 0U) continue;
    for (unsigned plane = 0U; plane < 2U; ++plane) {
      const unsigned base = plane == 0U ? (unsigned)(line->registers[2] & 0x38U) << 10 : (unsigned)(line->registers[4] & 7U) << 13;
      unsigned total = 0U, bad = 0U;
      for (int x = 0; x < (int)frame->width; x += 8) {
        const int edge = x < (int)S2_EDGE || x >= (int)frame->width - (int)S2_EDGE;
        int wx = x + (plane == 0U ? f->off_fg[l] : f->off_bg[l]);
        int wy = (int)l + (plane == 0U ? f->camy : f->bgy);
        const unsigned px = (unsigned)(x - (int)hs[plane]) & 511U, py = (unsigned)((int)l + (int)vs[plane]) & 255U;
        const unsigned a = base + ((py >> 3) * 64U + (px >> 3)) * 2U;
        const unsigned vw = ((unsigned)frame->vram[a & 0xFFFFU] << 8) | frame->vram[(a + 1U) & 0xFFFFU];
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
        if (++own_lines[plane] > S2_OWN_MAX) return GENESIS_COMPAT_MISMATCH;
      } else if (plane == 0U) { fg_total += total; fg_bad += bad; }
      else { bg_total += total; bg_bad += bad; }
    }
  }
  if (fg_total == 0U || fg_bad * 50U > fg_total || bg_bad * 50U > bg_total || edge_bad * 2U > edge_total) return GENESIS_COMPAT_MISMATCH;
  return GENESIS_COMPAT_OK;
}

/* Whether the game builds its one-player HUD this frame: a running level or demo (game mode 0x0C or 0x08; 0x8C is the level-restart fade after a death, during which the HUD is still built) after the title card, not split-screen. The work-RAM snapshot is one frame AHEAD of the sprite table on the
 * first level frame (the title card is still displayed while the mode has already changed), so the HUD is accepted only when the previous produced frame was also such a frame (verified frame by frame against
 * the game's own sprite table). */
static int g_prev_level;
static unsigned g_hud_frame;   /* the label-frame selection of the last frame the game really built; the level-restart fade after a death displays that frame unchanged */

/* game modes in which the level engine runs: 0x0C a level, 0x08 an attract-mode demo (the same engine, replaying recorded input) */
static int level_mode(const uint8_t *ram) { return ram[S2_GAMEMODE] == 0x0CU || ram[S2_GAMEMODE] == 0x08U; }

static int hud_state(const uint8_t *ram) { return (level_mode(ram) || ram[S2_GAMEMODE] == 0x8CU) && ram[S2_LEVEL_STARTED] != 0U && u16(ram, S2_TWO_PLAYER) == 0U; }

static void sonic2_prepare(void *state, const GenesisCompatFrame *frame, GenesisCompatDecision *out) {
  Sonic2Frame *f = (Sonic2Frame *)state;
  const uint8_t *ram = frame->work_ram;
  unsigned reason = GENESIS_COMPAT_UNSUPPORTED_SCENE, accepted = 0U;
  const int prev_level = g_prev_level;
  memset(f, 0, sizeof(*f));
  g_host = frame->host;
  out->accepted = 0U;
  out->reason = GENESIS_COMPAT_BAD_STATE;
  g_prev_level = 0;
  if (g_host == NULL || g_host->size < sizeof(GenesisCompatHost) || ram == NULL || frame->lines == NULL || frame->vram == NULL || frame->height == 0U || frame->height > 448U || frame->line_count < frame->height) return;
  g_prev_level = hud_state(ram);
  /* verified scope: a running level or attract-mode demo. The title card/start sequence, menus, bonus and special stages, split-screen play and every other screen are declined (the HUD alone may still be served). */
  if (!hud_state(ram) && !level_mode(ram)) { out->reason = GENESIS_COMPAT_UNSUPPORTED_SCENE; return; }
  if ((frame->requested & GENESIS_COMPAT_HUD) != 0U && prev_level && g_prev_level && frame->height == 224U) {
    const unsigned flash = (ram[S2_FLASH] >> 3) & 1U;
    f->lines = frame->lines;
    f->vram = frame->vram;
    if (level_mode(ram)) g_hud_frame = flash ? 0U : ((u16(ram, S2_RINGS) == 0U ? 1U : 0U) | (ram[S2_MINUTES] == 9U ? 2U : 0U));
    f->hud_frame = g_hud_frame;
    accepted |= GENESIS_COMPAT_HUD;
  }
  if ((frame->requested & GENESIS_COMPAT_SCENERY) != 0U && level_mode(ram) && u16(ram, S2_TWO_PLAYER) == 0U) {
    reason = scenery_check(f, frame, ram);
    if (reason == GENESIS_COMPAT_OK) { f->ram = ram; accepted |= GENESIS_COMPAT_SCENERY; }
  }
  if (accepted == 0U) { out->reason = (uint8_t)reason; return; }
  f->accepted = accepted;
  out->accepted = accepted;
  out->reason = (accepted & GENESIS_COMPAT_SCENERY) != 0U ? (uint8_t)GENESIS_COMPAT_OK : (uint8_t)reason;   /* a HUD-only frame still reports why the scenery was declined (diagnostic) */
}

static int sonic2_scenery_word(void *state, unsigned plane, unsigned row, int x, int hscroll, int vscroll, uint16_t *word) {
  const Sonic2Frame *f = (const Sonic2Frame *)state;
  int wx, wy;
  if (f->ram == NULL || (f->accepted & GENESIS_COMPAT_SCENERY) == 0U || plane > 1U || word == NULL || row >= f->height) return 0;
  /* the host passes small values (the VDP scroll is 10 bits, columns are within a few hundred pixels); anything wider is refused before any arithmetic can overflow */
  if (x < -65536 || x > 65536 || hscroll < -65536 || hscroll > 65536 || vscroll < -65536 || vscroll > 65536) return 0;
  if (f->own[row] != 0U || (plane < 2U && f->own_plane[row][plane] != 0U)) {   /* the VDP's own wrapped plane: the two lines the game does not world-scroll, and lines the identity check found unlike the layout */
    const unsigned px = (unsigned)(x - hscroll) & 511U, py = (unsigned)((int)row + vscroll) & 255U, a = ((unsigned)f->base[row][plane] << 1) + ((py >> 3) * 64U + (px >> 3)) * 2U;
    *word = (uint16_t)(((unsigned)f->vram[a & 0xFFFFU] << 8) | f->vram[(a + 1U) & 0xFFFFU]);
    return 1;
  }
  if (plane == 0U) {
    /* foreground: world position from the game's own unwrapped scroll; the scroll the VDP applied to this line must be the one prepare verified */
    if ((int)(((unsigned)0 - (unsigned)hscroll) - (unsigned)f->off_fg[row]) & 511) return 0;
    wx = x + f->off_fg[row];
    wy = (int)row + f->camy;
    if (f->fg_wrap_y) wy = wrap_to(wy, (int)S2_WORLD_H);
    if (((vscroll - f->camy) & 0x3FF) != 0) return 0;
  } else {
    /* background: its own unwrapped per-line scroll and camera y, exactly as the foreground (verified per line and per frame in prepare) */
    if ((int)(((unsigned)0 - (unsigned)hscroll) - (unsigned)f->off_bg[row]) & 511) return 0;
    wx = x + f->off_bg[row];
    wy = (int)row + f->bgy;
    if (((vscroll - f->bgy) & 0x3FF) != 0) return 0;
  }
  if (plane == 1U) { wy = wrap_to(wy, (int)S2_WORLD_H); wx = wrap_to(wx, bg_period_at(f->zone, wy)); }
  if (wx < 0 || wy < 0 || wx >= (int)S2_WORLD_W || wy >= (int)S2_WORLD_H) { *word = 0U; return 1; }   /* outside the level: no world, a blank cell */
  *word = (uint16_t)world_cell(f->ram, plane, (unsigned)wx, (unsigned)wy);
  return 1;
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

static int sonic2_hud(void *state, GenesisCompatOverlay *o) {
  const Sonic2Frame *f = (const Sonic2Frame *)state;
  if ((f->accepted & GENESIS_COMPAT_HUD) == 0U || o->rgba == NULL || f->vram == NULL || f->lines == NULL || o->capacity < (size_t)HUD_OW * HUD_H * 4U) return 0;
  o->width = (uint16_t)HUD_OW;
  o->height = (uint16_t)HUD_H;
  o->fallback_x = (uint16_t)(HUD_X0 - HUD_PAD);
  o->fallback_y = 0U;
  memset(o->rgba, 0, (size_t)HUD_OW * HUD_H * 4U);   /* fully transparent: no background */
  for (unsigned n = 0U; n < sizeof(k_hud_pieces) / sizeof(k_hud_pieces[0]); ++n) {
    const HudPiece *pc = &k_hud_pieces[n];
    const unsigned pal = (pc->group == 1U && (f->hud_frame & 2U) != 0U) || (pc->group == 2U && (f->hud_frame & 1U) != 0U) ? 0U : pc->line;
    for (unsigned cx = 0U; cx < pc->cells_w; ++cx)
      for (unsigned cy = 0U; cy < pc->cells_h; ++cy) {
        const unsigned tile = pc->tile + cx * pc->cells_h + cy;   /* a sprite's cells are numbered down each column */
        for (unsigned row = 0U; row < 8U; ++row) {
          const unsigned py = pc->y + cy * 8U + row;
          const GenesisCompatLine *line;
          if (py >= HUD_H) continue;
          line = &f->lines[py];
          for (unsigned col = 0U; col < 8U; ++col) {
            const unsigned px_ = pc->x + cx * 8U + col;
            const uint8_t byte = f->vram[(tile * 32U + row * 4U + col / 2U) & 0xFFFFU];
            const unsigned index = (col & 1U) == 0U ? (unsigned)(byte >> 4) : (unsigned)(byte & 0x0FU);
            uint8_t c[3];
            uint8_t *d;
            if (index == 0U || px_ < HUD_X0 || px_ - HUD_X0 >= HUD_W) continue;
            if (g_host->cram_rgb(line->cram, pal * 16U + index, c) != 0) continue;
            d = o->rgba + ((size_t)py * HUD_OW + (px_ - HUD_X0 + HUD_PAD)) * 4U;
            d[0] = c[0]; d[1] = c[1]; d[2] = c[2]; d[3] = 255U;
          }
        }
      }
  }
  return 1;
}

static const GenesisNativeCompat k_sonic2 = {GENESIS_NATIVE_COMPAT_ABI, S2_NAME, S2_IMPLEMENTATION, GENESIS_COMPAT_HUD | GENESIS_COMPAT_SCENERY, sonic2_prepare, sonic2_scenery_word, sonic2_hud};

const GenesisNativeCompat *segarecomp_patch_provider(void **state_out) {
  if (state_out != NULL) *state_out = &g_frame;
  return &k_sonic2;
}
