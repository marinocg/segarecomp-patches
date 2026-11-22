/* Castle of Illusion starring Mickey Mouse (Genesis, USA/Europe): authored widescreen scenery and Practice+, ONE native ABI 2 provider (strict C11).
 *
 * Everything here is a fact about the game's WORK RAM for ONE exact image (see mod.toml / README.md); nothing is read from, or copied out of, the cartridge. The game keeps, for each scrolling plane, a small record
 * (plane A at 0xFA80, plane B at 0xFAC0, big-endian words) and a byte map of 16 x 16 pixel blocks plus a table that expands a block to four VDP name-table words:
 *   +0 vertical scroll   +4 horizontal scroll (the camera x)   +8/+10 map address (long)   +12 map rows   +14 map columns (blocks)   +16/+18 block-table address (long)
 * A block b of the table is four words (top-left, top-right, bottom-left, bottom-right cell) at table + 8 * b. This provider rebuilds the name-table words of the cells BESIDE the picture from those two
 * structures and hands them to the host as an authored scenery window. The scenery path is presentation only: it never writes guest memory.
 *
 * Practice+ (the ONLY guest-affecting code, kept apart below): the game keeps Mickey's power at 0xF322 (0 = dead, 1..5 alive, 5 = full; its own routines cap it at 5). Pressing A+B+C together (an edge, never a held repeat) while a verified level runs and the
 * power is 1..4 restores it to 5 EXACTLY the way the game's own refresh routine leaves its state: the power word, the five HUD slot words (0xF244..0xF24D) and the HUD-upload flag (bit 0 of 0xF409), so the on-screen power row updates too. Lives (tries)
 * and everything else are never touched. The chord is also taken away from the game while a verified level runs (input.intercept, phase `input`): the game never sees A+B+C as a jump or an attack. Buttons that arrive before the chord is
 * complete still reach the game, and a chord outside a verified level is not touched. */
#include <segarecomp_mod_genesis.h>

#define REC_A 0xFA80U
#define REC_B 0xFAC0U
#define MAP_A 0x2000U   /* the lowest address plane A's map can have; its own address is in the record */
#define MAP_B 0x5000U
#define MAP_B_LOW 0x4800U   /* plane B's map is here in the scenes whose plane A map is small */
#define TABLE_A 0x0000U
#define TABLE_B 0x0800U
#define POWER 0xF322U
#define POWER_MAX 5U
#define HUD_SLOTS 0xF244U        /* five name-table words, one per power slot: the game's refresh routine stores a filled or an empty slot word in each */
#define HUD_SLOT_FILLED 0x807CU
#define HUD_SLOT_EMPTY 0x807DU
#define HUD_FLAGS 0xF409U        /* bit 0: the HUD row must be uploaded again */
#define CHORD 0x70U              /* A (0x40) + B (0x10) + C (0x20) of player 1, all together; Start is never used */
#define FLASH_FRAMES 90U
#define B_MAP_END 0x7000U
#define A_BLOCKS 256U
#define B_BLOCKS 256U
#define WCOLS 128U        /* the widest window the host accepts (1024 px): a 32:9 view is 796 px, the rest absorbs the rows scrolled differently and the camera's motion since the frame-end read */
#define WROWS 32U         /* 28 visible rows + 1 partial + one row of slack on each side; 128 x 32 = 4096 words is the host's window bound */
#define BROWS 16U         /* the second window (ADR 0313): the rows from picture row 128 down, where a split-scroll band (the status bar and, in some stages, a strip above it) is scrolled differently from the playfield */
#define BAND_ROW0 128     /* the first picture row the second window covers */
#define LEGACY_LEFT 238   /* the symmetric 32:9 margin the windows assumed before the picture could be placed (used while the host's margin is not known: no extension is planned, nothing is placed) */
#define SLACK_LEFT 6      /* cells of slack left of the view in the main windows (the camera moves a few pixels between the frame-end read and the frame the host produces) */
#define BAND_SLACK 2

typedef struct Plane {
  int32_t cam;            /* the game's horizontal scroll value (camera x, pixels) */
  int32_t vscroll;
  uint32_t rows, cols;    /* map size in blocks (the map record's own fields) */
  uint32_t map;           /* the map's work-RAM address (plane A: the record's own, plane B: fixed) */
  int32_t shift_cells;    /* world cell - window plane cell (x): a multiple of 128 while the VDP's 10-bit scroll has wrapped */
  int32_t shift_rows;     /* the same for y */
  int32_t cell_x0, cell_y0;
  int32_t band_y0;        /* first plane cell row of the second (band) window */
  uint32_t window_rows;
} Plane;

static Plane plane_a, plane_b;
static uint16_t words_a[WCOLS * WROWS], words_b[WCOLS * WROWS], band_a[WCOLS * BROWS], band_b[WCOLS * BROWS];
typedef struct ModState {
  uint32_t chord_held;    /* the chord was down at the latest post-input (an edge needs it up first) */
  uint32_t restores;      /* completed restorations since reset (kept in the save state; nothing is drawn for it: the package shows no indicator) */
  uint32_t flash;         /* frames since the latest restoration, counted down (kept in the save state; no notice is drawn) */
  uint32_t chord_now;     /* the chord is down in this frame's sample (set at `input`, read at `post-input`) */
} ModState;
static ModState st;
static uint32_t scene_id;          /* 0 = nothing verified this frame, else 1 + the index in `scenes` */
static uint32_t ready;             /* a window was built at the latest frame-end for the next render */
static uint32_t plane_b_authored;  /* plane B has a window (its map is a real world map, not a tiling background) */
static uint32_t band_ready;        /* the second (band) windows were built too: without them only the rows the main window covers are served */
static int32_t band_x0;            /* the band windows' first plane cell: the band is not scrolled, so its cells are the screen's own: the view starts `left` pixels left of the picture */
/* The asymmetric view (product ADR 0315). The host plans one total of 2 * margin extra columns and learns it to the provider (`view_margin`, in the render phase); the provider only chooses how many of them lie
 * left of the picture. The view is aligned left at the level's first column, centred in the middle and aligned right at the last one; `placement` ramps between them slowly and as a pure function of the camera (see there). The level's first column is the map's own (the planes hold no world left of block 0). The
 * margin is read in the render phase and used by the next frame-end that builds the windows, so a placement is declared only when the margin it was computed for is still the host's. */
static uint32_t margin_learnt;     /* per-side margin of the host's latest produced frame, 0 = none yet (or no extension): the centred layout is assumed */
static uint32_t margin_used;       /* the margin the windows of this frame were built for */
static int32_t view_left_px;       /* columns of the planned total left of the picture, for the frame the windows were built for */
static uint32_t view_declared;     /* a placement is to be declared at render (a margin is known) */

static int rd(const SegaModHost *h, uint32_t offset, uint32_t width, uint32_t *value) { return h->read(SEGA_GEN_SPACE_M68K_WORK_RAM, offset, width, value); }

static int record(const SegaModHost *h, uint32_t base, uint32_t map, uint32_t table, Plane *p, uint32_t *stored_cols) {
  uint32_t v = 0U, cam = 0U, ptr_hi = 0U, ptr_lo = 0U, rows = 0U, cols = 0U, tbl_hi = 0U, tbl_lo = 0U;
  if (rd(h, base, 2U, &v) || rd(h, base + 4U, 2U, &cam) || rd(h, base + 8U, 2U, &ptr_hi) || rd(h, base + 10U, 2U, &ptr_lo) || rd(h, base + 12U, 2U, &rows) || rd(h, base + 14U, 2U, &cols) ||
      rd(h, base + 16U, 2U, &tbl_hi) || rd(h, base + 18U, 2U, &tbl_lo))
    return 0;
  if (ptr_hi != 0xFFU || tbl_hi != 0xFFU || tbl_lo != table) return 0;   /* the record of a running scrolling level, not a menu, cutscene or transition (those leave it zeroed) */
  if (map != 0U ? (ptr_lo != MAP_B && ptr_lo != MAP_B_LOW) : (ptr_lo < MAP_A || ptr_lo >= MAP_B_LOW)) return 0;   /* plane B's map is at one of two addresses; plane A's own address is read from the record (inside the declared range) */
  p->map = ptr_lo;
  p->vscroll = (int32_t)v;
  p->cam = (int32_t)cam;
  p->rows = rows;
  *stored_cols = cols;
  return 1;
}

/* The VDP applies a 10-bit scroll: -camera wraps into [-512, 511] (and the vertical value into the same range); the host's plane coordinate is screen position minus that value. The window is in plane cells, the maps in world cells. */
static void place(Plane *p, int32_t left) {
  int32_t hs = -p->cam, vs = ((p->vscroll + 512) & 1023) - 512;
  hs = ((hs + 512) & 1023) - 512;
  p->shift_cells = (p->cam + hs) / 8;                    /* exact: cam + hs is a multiple of 1024 */
  p->shift_rows = (p->vscroll - vs) / 8;
  p->cell_x0 = ((p->cam - left) >> 3) - SLACK_LEFT - p->shift_cells;   /* the view starts `left` pixels left of the camera; the measured need of the scrolled rows is up to 18 cells beyond the view's right edge (rows with different parallax scroll included): the 128-cell window leaves 4 */
  p->cell_y0 = (vs >> 3) - 1;                           /* one row of slack above the visible rows (floor division) */
  p->band_y0 = ((BAND_ROW0 + vs) >> 3) - 1;              /* the band shares the playfield's vertical scroll in every measured stage */
  p->window_rows = WROWS;                               /* rows outside the map are the game's own empty block, as the VDP planes hold them */
}

static int build_plane(const SegaModHost *h, const Plane *p, uint32_t map, uint32_t table, uint32_t stride, uint32_t blocks, int wrap, uint16_t *out) {
  uint16_t cache[A_BLOCKS][4];
  uint8_t have[A_BLOCKS];
  uint32_t r, c, i;
  for (i = 0U; i < blocks; ++i) have[i] = 0U;
  for (r = 0U; r < p->window_rows; ++r) {
    const int32_t wy = p->cell_y0 + (int32_t)r + p->shift_rows;
    for (c = 0U; c < WCOLS; ++c) {
      const int32_t wx = p->cell_x0 + (int32_t)c + p->shift_cells;
      uint32_t b = 0U, word = 0U;
      int32_t bx = wx >> 1;
      const int32_t by = wy >> 1;
      /* Beyond a level's first or last column the game has no scenery. A tiling (wrapped) background plane keeps tiling, as the game's own plane does; the level plane repeats its edge column outward, so a floor continues flat and the sides stay coherent instead of showing a void. */
      if (wrap) bx = bx & (int32_t)(stride - 1U);
      else if (bx < 0) bx = 0;
      else if ((uint32_t)bx >= stride) bx = (int32_t)stride - 1;
      if (bx >= 0 && (uint32_t)bx < stride && by >= 0 && (uint32_t)by < p->rows) {
        if (rd(h, map + (uint32_t)by * stride + (uint32_t)bx, 1U, &b) != 0 || b >= blocks) return 0;
      }
      if (!have[b]) {
        for (i = 0U; i < 4U; ++i) {
          if (rd(h, table + 8U * b + 2U * i, 2U, &word) != 0) return 0;
          cache[b][i] = (uint16_t)word;
        }
        have[b] = 1U;
      }
      out[r * WCOLS + c] = cache[b][(uint32_t)(wy & 1) * 2U + (uint32_t)(wx & 1)];
    }
  }
  return 1;
}

/* The verified scenes, by the map sizes (blocks) of the running level: plane A rows x columns and plane B rows. Each was flown through end to end with a private debug build and compared against the VDP (see README). */
typedef struct Scene { uint32_t a_rows, a_cols, b_rows, b_stride; const char *name; uint32_t b_generic; } Scene;   /* b_generic: plane B is left to the VDP-derived extension (product ADR 0314), see below */
static const Scene scenes[] = {
  {16U, 240U, 16U, 32U, "a16x240-b16", 1U}, {48U, 160U, 16U, 32U, "a48x160-b16", 1U}, {48U, 128U, 48U, 32U, "a48x128-b48", 1U}, {16U, 32U, 16U, 32U, "a16x32-b16", 1U},
  {192U, 48U, 192U, 32U, "a192x48-b192", 1U}, {32U, 112U, 32U, 32U, "a32x112-b32", 1U}, {14U, 320U, 14U, 32U, "a14x320-b14", 1U}, {17U, 32U, 17U, 32U, "a17x32-b17", 1U},
  {80U, 80U, 80U, 80U, "a80x80-b80x80", 0U}, {32U, 128U, 32U, 128U, "a32x128-b32x128", 0U}, {96U, 64U, 96U, 32U, "a96x64-b96", 0U},
  {48U, 160U, 48U, 32U, "a48x160-b48", 0U}, {48U, 256U, 48U, 32U, "a48x256-b48", 1U}, {16U, 160U, 16U, 32U, "a16x160-b16", 1U}, {32U, 32U, 32U, 32U, "a32x32-b32", 1U}, {80U, 128U, 80U, 128U, "a80x128-b80x128", 0U}, {16U, 64U, 16U, 32U, "a16x64-b16", 1U},
};
#define SCENE_COUNT (sizeof scenes / sizeof scenes[0])

/* 0 = none (a menu, cutscene, load, transition or an unverified level), else 1 + the index in `scenes`. Fills both planes from the live records. */
static uint32_t classify(const SegaModHost *h, Plane *a, Plane *b) {
  uint32_t cols_a = 0U, cols_b = 0U, id = 0U, i;
  if (!record(h, REC_A, 0U, TABLE_A, a, &cols_a) || !record(h, REC_B, 1U, TABLE_B, b, &cols_b)) return 0U;
  a->cols = cols_a;
  for (i = 0U; i < SCENE_COUNT; ++i)
    if (a->rows == scenes[i].a_rows && a->cols == scenes[i].a_cols && b->rows == scenes[i].b_rows) { id = i + 1U; b->cols = scenes[i].b_stride; }
  if (id == 0U) return 0U;
  if (a->map + a->rows * a->cols > b->map || b->map + b->rows * b->cols > B_MAP_END) return 0U;
  if (a->vscroll >= (int32_t)a->rows * 16 || b->vscroll >= (int32_t)b->rows * 16 + 512 || a->cam < 0 || b->cam < 0 || a->cam >= (int32_t)a->cols * 16 || b->cam >= (int32_t)a->cols * 16) return 0U;
  return id;
}


/* ---- Actors beyond the hardware sprite range (presentation only; no guest write) ----
 * The game's object sprite builder assembles each sprite piece's hardware entry (y, size, link, attribute) in its work-RAM sprite buffer, then asks one routine whether the piece's x is inside the range it keeps
 * (sprite x 0x60 .. 0x1DF, i.e. screen -32 .. 351) and silently drops it otherwise, unless its object is flagged never-clipped. A `before` function hook on that routine observes every piece at that moment (d0 = x, a0 =
 * the object, a2 = the buffer position just after the attribute), BEFORE the decision, so the dropped pieces can be drawn as virtual sprites with the game's own art (tile, palette, flips from the attribute word,
 * read from the frame's own VRAM/CRAM by the host). Nothing is written to the guest, and a piece the game keeps is never drawn twice: only pieces outside the kept range are collected. */
#define COLLECT_MAX 128U         /* scratch for the frame's candidate pieces (in the game's order); the host takes at most GENESIS_VSPRITE_MAX of them, chosen at render when the presented view is known */
#define VIEW_SLACK 8             /* pixels of tolerance around the presented view (the camera moves a little between the frame-end read and the frame the host produces) */
#define PIECE_X_LO 0x60
#define PIECE_X_HI 0x1E0
#define OBJECT_FLAGS 0xEU        /* byte at object + 0xE: bit 5 = never clipped */
#define OBJECT_LO 0xA000U
#define SPRITE_BUFFER_LO 0xF506U /* the buffer position of an x slot (entry base + 6 .. ) inside the buffer at 0xF500 */
#define SPRITE_BUFFER_HI 0xF800U
typedef struct Piece { int16_t x, y; uint16_t attr; uint8_t size; uint8_t edge; uint8_t likely; } Piece;   /* edge: 0 = draw whole (the game dropped it), 1 = only the part right of the raster, 2 = only the part left of it (the game keeps the piece, the hardware cannot show that part) */
#define RASTER_W 320
#define RASTER_H 224
static Piece collected[COLLECT_MAX], served[COLLECT_MAX];
static uint32_t collected_n, served_n;
static GenesisVirtualSpriteSet vset;
/* Diagnostics only (never saved, never read by the guest-affecting code): candidates that no presented view could show, visible commands lost to a full host budget, candidates lost to a full scratch. A loss is never silent: it is logged when it starts. */
static uint32_t stat_lost_visible, stat_lost_scratch, stat_unlikely_dropped, stat_evicted, lost_logged, lost_prev;

/* The part of a collected piece the provider asks the host to draw, as [x0, x1) in screen pixels: a dropped piece whole, a kept edge piece only the part the raster does not show (edge 1: right of it, edge 2: left of it). */
static int piece_region(const Piece *p, int32_t *x0, int32_t *x1) {
  const int32_t w = (int32_t)(((p->size >> 2) & 3U) + 1U) * 8, h = (int32_t)((p->size & 3U) + 1U) * 8;
  *x0 = p->x;
  *x1 = p->x + w;
  if (p->edge == 1U && *x0 < RASTER_W) *x0 = RASTER_W;
  if (p->edge == 2U && *x1 > 0) *x1 = 0;
  return *x0 < *x1 && p->y + h > 0 && p->y < RASTER_H;   /* a piece with no vertical overlap with the raster rows is shown by nobody (the presented view is as tall as the raster) */
}
/* Whether any pixel of the piece's drawn part can lie in the presented view [lo, hi) (screen x, the picture's left edge is 0). */
static int piece_visible(const Piece *p, int32_t lo, int32_t hi) {
  int32_t x0, x1;
  if (!piece_region(p, &x0, &x1)) return 0;
  /* the tolerance does not apply to an edge that is the picture's own (no extension on that side): nothing is presented beyond it, however the camera moves */
  return x1 > (lo == 0 ? 0 : lo - VIEW_SLACK) && x0 < (hi == RASTER_W ? RASTER_W : hi + VIEW_SLACK);
}

static int provider_hook(void *state, const SegaModHost *h, uint32_t hook_id) {
  uint32_t d0 = 0U, a0 = 0U, a2 = 0U, yw = 0U, size = 0U, attr = 0U, flags = 0U, edge = 0U;
  int32_t x;
  (void)state;
  (void)hook_id;
  if (h->read(SEGA_GEN_SPACE_M68K_HOOK_REGS, 0U, 4U, &d0) != 0 || h->read(SEGA_GEN_SPACE_M68K_HOOK_REGS, 8U, 4U, &a0) != 0 || h->read(SEGA_GEN_SPACE_M68K_HOOK_REGS, 10U, 4U, &a2) != 0) return 0;
  x = (int32_t)(int16_t)(uint16_t)(d0 & 0xFFFFU);
  a2 &= 0xFFFFU;
  if (a2 < SPRITE_BUFFER_LO || a2 >= SPRITE_BUFFER_HI) return 0;
  a0 &= 0xFFFFU;
  if (a0 < OBJECT_LO || a0 + OBJECT_FLAGS >= SPRITE_BUFFER_HI) return 0;   /* only objects inside the declared range are read (anything else is not a verified object) */
  if (rd(h, a0 + OBJECT_FLAGS, 1U, &flags) != 0) return 0;
  if ((flags & 0x20U) != 0U && (x < PIECE_X_LO || x >= PIECE_X_HI)) return 0;   /* a never-clipped object is kept by the game at any x: outside the sprite table's range the hardware wraps it, which is not reproduced here */
  if (rd(h, a2 - 6U, 2U, &yw) != 0 || rd(h, a2 - 4U, 1U, &size) != 0 || rd(h, a2 - 2U, 2U, &attr) != 0) return 0;
  if (x >= PIECE_X_LO && x < PIECE_X_HI) {
    /* The game keeps this piece and the hardware sprite layer draws it, but the raster is only 320 wide: the part of a kept piece left of 0 or right of 319 (the 32 columns beside the picture the sprite table can address) is drawn by nobody. Only that part is submitted (clipped), so no native pixel is drawn twice. */
    const int32_t sx = x - 128, w = (int32_t)(((size >> 2) & 3U) + 1U) * 8;
    if (sx >= 0 && sx + w <= RASTER_W) return 0;
    edge = sx < 0 ? 2U : 1U;
  }
  {   /* the coarse filter: a piece no placement of any package could show (beyond the widest planned view, or off the raster rows) never takes a place; the exact choice is made at render, when the host's plan is known */
    Piece c;
    c.x = (int16_t)(x - 128);
    c.y = (int16_t)((int32_t)(int16_t)(uint16_t)yw - 128);
    c.attr = (uint16_t)attr;
    c.size = (uint8_t)size;
    c.edge = (uint8_t)edge;
    if (!piece_visible(&c, -LEGACY_LEFT, RASTER_W + 2 * LEGACY_LEFT)) return 0;
    {   /* "likely": visible under the best plan known now (the host's last margin and this frame's camera). Only a full scratch makes it matter: a likely piece then takes the place of the newest unlikely one (which may still be needed in the frame the plan changes). */
      uint32_t cam = 0U, m = margin_learnt > margin_used ? margin_learnt : margin_used;
      const int32_t left = (rd(h, REC_A + 4U, 2U, &cam) == 0 && (int32_t)cam < (int32_t)m) ? (int32_t)cam : (int32_t)m;
      c.likely = (uint8_t)(piece_visible(&c, -left, RASTER_W + 2 * (int32_t)m - left) ? 1U : 0U);
    }
    if (collected_n >= COLLECT_MAX) {
      uint32_t k = COLLECT_MAX;
      if (c.likely != 0U) while (k != 0U && collected[k - 1U].likely != 0U) --k;
      else k = 0U;
      if (k == 0U) { if (c.likely != 0U) ++stat_lost_scratch; else ++stat_unlikely_dropped; return 0; }
      for (--k; k + 1U < collected_n; ++k) collected[k] = collected[k + 1U];   /* drop the newest unlikely candidate; the order of the others is kept */
      --collected_n;
      ++stat_evicted;
    }
    collected[collected_n++] = c;
  }
  return 0;
}

/* The exact choice (render phase): the pieces whose drawn part intersects the view [lo, hi) the host presents this frame, in the game's order (so the priority bit and the relative order of the pieces are the game's), at most GENESIS_VSPRITE_MAX of them.
 * A visible piece the full host budget cannot take is counted and logged, never dropped silently. */
static void submit_actors(const SegaModHost *h, const SegaGenesisRenderApi *render, int32_t lo, int32_t hi, int plan_known) {
  uint32_t i, n = 0U, lost = 0U;
  for (i = 0U; i < served_n; ++i) {
    GenesisVirtualSprite *c = &vset.sprites[n];
    const Piece *p = &served[i];
    if (p->x < -900 || p->x > 900 || p->y < -900 || p->y > 900) continue;
    if (!piece_visible(p, lo, hi)) continue;
    if (n >= GENESIS_VSPRITE_MAX) { ++lost; continue; }
    { uint8_t *z = (uint8_t *)c; uint32_t b; for (b = 0U; b < (uint32_t)sizeof *c; ++b) z[b] = 0U; }
    c->provenance = (uint8_t)GENESIS_VSPRITE_GAME_STATE_VERIFIED;
    c->layer = (uint8_t)((p->attr & 0x8000U) != 0U ? GENESIS_VSPRITE_LAYER_ABOVE_ALL : GENESIS_VSPRITE_LAYER_BETWEEN);   /* the piece's own priority bit (bit 15 of the attribute word): a priority-0 piece sits behind high-priority planes, as the hardware draws it */
    c->width_cells = (uint8_t)(((p->size >> 2) & 3U) + 1U);
    c->height_cells = (uint8_t)((p->size & 3U) + 1U);
    c->palette = (uint8_t)((p->attr >> 13) & 3U);
    c->h_flip = (uint8_t)((p->attr >> 11) & 1U);
    c->v_flip = (uint8_t)((p->attr >> 12) & 1U);
    c->tile_index = (uint16_t)(p->attr & 0x7FFU);
    if (p->edge != 0U) { c->flags = (uint8_t)GENESIS_VSPRITE_FLAG_HARDWARE_PIECE; c->has_clip = 1U; c->clip_y = 0; c->clip_h = RASTER_H; c->clip_w = 1024U; c->clip_x = (int16_t)(p->edge == 1U ? RASTER_W : -1024); }
    c->x = p->x;
    c->y = p->y;
    ++n;
  }
  stat_lost_visible += lost;
  if (!plan_known) stat_lost_scratch += stat_unlikely_dropped;   /* while the plan is changing, a candidate the scratch could not hold may have been visible: not silent */
  stat_unlikely_dropped = 0U;
  if ((lost != 0U || stat_lost_scratch != 0U) && lost_prev == 0U && lost_logged < 8U) {
    static const char msg[] = "castle: visible virtual sprites exceeded the host budget or the candidate scratch; the later ones of the frame are not drawn";
    if (h->log != NULL) h->log(msg, (uint32_t)(sizeof msg - 1U));
    ++lost_logged;
  }
  lost_prev = lost + stat_lost_scratch;
  stat_lost_scratch = 0U;
  if (n == 0U) return;
  vset.space = (uint8_t)GENESIS_VSPRITE_SPACE_PRESENTATION;
  vset.budget_mode = (uint8_t)GENESIS_VSPRITE_BUDGET_EXTENDED;
  vset.count = n;
  (void)render->virtual_sprites(&vset);
}

static uint32_t scene_id_valid_for_actors(const SegaModHost *h) { Plane a, b; return classify(h, &a, &b) != 0U; }

/* The columns of the planned total (2 * margin) that lie left of the picture, as a pure function of the camera (no state: replay, rewind and load see the same value for the same camera).
 * `range` is the camera's last value (level width - 320). The view is aligned left at the level's first column, centred in the middle and aligned right at its last column, as a side-scroller wants, but the
 * picture is not moved with the camera: while `left` changes, the picture's own parallax layers (the guest draws them for ITS camera, scroll k * camera) are offset from the view's world by (1 - k) * left, so they
 * drift against the foreground at (1 - k) * d(left)/d(camera) of the camera's speed. A 1:1 slide (left = camera) froze the world in the view while every background layer slid backwards, which is the dizzying parallax.
 * `left` therefore ramps slowly, over RAMP_DEN margins of camera travel at each end (at most 1/RAMP_DEN of a pixel per camera pixel, and never more than the camera moved, so no void is shown left of the level
 * and the view's right edge never passes the level's end), and is constant everywhere else. A level too short for the ramp keeps the plain rule: the picture at the left until the camera is `margin` in. */
#define RAMP_DEN 6
static int32_t placement(int32_t cam, int32_t range, int32_t margin) {
  int64_t zone, lo, hi;
  if (cam < 0) cam = 0;
  if (range < 2 * margin) return cam < margin ? cam : margin;   /* the level is narrower than the planned total: no room for a ramp at each end */
  if (cam > range) cam = range;
  zone = range / 2 < (int64_t)RAMP_DEN * margin ? range / 2 : (int64_t)RAMP_DEN * margin;   /* >= margin: a slope of at most 1 */
  lo = cam < zone ? cam : zone;
  hi = range - cam < zone ? range - cam : zone;
  return (int32_t)(((int64_t)margin * lo) / zone + (int64_t)margin - ((int64_t)margin * hi) / zone);
}

static void provider_frame_end(const SegaModHost *h) {
  served_n = scene_id_valid_for_actors(h) ? collected_n : 0U;
  { uint32_t k; for (k = 0U; k < served_n; ++k) served[k] = collected[k]; }
  collected_n = 0U;
  ready = 0U;
  band_ready = 0U;
  scene_id = classify(h, &plane_a, &plane_b);
  if (st.flash != 0U) --st.flash;
  view_declared = 0U;
  if (scene_id == 0U) return;
  margin_used = margin_learnt;
  if (margin_used != 0U) {
    view_left_px = placement(plane_a.cam, (int32_t)plane_a.cols * 16 - 320, (int32_t)margin_used);
    view_declared = 1U;
  } else {
    view_left_px = LEGACY_LEFT;
  }
  band_x0 = -((view_left_px + 7) / 8) - BAND_SLACK;
  place(&plane_a, view_left_px);
  place(&plane_b, view_left_px);
  /* Plane B of most scenes is a tiling background that the VDP-derived extension already shows exactly, wrapped: in those scenes (`b_generic`, measured per scene) its margins were pixel-identical to this
   * provider's authored ones in every sampled frame and its words equal the VDP's in every answered cell, and its scroll can differ from the record this provider reads (parallax rows), so nothing is authored
   * for it (product ADR 0314). Two scenes (a48x160-b48, a96x64-b96) differ, because their plane B map is taller than the VDP's 64-cell plane: there the authored world rows are submitted. */
  plane_b_authored = scenes[scene_id - 1U].b_generic == 0U;
  if (!build_plane(h, &plane_a, plane_a.map, TABLE_A, plane_a.cols, A_BLOCKS, 0, words_a) || (plane_b_authored && !build_plane(h, &plane_b, plane_b.map, TABLE_B, plane_b.cols, B_BLOCKS, plane_b.cols == 32U, words_b))) { scene_id = 0U; return; }
  /* the second window of each plane (ADR 0313): the same cell builder over the unscrolled plane coordinates and the rows where a split-scroll band lives (rows from BAND_ROW0 down) */
  { Plane ba = plane_a, bb = plane_b;
    ba.cell_x0 = bb.cell_x0 = band_x0; ba.cell_y0 = plane_a.band_y0; bb.cell_y0 = plane_b.band_y0; ba.window_rows = bb.window_rows = BROWS;
    band_ready = build_plane(h, &ba, ba.map, TABLE_A, ba.cols, A_BLOCKS, 0, band_a) && (!plane_b_authored || build_plane(h, &bb, bb.map, TABLE_B, bb.cols, B_BLOCKS, bb.cols == 32U, band_b)); }
  ready = 1U;
}

/* ---- Practice+: the only code that changes the game. Every write goes through a declared read-write range of mod.toml. ---- */
/* `input`: the sample of player 1. A complete chord is removed from what the guest reads, but only inside a verified level. */
static void intercept(const SegaModHost *h) {
  uint32_t pad = 0U;
  Plane a, b;
  st.chord_now = 0U;
  if (h->input_get(1U, &pad) != 0) return;
  st.chord_now = (pad & CHORD) == CHORD ? 1U : 0U;
  if (st.chord_now != 0U && classify(h, &a, &b) != 0U) (void)h->input_set(1U, pad & ~CHORD);
}

static void practice(const SegaModHost *h) {
  uint32_t power = 0U, flags = 0U, i;
  Plane a, b;
  if (st.chord_now != 0U && st.chord_held == 0U && classify(h, &a, &b) != 0U && rd(h, POWER, 2U, &power) == 0 && power >= 1U && power < POWER_MAX && rd(h, HUD_FLAGS, 1U, &flags) == 0) {
    int ok = h->write(SEGA_GEN_SPACE_M68K_WORK_RAM, POWER, 2U, POWER_MAX) == 0;
    for (i = 0U; ok && i < POWER_MAX; ++i) ok = h->write(SEGA_GEN_SPACE_M68K_WORK_RAM, HUD_SLOTS + 2U * i, 2U, HUD_SLOT_FILLED) == 0;
    if (ok && h->write(SEGA_GEN_SPACE_M68K_WORK_RAM, HUD_FLAGS, 1U, flags | 1U) == 0) {
      ++st.restores;
      st.flash = FLASH_FRAMES;
    }
  }
  st.chord_held = st.chord_now;   /* updated every frame, valid scene or not: a chord that was already down never fires later */
}

static void provider_render(const SegaModHost *h) {
  uint32_t serve, m = 0U;
  int32_t view_lo, view_hi;
  const SegaGenesisFeatures *features = (const SegaGenesisFeatures *)h->platform_features;
  const SegaGenesisRenderApi *render;
  if (features == NULL || features->size < sizeof(SegaGenesisFeatures) || features->render == NULL || scene_id == 0U) return;
  render = features->render;
  { const char *n = scenes[scene_id - 1U].name; uint32_t len = 0U; while (n[len] != 0) ++len; (void)render->scene(n, len); }
  serve = ready;
  {   /* learn the host's plan for the next frame-end; declare the placement the windows below were built for, only while that plan is still the host's */
    if (features->render->view_margin != NULL && features->render->view_left != NULL && features->render->view_margin(&m) == 0) {
      margin_learnt = m;
      if (view_declared != 0U) {
        if (m == margin_used) (void)features->render->view_left((uint32_t)view_left_px, margin_used);
        else serve = 0U;   /* the windows were built for a view of another margin: neither they nor a placement are submitted (the scenery is generic this frame; the HUD layer and the actors are independent of the view) */
      }
    } }
  if (serve != 0U) {
    if (plane_a.window_rows != 0U) (void)render->scenery_window(0U, plane_a.cell_x0, plane_a.cell_y0, WCOLS, plane_a.window_rows, words_a);
    if (plane_b_authored != 0U && plane_b.window_rows != 0U) (void)render->scenery_window(1U, plane_b.cell_x0, plane_b.cell_y0, WCOLS, plane_b.window_rows, words_b);
    if (band_ready != 0U) {   /* a cell is answered by the first window of its plane that contains it: the main window first */
      (void)render->scenery_window(0U, band_x0, plane_a.band_y0, WCOLS, BROWS, band_a);
      if (plane_b_authored != 0U) (void)render->scenery_window(1U, band_x0, plane_b.band_y0, WCOLS, BROWS, band_b);
    }
  }
  /* The view the host presents this frame, for the exact choice of actor pieces. With the placement known (the windows above were built for this very margin) it is exactly [-left, 320 + total - left); when it is not (the plan changed this frame, or no placement was
   * declared) the widest placement of the plan; with no extension at all (Original, 4:3) just the picture; a host without the plan queries is assumed to present the widest view. */
  if (render->view_margin == NULL || render->view_left == NULL) { view_lo = -LEGACY_LEFT; view_hi = RASTER_W + LEGACY_LEFT; }
  else if (view_declared != 0U && m == margin_used) { view_lo = -view_left_px; view_hi = RASTER_W + 2 * (int32_t)margin_used - view_left_px; }
  else { const int32_t mw = (int32_t)(m > margin_used ? m : margin_used); view_lo = -mw; view_hi = RASTER_W + 2 * mw; }
  submit_actors(h, render, view_lo, view_hi, render->view_margin != NULL && render->view_left != NULL && view_declared != 0U && m == margin_used);
}

static int provider_init(void *state, const SegaModHost *host) {
  (void)state;
  return host->platform == SEGA_MOD_PLATFORM && host->platform_features != NULL ? 0 : 1;
}

static void provider_phase(void *state, const SegaModHost *host) {
  (void)state;
  if (host->phase == SEGA_MOD_PHASE_RESET) { collected_n = served_n = 0U; stat_lost_visible = stat_lost_scratch = stat_unlikely_dropped = stat_evicted = lost_logged = lost_prev = 0U; ready = band_ready = scene_id = view_declared = margin_learnt = 0U; st.chord_held = st.restores = st.flash = st.chord_now = 0U; }
  else if (host->phase == SEGA_MOD_PHASE_INPUT) intercept(host);
  else if (host->phase == SEGA_MOD_PHASE_POST_INPUT) practice(host);
  else if (host->phase == SEGA_MOD_PHASE_FRAME_END) provider_frame_end(host);
  else if (host->phase == SEGA_MOD_PHASE_RENDER) provider_render(host);
}

static int provider_save(void *state, uint8_t *out, uint32_t cap, uint32_t *len) {
  const uint32_t values[4] = {st.chord_held, st.restores, st.flash, st.chord_now};
  uint32_t i;
  (void)state;
  if (cap < 16U) return 1;
  for (i = 0U; i < 16U; ++i) out[i] = (uint8_t)(values[i / 4U] >> (24U - 8U * (i % 4U)));
  *len = 16U;
  return 0;
}

static int provider_load(void *state, const uint8_t *in, uint32_t len) {
  uint32_t values[4], i;
  (void)state;
  if (len != 16U) return 1;
  for (i = 0U; i < 4U; ++i) values[i] = ((uint32_t)in[4U * i] << 24U) | ((uint32_t)in[4U * i + 1U] << 16U) | ((uint32_t)in[4U * i + 2U] << 8U) | (uint32_t)in[4U * i + 3U];
  if (values[0] > 1U || values[2] > FLASH_FRAMES || values[3] > 1U) return 1;
  st.chord_held = values[0];
  st.restores = values[1];
  st.flash = values[2];
  st.chord_now = values[3];
  collected_n = served_n = 0U;   /* pieces are re-collected from the next frame's hook calls */
  ready = band_ready = scene_id = view_declared = 0U;   /* rebuilt from guest RAM at the next frame-end; nothing of an earlier frame is drawn */
  return 0;
}

static const SegaModProvider provider = {sizeof(SegaModProvider), SEGA_MOD_ABI_MAJOR, 0U, SEGA_MOD_PLATFORM, "castle-of-illusion-widescreen-practice", 1U, provider_init, provider_phase, provider_hook, provider_save, provider_load,
                                         {NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL}};

const SegaModProvider *segarecomp_mod_provider(void **state_out) {
  if (state_out != NULL) *state_out = &st;
  return &provider;
}
