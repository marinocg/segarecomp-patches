/*
 * Sonic 3 & Knuckles (Genesis, lock-on composite) native widescreen provider: a PACKAGE-OWNED implementation for segarecomp's public native patch SDK (ADR 0267, ABI 1).
 * Written against segarecomp_genesis_patch.h only. Bound by its package to ONE exact image (the 4 MiB S&K + Sonic 3 composite); identities are enforced by the package, not here.
 *
 * What it serves (this version): the scenery of running levels (the foreground always; background lines where the layout explains them, the rest from the VDP's own plane), reconstructed beyond the 320-pixel picture from the game's own level model in work RAM by WORLD
 * coordinates. Every frame is identity-checked against the VDP: the display configuration must be the verified one, the scroll the VDP applies must equal the game's own per-line
 * scroll buffer, and the provider's cells for the visible picture must agree with the VDP name tables. A line of one plane that the level model does not describe (a background band
 * the game draws from another source) is answered from the VDP's own wrapped plane and never claimed as reconstruction; any gross disagreement of the foreground
 * declines the frame. No HUD, audio, gameplay, object or sprite is touched.
 *
 * The state map below was derived independently for this image (it is NOT the Sonic 1 or Sonic 2 map): see patches/sonic3k/README.md and the T005 evidence.
 */
#include "segarecomp_genesis_patch.h"

#include <string.h>

#define S3K_NAME "sonic3k.native-widescreen"
#define S3K_IMPLEMENTATION 8U

/* Work-RAM map (offsets into the 64 KiB work RAM), each verified against the VDP on the composite image */
#define K_CHUNKS 0x0000U      /* 128x128 px chunks: 0x80 bytes each = 8x8 block words (16x16 px blocks) */
#define K_CHUNK_BYTES 0x80U
#define K_LAYOUT 0x8000U      /* layout header: words fg width, bg width (chunks), fg height, bg height (rows) */
#define K_ROWPTR 0x8008U      /* then per row r: word fg row pointer, word bg row pointer (work-RAM offsets of one byte per chunk) */
#define K_MAX_ROWS 32U        /* the row-pointer table's bound (the layout data begins after it) */
#define K_BLOCKS 0x9000U      /* 16x16 blocks: 8 bytes (4 name-table words TL TR BL BR) indexed by the low 10 bits of a chunk word */
#define K_BLOCK_MASK 0x3FFU
#define K_GAMEMODE 0xF600U    /* byte: 0x0C = running level */
#define K_ZONE 0xFE10U        /* bytes: zone, act */
#define K_HSCROLL 0xE000U     /* per-line scroll buffer copied to the VDP at VBlank: 224 x (fg word, bg word), signed */
#define K_HSCROLL_LINES 224U
#define K_VSCROLL 0xF616U     /* words: foreground and background vertical scroll the VBlank handler writes to VSRAM */
#define K_HUD_X 0xF711U    /* signed byte: the HUD's horizontal slide offset (the HUD is built only while it is non-zero); the builder moves it towards 0 by 8 per frame */
#define K_COMPETITION 0xFFE8U /* word: non-zero in competition mode (its own sprite builder, no one-player HUD) */
#define K_FLASH 0xFE05U    /* byte: bit 3 is the HUD blink phase */
#define K_RINGS 0xFE20U    /* word: ring count */
#define K_MINUTES 0xFE23U  /* byte: timer minutes */
#define K_EDGE 48U            /* picture edge bands judged apart from the centre (the game streams them) */

static const GenesisCompatHost *g_host;

static unsigned u16(const uint8_t *r, unsigned a) { return ((unsigned)r[a & 0xFFFFU] << 8) | r[(a + 1U) & 0xFFFFU]; }
static int wrap_to(int v, int size) { const int m = v % size; return m < 0 ? m + size : m; }

typedef struct Sonic3kFrame {
  const uint8_t *ram;
  unsigned accepted;
  unsigned wide[2], high[2];          /* layout size per plane in chunks (verified in prepare) */
  int vs[2];                          /* the game's vertical scroll per plane */
  int off[K_HSCROLL_LINES][2];        /* world x of screen column 0 per output line and plane (the game's own per-line scroll; for the background plus the registered plane multiple) */
  int bgy[K_HSCROLL_LINES];           /* background world y of each output line (the vertical scroll plus the registered plane multiple) */
  uint8_t own_plane[K_HSCROLL_LINES][2];
  uint16_t base[K_HSCROLL_LINES][2];  /* name-table base address per line and plane */
  const uint8_t *vram;
  unsigned height;
  unsigned own_lines[2];              /* diagnostic: lines answered from the VDP's own plane */
  const GenesisCompatLine *lines;     /* HUD: the frame's per-line CRAM */
  unsigned hud_frame;                 /* HUD: the game's mapping frame (0 all, 1 no RINGS label, 2 no TIME label, 3 neither) */
  int hud_x;                          /* HUD: the slide offset applied to every piece */
  unsigned diag_total[2], diag_bad[2], diag_edge_total, diag_edge_bad;   /* diagnostic: the identity check's own counts (validation logs) */
} Sonic3kFrame;

static Sonic3kFrame g_frame;

/* Name-table word of the cell containing world pixel (wx, wy) of `plane` (0 fg, 1 bg); 0 outside the foreground. The background repeats vertically over its own layout and
 * horizontally continues by plane widths beyond its layout's ends. */
static unsigned world_cell(const Sonic3kFrame *f, unsigned plane, int wx, int wy) {
  const uint8_t *ram = f->ram;
  const int w = (int)f->wide[plane] * 128, h = (int)f->high[plane] * 128;
  unsigned chunk, bw, fx, fy, col, row, word;
  if (plane == 1U) {
    /* beyond either end of its layout row the background continues the plane's own 512-px repetition from the nearest layout edge: the game never draws background
     * columns past the layout, so the VDP keeps showing the last drawn plane-width window (verified against the VDP); a layout narrower than the plane wraps */
    if (w >= 512 && wx >= w) wx -= ((wx - w) / 512 + 1) * 512;
    else if (w >= 512 && wx < 0) wx += ((-wx - 1) / 512 + 1) * 512;
    wx = wrap_to(wx, w);
    wy = wrap_to(wy, h);
  }
  else if (wx < 0 || wy < 0 || wx >= w || wy >= h) return 0U;
  chunk = ram[(u16(ram, K_ROWPTR + ((unsigned)wy >> 7) * 4U + plane * 2U) + ((unsigned)wx >> 7)) & 0xFFFFU];
  bw = u16(ram, K_CHUNKS + chunk * K_CHUNK_BYTES + ((((unsigned)wy & 127U) >> 4) * 8U + (((unsigned)wx & 127U) >> 4)) * 2U);
  fx = (bw >> 10) & 1U;
  fy = (bw >> 11) & 1U;
  col = (((unsigned)wx & 15U) >> 3) ^ fx;
  row = (((unsigned)wy & 15U) >> 3) ^ fy;
  word = u16(ram, K_BLOCKS + (bw & K_BLOCK_MASK) * 8U + (row * 2U + col) * 2U);
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

/* Background registration. Many zones draw the background plane around their own background camera and then scroll it per line (parallax bands), so the layout column a
 * plane column shows is the scroll-implied position plus an unknown multiple of the plane's width (512 px), and likewise vertically (256 px). For each line the multiple that makes
 * the provider's cells equal the VDP's own cells across the visible line is searched (previous line's and previous frame's multiples first); the line is then reconstructed
 * continuously from that origin, so its extension continues the same layout row. A line no multiple explains is answered from the VDP's own plane (see scenery_check). */
static int g_prev_kx[K_HSCROLL_LINES], g_prev_ky[K_HSCROLL_LINES];

static unsigned bg_line_bad(const Sonic3kFrame *f, const GenesisCompatFrame *frame, unsigned l, int wx0, int wy, unsigned limit) {
  unsigned bad = 0U;
  for (int x = (int)K_EDGE; x < (int)frame->width - (int)K_EDGE; x += 8) {
    if (!same_cell(world_cell(f, 1U, wx0 + x, wy), vdp_cell(frame->vram, f->base[l][1], x, -f->off[l][1], l, f->vs[1]))) {
      if (++bad > limit) return bad;
    }
  }
  return bad;
}

/* Extension agreement of a candidate origin: the cells of the widened margins that equal the VDP's own plane there (the game draws whole 64-cell background rows, wider than
 * the margins, so where it has drawn them they are evidence; where it has not, every candidate disagrees alike). */
static unsigned bg_ext_agree(const Sonic3kFrame *f, const GenesisCompatFrame *frame, unsigned l, int wx0, int wy) {
  const int side = frame->side > 0U && frame->side < 128U ? (int)frame->side : 64;
  unsigned agree = 0U;
  for (int x = -side; x < (int)frame->width + side; x += 8) {
    if (x >= 0 && x < (int)frame->width) continue;
    agree += same_cell(world_cell(f, 1U, wx0 + x, wy), vdp_cell(frame->vram, f->base[l][1], x, -f->off[l][1], l, f->vs[1]));
  }
  return agree;
}

/* Returns 1 with the registered multiple, or 0 when no multiple explains the line (the line is then answered from the VDP's own plane). off[l - 1] already carries that line's registered multiple. */
static int bg_register(Sonic3kFrame *f, const GenesisCompatFrame *frame, unsigned l, int *kx_out, int *ky_out) {
  const int nx = ((int)f->wide[1] * 128 + 511) / 512, ny = ((int)f->high[1] * 128 + 255) / 256;
  const unsigned allowed = 1U;   /* a plane multiple is registered only when the central cells agree exactly (one cell of slack for a streaming boundary) */
  int best_kx = 0, best_ky = 0;
  long best = -1;
  /* within a band (the same scroll as the previous line) the band's multiple is kept while it still explains the line */
  if (l > 0U && f->off[l][1] == f->off[l - 1U][1] - g_prev_kx[l - 1U] * 512 && f->own_plane[l - 1U][1] == 0U &&
      bg_line_bad(f, frame, l, f->off[l][1] + g_prev_kx[l - 1U] * 512, (int)l + f->vs[1] + g_prev_ky[l - 1U] * 256, allowed) <= allowed) {
    *kx_out = g_prev_kx[l - 1U]; *ky_out = g_prev_ky[l - 1U];
    return 1;
  }
  /* a band start (or a multiple that no longer explains the line): every multiple that explains the visible cells exactly is a candidate (a repeating background can
   * admit several); the one agreeing best with the VDP's own plane in the margins wins, ties going to the previous line's, then the previous frame's multiple */
  for (int ky = 0; ky < ny; ++ky)
    for (int kx = 0; kx < nx; ++kx) {
      const int wx0 = f->off[l][1] + kx * 512, wy = (int)l + f->vs[1] + ky * 256;
      long score;
      if (bg_line_bad(f, frame, l, wx0, wy, allowed) > allowed) continue;
      score = (long)bg_ext_agree(f, frame, l, wx0, wy) * 4L + ((l > 0U && kx == g_prev_kx[l - 1U] && ky == g_prev_ky[l - 1U]) ? 2L : 0L) +
              ((kx == g_prev_kx[l] && ky == g_prev_ky[l]) ? 1L : 0L);
      if (score > best) { best = score; best_kx = kx; best_ky = ky; }
    }
  *kx_out = best_kx; *ky_out = best_ky;
  return best >= 0;
}

static unsigned scenery_check(Sonic3kFrame *f, const GenesisCompatFrame *frame, const uint8_t *ram) {
  unsigned total[2] = {0U, 0U}, bad[2] = {0U, 0U}, edge_total = 0U, edge_bad = 0U;
  if (ram[K_GAMEMODE] != 0x0CU) return GENESIS_COMPAT_UNSUPPORTED_SCENE;   /* scenery only in a running level (0x8C is the title card / restart sequence) */
  if (frame->width != 320U || frame->height > K_HSCROLL_LINES) return GENESIS_COMPAT_BAD_STATE;
  for (unsigned p = 0U; p < 2U; ++p) {
    f->wide[p] = u16(ram, K_LAYOUT + p * 2U);
    f->high[p] = u16(ram, K_LAYOUT + 4U + p * 2U);
    if (f->wide[p] == 0U || f->high[p] == 0U || f->high[p] > K_MAX_ROWS || f->wide[p] > 0x100U) return GENESIS_COMPAT_BAD_STATE;
    f->vs[p] = (int16_t)u16(ram, K_VSCROLL + p * 2U);
  }
  /* The display must be the verified configuration (64x32 planes, per-line horizontal scroll, full-screen vertical scroll, 320 wide, no interlace, no window) and the scroll the VDP
   * applies must equal the game's own buffer line by line: then work RAM and VDP describe the same frame. */
  for (unsigned l = 0U; l < frame->height; ++l) {
    const GenesisCompatLine *line = &frame->lines[l];
    for (unsigned p = 0U; p < 2U; ++p) {
      int32_t hs = 0, vs = 0;
      const int ram_hs = (int16_t)u16(ram, K_HSCROLL + l * 4U + p * 2U);
      if ((line->registers[16] & 0x33U) != 0x01U || (line->registers[11] & 7U) != 3U || (line->registers[12] & 0x87U) != 0x81U || line->registers[17] != 0U ||
          line->registers[18] != 0U || g_host->vscroll_is_per_column(line->registers))
        return GENESIS_COMPAT_BAD_SCROLL;
      if (g_host->read_hscroll(frame->vram, line->registers, p, l, &hs) != 0 || g_host->read_vscroll(line->vsram, line->registers, p, 0U, &vs) != 0)
        return GENESIS_COMPAT_BAD_SCROLL;
      if ((((int)hs - ram_hs) & 0x3FF) != 0 || (((int)vs - f->vs[p]) & 0x3FF) != 0) return GENESIS_COMPAT_BAD_SCROLL;
      f->off[l][p] = -ram_hs;
      f->base[l][p] = (uint16_t)(p == 0U ? ((unsigned)(line->registers[2] & 0x38U) << 10) : ((unsigned)(line->registers[4] & 7U) << 13));
    }
  }
  f->ram = ram;
  f->vram = frame->vram;
  f->height = frame->height;
  /* Frame identity: the provider's cells for the visible picture must agree with the VDP name tables. */
  for (unsigned l = 0U; l < frame->height; ++l) {
    int kx, ky;
    if (!bg_register(f, frame, l, &kx, &ky)) f->own_plane[l][1] = 1U;
    g_prev_kx[l] = kx; g_prev_ky[l] = ky;
    f->off[l][1] += kx * 512;
    f->bgy[l] = (int)l + f->vs[1] + ky * 256;
  }
  for (unsigned l = 0U; l < frame->height; ++l)
    for (unsigned p = 0U; p < 2U; ++p) {
      unsigned t = 0U, b = 0U, et = 0U, eb = 0U;
      if (p == 1U && f->own_plane[l][1] != 0U) { ++f->own_lines[1]; continue; }   /* no multiple explains it: the VDP's own plane, never reconstruction */
      for (int x = 0; x < (int)frame->width; x += 8) {
        const unsigned w = world_cell(f, p, x + f->off[l][p], p == 0U ? (int)l + f->vs[0] : f->bgy[l]);
        const unsigned v = vdp_cell(frame->vram, f->base[l][p], x, -f->off[l][p], l, f->vs[p]);
        if (x < (int)K_EDGE || x >= (int)frame->width - (int)K_EDGE) { ++et; eb += !same_cell(w, v); continue; }
        ++t;
        b += !same_cell(w, v);
      }
      if (b * 10U <= t) { edge_total += et; edge_bad += eb; }   /* edge cells count only for lines that are reconstructed (an own-plane line is the VDP's own) */
      if (b * 10U > t) {   /* this line of this plane is not the world the layout describes: the VDP's own plane answers it */
        f->own_plane[l][p] = 1U;
        if (p == 0U) { f->diag_bad[p] = 0xFFFFU; return GENESIS_COMPAT_MISMATCH; }   /* the foreground must be the layout everywhere */
        ++f->own_lines[p];
      } else {
        total[p] += t;
        bad[p] += b;
      }
    }
  f->diag_total[0] = total[0]; f->diag_total[1] = total[1]; f->diag_bad[0] = bad[0]; f->diag_bad[1] = bad[1]; f->diag_edge_total = edge_total; f->diag_edge_bad = edge_bad;
  if (total[0] == 0U || bad[0] * 50U > total[0] || bad[1] * 50U > total[1] || edge_bad * 2U > edge_total) return GENESIS_COMPAT_MISMATCH;
  return GENESIS_COMPAT_OK;
}

/* ---------------------------------------------------------------------------------------------------------------- HUD */
/* The game's own one-player HUD, relocated. The package's BPS moves the HUD's Y base off the visible window (one immediate of the HUD routine: the routine still runs, queues the
 * same pieces in the same order with the same work, and keeps updating its slide offset), and this draws the same pieces from the frame's own VRAM and CRAM. The HUD routine is called
 * by the one-player sprite builder while the slide offset is non-zero and competition mode is off; it selects a mapping frame from the blink phase, the ring count and the minutes (the
 * blinking labels are omitted pieces, not a palette change). Layout read from the image's HUD mapping frames; checked frame by frame against the unmodified game's sprite table. */
#define HUD_X0 16U    /* picture column of the HUD's left edge at rest (slide offset 1) */
#define HUD_W 104U    /* picture columns 16..119 */
#define HUD_H 216U    /* picture rows 0..215 (the lives row ends at 215) */
#define HUD_PAD 8U    /* transparent left margin of the overlay: keeps the HUD off the very edge of the screen beside the picture; the in-picture position is unchanged */
#define HUD_OW (HUD_W + HUD_PAD)

typedef struct HudPiece { int8_t x; uint8_t y; uint8_t cells_w, cells_h; uint16_t tile; uint8_t line; uint8_t frames; } HudPiece;
/* frames: bit n set = the piece is in mapping frame n */
static const HudPiece k_hud_pieces[] = {
    {0, 8, 4, 2, 0x6CAU, 1, 0x0F}, {32, 8, 4, 2, 0x6E2U, 1, 0x0F}, {64, 8, 4, 2, 0x6EAU, 1, 0x0F},   /* SCORE and its digits */
    {0, 24, 4, 2, 0x6DAU, 1, 0x03}, {40, 24, 4, 2, 0x6F2U, 1, 0x0F},                                 /* TIME (omitted in frames 2, 3) and its digits */
    {0, 40, 4, 2, 0x6D2U, 1, 0x05}, {32, 40, 1, 2, 0x6CAU, 1, 0x05}, {48, 40, 3, 2, 0x6FAU, 1, 0x0F}, /* RINGS (omitted in frames 1, 3) and its digits */
    {0, 200, 2, 2, 0x7D4U, 0, 0x0F}, {16, 200, 4, 2, 0x7D8U, 1, 0x0F},                              /* the character icon, and the name and lives */
};

static int hud_state(const uint8_t *ram) {
  return (ram[K_GAMEMODE] == 0x0CU || ram[K_GAMEMODE] == 0x8CU) && ram[K_HUD_X] != 0U && u16(ram, K_COMPETITION) == 0U && scenery_scope(ram[K_ZONE], ram[K_ZONE + 1U]);
}

static unsigned hud_frame_of(const uint8_t *ram) {
  unsigned frame = 0U;
  if ((ram[K_FLASH] & 0x08U) != 0U) return 0U;
  if (u16(ram, K_RINGS) == 0U) frame += 1U;
  if (ram[K_MINUTES] == 9U) frame += 2U;
  return frame;
}

static int s3k_hud(void *state, GenesisCompatOverlay *o) {
  const Sonic3kFrame *f = (const Sonic3kFrame *)state;
  if ((f->accepted & GENESIS_COMPAT_HUD) == 0U || o == NULL || o->rgba == NULL || f->vram == NULL || f->lines == NULL || o->capacity < (size_t)HUD_OW * HUD_H * 4U) return 0;
  o->width = (uint16_t)HUD_OW;
  o->height = (uint16_t)HUD_H;
  o->fallback_x = (uint16_t)(HUD_X0 - HUD_PAD);
  o->fallback_y = 0U;
  memset(o->rgba, 0, (size_t)HUD_OW * HUD_H * 4U);   /* fully transparent: no panel */
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
            const uint8_t byte = f->vram[(tile * 32U + row * 4U + col / 2U) & 0xFFFFU];
            const unsigned index = (col & 1U) == 0U ? (unsigned)(byte >> 4) : (unsigned)(byte & 0x0FU);
            uint8_t c[3];
            uint8_t *d;
            if (index == 0U || ox < (int)HUD_PAD || ox >= (int)HUD_OW) continue;
            if (g_host->cram_rgb(f->lines[py].cram, pc->line * 16U + index, c) != 0) continue;
            d = o->rgba + ((size_t)py * HUD_OW + (unsigned)ox) * 4U;
            d[0] = c[0]; d[1] = c[1]; d[2] = c[2]; d[3] = 255U;
          }
        }
      }
  }
  return 1;
}

static void s3k_prepare(void *state, const GenesisCompatFrame *frame, GenesisCompatDecision *out) {
  Sonic3kFrame *f = (Sonic3kFrame *)state;
  const uint8_t *ram = frame->work_ram;
  unsigned reason;
  memset(f, 0, sizeof(*f));
  g_host = frame->host;
  out->accepted = 0U;
  out->reason = GENESIS_COMPAT_BAD_STATE;
  if (g_host == NULL || g_host->size < sizeof(GenesisCompatHost) || ram == NULL || frame->lines == NULL || frame->vram == NULL || frame->height == 0U ||
      frame->line_count < frame->height)
    return;
  /* scope: a running level of the single-player campaign inventory (scenery_scope). Every other screen (title, menus, special and bonus stages, competition) is declined. Membership
   * alone never accepts anything: every frame is identity-checked below. */
  if ((ram[K_GAMEMODE] != 0x0CU && ram[K_GAMEMODE] != 0x8CU) || !scenery_scope(ram[K_ZONE], ram[K_ZONE + 1U])) { out->reason = GENESIS_COMPAT_UNSUPPORTED_SCENE; return; }
  if ((frame->requested & GENESIS_COMPAT_HUD) != 0U && hud_state(ram) && frame->height == 224U) {
    f->lines = frame->lines;
    f->vram = frame->vram;
    f->hud_frame = hud_frame_of(ram);
    f->hud_x = (int8_t)ram[K_HUD_X];
    f->accepted |= GENESIS_COMPAT_HUD;
  }
  reason = GENESIS_COMPAT_UNSUPPORTED_SCENE;
  if ((frame->requested & GENESIS_COMPAT_SCENERY) != 0U) {
    reason = scenery_check(f, frame, ram);
    if (reason == GENESIS_COMPAT_OK) f->accepted |= GENESIS_COMPAT_SCENERY;
    else f->ram = NULL;
  }
  out->accepted = f->accepted;
  out->reason = (f->accepted & GENESIS_COMPAT_SCENERY) != 0U ? (uint8_t)GENESIS_COMPAT_OK : (uint8_t)reason;   /* a HUD-only frame still reports why the scenery was declined */
}

static int s3k_scenery_word(void *state, unsigned plane, unsigned row, int x, int hscroll, int vscroll, uint16_t *word) {
  const Sonic3kFrame *f = (const Sonic3kFrame *)state;
  if (f->ram == NULL || (f->accepted & GENESIS_COMPAT_SCENERY) == 0U || plane > 1U || word == NULL || row >= f->height) return 0;
  if (x < -65536 || x > 65536 || hscroll < -65536 || hscroll > 65536 || vscroll < -65536 || vscroll > 65536) return 0;
  /* the scroll the VDP applies to this line must be the one prepare verified */
  if (((((unsigned)0 - (unsigned)hscroll) - (unsigned)f->off[row][plane]) & (plane == 0U ? 0x3FFU : 0x1FFU)) != 0U || (((unsigned)vscroll - (unsigned)f->vs[plane]) & 0x3FFU) != 0U) return 0;
  if (f->own_plane[row][plane] != 0U) {   /* not the layout's world: the VDP's own wrapped plane (what the unextended game would show), never claimed as reconstruction */
    *word = (uint16_t)vdp_cell(f->vram, f->base[row][plane], x, hscroll, row, vscroll);
    return 1;
  }
  *word = (uint16_t)world_cell(f, plane, x + f->off[row][plane], plane == 0U ? (int)row + f->vs[0] : f->bgy[row]);
  return 1;
}

static const GenesisNativeCompat k_s3k = {GENESIS_NATIVE_COMPAT_ABI, S3K_NAME, S3K_IMPLEMENTATION, GENESIS_COMPAT_SCENERY | GENESIS_COMPAT_HUD, s3k_prepare, s3k_scenery_word, s3k_hud};

const GenesisNativeCompat *segarecomp_patch_provider(void **state_out) {
  if (state_out != NULL) *state_out = &g_frame;
  return &k_s3k;
}
