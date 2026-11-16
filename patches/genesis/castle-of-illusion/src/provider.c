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
#define WCOLS 128U        /* the widest window the host accepts: 32:9 needs about 30 cells each side of the picture, the rest absorbs the camera's motion since the frame-end read */
#define WROWS 32U         /* 28 visible rows + 1 partial + one row of slack on each side; 128 x 32 = 4096 words is the host's window bound */

typedef struct Plane {
  int32_t cam;            /* the game's horizontal scroll value (camera x, pixels) */
  int32_t vscroll;
  uint32_t rows, cols;    /* map size in blocks (the map record's own fields) */
  uint32_t map;           /* the map's work-RAM address (plane A: the record's own, plane B: fixed) */
  int32_t shift_cells;    /* world cell - window plane cell (x): a multiple of 128 while the VDP's 10-bit scroll has wrapped */
  int32_t shift_rows;     /* the same for y */
  int32_t cell_x0, cell_y0;
  uint32_t window_rows;
} Plane;

static Plane plane_a, plane_b;
static uint16_t words_a[WCOLS * WROWS], words_b[WCOLS * WROWS];
typedef struct ModState {
  uint32_t chord_held;    /* the chord was down at the latest post-input (an edge needs it up first) */
  uint32_t restores;      /* completed restorations since reset */
  uint32_t flash;         /* frames left of the "POWER" notice */
  uint32_t chord_now;     /* the chord is down in this frame's sample (set at `input`, read at `post-input`) */
} ModState;
static ModState st;
static uint32_t scene_id;          /* 0 = nothing verified this frame, else 1 + the index in `scenes` */
static uint32_t ready;             /* a window was built at the latest frame-end for the next render */

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
static void place(Plane *p) {
  int32_t hs = -p->cam, vs = ((p->vscroll + 512) & 1023) - 512;
  hs = ((hs + 512) & 1023) - 512;
  p->shift_cells = (p->cam + hs) / 8;                    /* exact: cam + hs is a multiple of 1024 */
  p->shift_rows = (p->vscroll - vs) / 8;
  p->cell_x0 = (p->cam / 8 - 40) - p->shift_cells;      /* 40 cells of slack on the left: more than the widest side style needs */
  p->cell_y0 = (vs >> 3) - 1;                           /* one row of slack above the visible rows (floor division) */
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
typedef struct Scene { uint32_t a_rows, a_cols, b_rows, b_stride; const char *name; } Scene;
static const Scene scenes[] = {
  {16U, 240U, 16U, 32U, "a16x240-b16"}, {48U, 160U, 16U, 32U, "a48x160-b16"}, {48U, 128U, 48U, 32U, "a48x128-b48"}, {16U, 32U, 16U, 32U, "a16x32-b16"},
  {192U, 48U, 192U, 32U, "a192x48-b192"}, {32U, 112U, 32U, 32U, "a32x112-b32"}, {14U, 320U, 14U, 32U, "a14x320-b14"}, {17U, 32U, 17U, 32U, "a17x32-b17"},
  {80U, 80U, 80U, 80U, "a80x80-b80x80"}, {32U, 128U, 32U, 128U, "a32x128-b32x128"}, {96U, 64U, 96U, 32U, "a96x64-b96"},
  {48U, 160U, 48U, 32U, "a48x160-b48"}, {48U, 256U, 48U, 32U, "a48x256-b48"}, {16U, 160U, 16U, 32U, "a16x160-b16"}, {32U, 32U, 32U, 32U, "a32x32-b32"},
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
#define PIECE_MAX 48U
#define PIECE_X_LO 0x60
#define PIECE_X_HI 0x1E0
#define OBJECT_FLAGS 0xEU        /* byte at object + 0xE: bit 5 = never clipped */
#define OBJECT_LO 0xA000U
#define SPRITE_BUFFER_LO 0xF506U /* the buffer position of an x slot (entry base + 6 .. ) inside the buffer at 0xF500 */
#define SPRITE_BUFFER_HI 0xF800U
typedef struct Piece { int16_t x, y; uint16_t attr; uint8_t size; } Piece;
static Piece collected[PIECE_MAX], served[PIECE_MAX];
static uint32_t collected_n, served_n;
static GenesisVirtualSpriteSet vset;

static int provider_hook(void *state, const SegaModHost *h, uint32_t hook_id) {
  uint32_t d0 = 0U, a0 = 0U, a2 = 0U, yw = 0U, size = 0U, attr = 0U, flags = 0U;
  int32_t x;
  (void)state;
  (void)hook_id;
  if (collected_n >= PIECE_MAX) return 0;
  if (h->read(SEGA_GEN_SPACE_M68K_HOOK_REGS, 0U, 4U, &d0) != 0 || h->read(SEGA_GEN_SPACE_M68K_HOOK_REGS, 8U, 4U, &a0) != 0 || h->read(SEGA_GEN_SPACE_M68K_HOOK_REGS, 10U, 4U, &a2) != 0) return 0;
  x = (int32_t)(int16_t)(uint16_t)(d0 & 0xFFFFU);
  if (x >= PIECE_X_LO && x < PIECE_X_HI) return 0;                   /* the game keeps it (and the host's own sprite layer shows it) */
  a2 &= 0xFFFFU;
  if (a2 < SPRITE_BUFFER_LO || a2 >= SPRITE_BUFFER_HI) return 0;
  a0 &= 0xFFFFU;
  if (a0 < OBJECT_LO || a0 + OBJECT_FLAGS >= SPRITE_BUFFER_HI) return 0;   /* only objects inside the declared range are read (anything else is not a verified object) */
  if (rd(h, a0 + OBJECT_FLAGS, 1U, &flags) != 0 || (flags & 0x20U) != 0U) return 0;   /* never-clipped objects are kept by the game */
  if (rd(h, a2 - 6U, 2U, &yw) != 0 || rd(h, a2 - 4U, 1U, &size) != 0 || rd(h, a2 - 2U, 2U, &attr) != 0) return 0;
  collected[collected_n].x = (int16_t)(x - 128);
  collected[collected_n].y = (int16_t)((int32_t)(int16_t)(uint16_t)yw - 128);
  collected[collected_n].attr = (uint16_t)attr;
  collected[collected_n].size = (uint8_t)size;
  ++collected_n;
  return 0;
}

static void submit_actors(const SegaGenesisRenderApi *render) {
  uint32_t i, n = 0U;
  for (i = 0U; i < served_n && n < GENESIS_VSPRITE_MAX; ++i) {
    GenesisVirtualSprite *c = &vset.sprites[n];
    const Piece *p = &served[i];
    if (p->x < -900 || p->x > 900 || p->y < -900 || p->y > 900) continue;
    { uint8_t *z = (uint8_t *)c; uint32_t b; for (b = 0U; b < (uint32_t)sizeof *c; ++b) z[b] = 0U; }
    c->provenance = (uint8_t)GENESIS_VSPRITE_GAME_STATE_VERIFIED;
    c->layer = (uint8_t)GENESIS_VSPRITE_LAYER_ABOVE_ALL;
    c->width_cells = (uint8_t)(((p->size >> 2) & 3U) + 1U);
    c->height_cells = (uint8_t)((p->size & 3U) + 1U);
    c->palette = (uint8_t)((p->attr >> 13) & 3U);
    c->h_flip = (uint8_t)((p->attr >> 11) & 1U);
    c->v_flip = (uint8_t)((p->attr >> 12) & 1U);
    c->tile_index = (uint16_t)(p->attr & 0x7FFU);
    c->x = p->x;
    c->y = p->y;
    ++n;
  }
  if (n == 0U) return;
  vset.space = (uint8_t)GENESIS_VSPRITE_SPACE_PRESENTATION;
  vset.budget_mode = (uint8_t)GENESIS_VSPRITE_BUDGET_LIMIT;
  vset.count = n;
  (void)render->virtual_sprites(&vset);
}

static uint32_t scene_id_valid_for_actors(const SegaModHost *h) { Plane a, b; return classify(h, &a, &b) != 0U; }

static void provider_frame_end(const SegaModHost *h) {
  served_n = scene_id_valid_for_actors(h) ? collected_n : 0U;
  { uint32_t k; for (k = 0U; k < served_n; ++k) served[k] = collected[k]; }
  collected_n = 0U;
  ready = 0U;
  scene_id = classify(h, &plane_a, &plane_b);
  if (st.flash != 0U) --st.flash;
  if (scene_id == 0U) return;
  place(&plane_a);
  place(&plane_b);
  if (!build_plane(h, &plane_a, plane_a.map, TABLE_A, plane_a.cols, A_BLOCKS, 0, words_a) || !build_plane(h, &plane_b, plane_b.map, TABLE_B, plane_b.cols, B_BLOCKS, plane_b.cols == 32U, words_b)) { scene_id = 0U; return; }
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

static void draw_number(const SegaGenesisRenderApi *render, int32_t x, int32_t y, uint32_t value, uint32_t rgba) {
  char digits[4];
  value %= 1000U;
  digits[0] = (char)('0' + value / 100U);
  digits[1] = (char)('0' + (value / 10U) % 10U);
  digits[2] = (char)('0' + value % 10U);
  digits[3] = 0;
  (void)render->overlay_text(x, y, digits + (value >= 100U ? 0 : (value >= 10U ? 1 : 2)), value >= 100U ? 3U : (value >= 10U ? 2U : 1U), rgba);
}

static void provider_render(const SegaModHost *h) {
  const SegaGenesisFeatures *features = (const SegaGenesisFeatures *)h->platform_features;
  const SegaGenesisRenderApi *render;
  if (features == NULL || features->size < sizeof(SegaGenesisFeatures) || features->render == NULL || scene_id == 0U) return;
  render = features->render;
  { const char *n = scenes[scene_id - 1U].name; uint32_t len = 0U; while (n[len] != 0) ++len; (void)render->scene(n, len); }
  if (ready != 0U) {
    if (plane_a.window_rows != 0U) (void)render->scenery_window(0U, plane_a.cell_x0, plane_a.cell_y0, WCOLS, plane_a.window_rows, words_a);
    if (plane_b.window_rows != 0U) (void)render->scenery_window(1U, plane_b.cell_x0, plane_b.cell_y0, WCOLS, plane_b.window_rows, words_b);
  }
  submit_actors(render);
  /* The Practice+ indicator: a small panel with the number of restorations, and a notice for a moment after one. Presentation only. */
  (void)render->overlay_rect(0, 0, st.restores != 0U ? 38 : 24, 8, 0x000000C0U);
  (void)render->overlay_text(2, 0, "P+", 2U, 0xFFD040FFU);
  if (st.restores != 0U) draw_number(render, 16, 0, st.restores, 0xFFFFFFFFU);
  if (st.flash != 0U) {
    (void)render->overlay_rect(0, 8, 40, 8, 0x000000C0U);
    (void)render->overlay_text(2, 8, "POWER", 5U, 0x60FF60FFU);
  }
}

static int provider_init(void *state, const SegaModHost *host) {
  (void)state;
  return host->platform == SEGA_MOD_PLATFORM && host->platform_features != NULL ? 0 : 1;
}

static void provider_phase(void *state, const SegaModHost *host) {
  (void)state;
  if (host->phase == SEGA_MOD_PHASE_RESET) { collected_n = served_n = 0U; ready = scene_id = 0U; st.chord_held = st.restores = st.flash = st.chord_now = 0U; }
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
  ready = scene_id = 0U;   /* rebuilt from guest RAM at the next frame-end; nothing of an earlier frame is drawn */
  return 0;
}

static const SegaModProvider provider = {sizeof(SegaModProvider), SEGA_MOD_ABI_MAJOR, 0U, SEGA_MOD_PLATFORM, "castle-of-illusion-widescreen-practice", 1U, provider_init, provider_phase, provider_hook, provider_save, provider_load,
                                         {NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL}};

const SegaModProvider *segarecomp_mod_provider(void **state_out) {
  if (state_out != NULL) *state_out = &st;
  return &provider;
}
