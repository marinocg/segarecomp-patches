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
 * and everything else are never touched. */
#include <segarecomp_mod_genesis.h>

#define REC_A 0xFA80U
#define REC_B 0xFAC0U
#define MAP_A 0x2000U
#define MAP_B 0x5000U
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
#define B_STRIDE 32U      /* plane B's map is 32 blocks wide in both verified levels (its record's own column field is not a stride in every scene) */
#define A_BLOCKS 256U
#define B_BLOCKS 256U
#define WCOLS 128U        /* the widest window the host accepts: 32:9 needs about 30 cells each side of the picture, the rest absorbs the camera's motion since the frame-end read */
#define WROWS 32U         /* 28 visible rows + 1 partial + one row of slack on each side; 128 x 32 = 4096 words is the host's window bound */

typedef struct Plane {
  int32_t cam;            /* the game's horizontal scroll value (camera x, pixels) */
  int32_t vscroll;
  uint32_t rows, cols;    /* map size in blocks (the map record's own fields) */
  int32_t shift_cells;    /* world cell - window plane cell: a multiple of 128 while the VDP's 10-bit scroll has wrapped */
  int32_t cell_x0, cell_y0;
  uint32_t window_rows;
} Plane;

static Plane plane_a, plane_b;
static uint16_t words_a[WCOLS * WROWS], words_b[WCOLS * WROWS];
typedef struct ModState {
  uint32_t chord_held;    /* the chord was down at the latest post-input (an edge needs it up first) */
  uint32_t restores;      /* completed restorations since reset */
  uint32_t flash;         /* frames left of the "POWER" notice */
} ModState;
static ModState st;
static uint32_t scene_id;          /* 0 = nothing verified this frame, 1 = Enchanted Forest, 2 = castle interior */
static uint32_t ready;             /* a window was built at the latest frame-end for the next render */

static int rd(const SegaModHost *h, uint32_t offset, uint32_t width, uint32_t *value) { return h->read(SEGA_GEN_SPACE_M68K_WORK_RAM, offset, width, value); }

static int record(const SegaModHost *h, uint32_t base, uint32_t map, uint32_t table, Plane *p, uint32_t *stored_cols) {
  uint32_t v = 0U, cam = 0U, ptr_hi = 0U, ptr_lo = 0U, rows = 0U, cols = 0U, tbl_hi = 0U, tbl_lo = 0U;
  if (rd(h, base, 2U, &v) || rd(h, base + 4U, 2U, &cam) || rd(h, base + 8U, 2U, &ptr_hi) || rd(h, base + 10U, 2U, &ptr_lo) || rd(h, base + 12U, 2U, &rows) || rd(h, base + 14U, 2U, &cols) ||
      rd(h, base + 16U, 2U, &tbl_hi) || rd(h, base + 18U, 2U, &tbl_lo))
    return 0;
  if (ptr_hi != 0xFFU || ptr_lo != map || tbl_hi != 0xFFU || tbl_lo != table) return 0;   /* the record of a running scrolling level, not a menu, cutscene or transition (those leave it zeroed) */
  p->vscroll = (int32_t)v;
  p->cam = (int32_t)cam;
  p->rows = rows;
  *stored_cols = cols;
  return 1;
}

/* The VDP applies a 10-bit scroll: -camera wraps into [-512, 511]; the host's plane coordinate is screen x - that value. */
static void place(Plane *p, uint32_t max_rows_cells) {
  int32_t hs = -p->cam;
  hs = ((hs + 512) & 1023) - 512;
  p->shift_cells = (p->cam + hs) / 8;                    /* exact: cam + hs is a multiple of 1024 */
  p->cell_x0 = (p->cam / 8 - 40) - p->shift_cells;      /* 40 cells of slack on the left: more than the widest side style needs */
  p->cell_y0 = p->vscroll / 8 - 1;
  if (p->cell_y0 < 0) p->cell_y0 = 0;
  p->window_rows = WROWS;
  if ((uint32_t)p->cell_y0 + p->window_rows > max_rows_cells) p->window_rows = (uint32_t)p->cell_y0 >= max_rows_cells ? 0U : max_rows_cells - (uint32_t)p->cell_y0;
}

static int build_plane(const SegaModHost *h, const Plane *p, uint32_t map, uint32_t table, uint32_t stride, uint32_t blocks, int wrap, uint16_t *out) {
  uint16_t cache[A_BLOCKS][4];
  uint8_t have[A_BLOCKS];
  uint32_t r, c, i;
  for (i = 0U; i < blocks; ++i) have[i] = 0U;
  for (r = 0U; r < p->window_rows; ++r) {
    const int32_t wy = p->cell_y0 + (int32_t)r;
    for (c = 0U; c < WCOLS; ++c) {
      const int32_t wx = p->cell_x0 + (int32_t)c + p->shift_cells;
      uint32_t b = 0U, word = 0U;
      int32_t bx = wx >> 1;
      const int32_t by = wy >> 1;
      if (wrap) bx = bx & (int32_t)(stride - 1U);
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

/* The verified scenes: 0 = none (a menu, cutscene, load, transition or an unverified level), 1 = Enchanted Forest, 2 = castle interior. Fills both planes from the live records. */
static uint32_t classify(const SegaModHost *h, Plane *a, Plane *b) {
  uint32_t cols_a = 0U, cols_b = 0U, id = 0U;
  if (!record(h, REC_A, MAP_A, TABLE_A, a, &cols_a) || !record(h, REC_B, MAP_B, TABLE_B, b, &cols_b)) return 0U;
  a->cols = cols_a;
  b->cols = B_STRIDE;
  if (a->rows == 16U && a->cols == 240U && b->rows == 16U) id = 1U;        /* Enchanted Forest */
  else if (a->rows == 32U && a->cols == 112U && b->rows == 32U) id = 2U;   /* the castle interior of the attract demo */
  if (id == 0U) return 0U;
  if (a->vscroll > 511 || b->vscroll > 511 || a->cam < 0 || b->cam < 0 || a->cam >= (int32_t)a->cols * 16 || b->cam >= (int32_t)a->cols * 16) return 0U;
  return id;
}

static void provider_frame_end(const SegaModHost *h) {
  ready = 0U;
  scene_id = classify(h, &plane_a, &plane_b);
  if (st.flash != 0U) --st.flash;
  if (scene_id == 0U) return;
  place(&plane_a, plane_a.rows * 2U);
  place(&plane_b, plane_b.rows * 2U);
  if (!build_plane(h, &plane_a, MAP_A, TABLE_A, plane_a.cols, A_BLOCKS, 0, words_a) || !build_plane(h, &plane_b, MAP_B, TABLE_B, B_STRIDE, B_BLOCKS, 1, words_b)) { scene_id = 0U; return; }
  ready = 1U;
}

/* ---- Practice+: the only code that changes the game. Every write goes through a declared read-write range of mod.toml. ---- */
static void practice(const SegaModHost *h) {
  uint32_t pad = 0U, power = 0U, flags = 0U, i, chord;
  Plane a, b;
  if (h->input_get(1U, &pad) != 0) return;
  chord = (pad & CHORD) == CHORD ? 1U : 0U;
  if (chord != 0U && st.chord_held == 0U && classify(h, &a, &b) != 0U && rd(h, POWER, 2U, &power) == 0 && power >= 1U && power < POWER_MAX && rd(h, HUD_FLAGS, 1U, &flags) == 0) {
    int ok = h->write(SEGA_GEN_SPACE_M68K_WORK_RAM, POWER, 2U, POWER_MAX) == 0;
    for (i = 0U; ok && i < POWER_MAX; ++i) ok = h->write(SEGA_GEN_SPACE_M68K_WORK_RAM, HUD_SLOTS + 2U * i, 2U, HUD_SLOT_FILLED) == 0;
    if (ok && h->write(SEGA_GEN_SPACE_M68K_WORK_RAM, HUD_FLAGS, 1U, flags | 1U) == 0) {
      ++st.restores;
      st.flash = FLASH_FRAMES;
    }
  }
  st.chord_held = chord;   /* updated every frame, valid scene or not: a chord that was already down never fires later */
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
  (void)render->scene(scene_id == 1U ? "enchanted-forest" : "castle-interior", scene_id == 1U ? 16U : 15U);
  if (ready != 0U) {
    if (plane_a.window_rows != 0U) (void)render->scenery_window(0U, plane_a.cell_x0, plane_a.cell_y0, WCOLS, plane_a.window_rows, words_a);
    if (plane_b.window_rows != 0U) (void)render->scenery_window(1U, plane_b.cell_x0, plane_b.cell_y0, WCOLS, plane_b.window_rows, words_b);
  }
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
  if (host->phase == SEGA_MOD_PHASE_RESET) { ready = scene_id = 0U; st.chord_held = st.restores = st.flash = 0U; }
  else if (host->phase == SEGA_MOD_PHASE_POST_INPUT) practice(host);
  else if (host->phase == SEGA_MOD_PHASE_FRAME_END) provider_frame_end(host);
  else if (host->phase == SEGA_MOD_PHASE_RENDER) provider_render(host);
}

static int provider_save(void *state, uint8_t *out, uint32_t cap, uint32_t *len) {
  const uint32_t values[3] = {st.chord_held, st.restores, st.flash};
  uint32_t i;
  (void)state;
  if (cap < 12U) return 1;
  for (i = 0U; i < 12U; ++i) out[i] = (uint8_t)(values[i / 4U] >> (24U - 8U * (i % 4U)));
  *len = 12U;
  return 0;
}

static int provider_load(void *state, const uint8_t *in, uint32_t len) {
  uint32_t values[3], i;
  (void)state;
  if (len != 12U) return 1;
  for (i = 0U; i < 3U; ++i) values[i] = ((uint32_t)in[4U * i] << 24U) | ((uint32_t)in[4U * i + 1U] << 16U) | ((uint32_t)in[4U * i + 2U] << 8U) | (uint32_t)in[4U * i + 3U];
  if (values[0] > 1U || values[2] > FLASH_FRAMES) return 1;
  st.chord_held = values[0];
  st.restores = values[1];
  st.flash = values[2];
  ready = scene_id = 0U;   /* rebuilt from guest RAM at the next frame-end; nothing of an earlier frame is drawn */
  return 0;
}

static const SegaModProvider provider = {sizeof(SegaModProvider), SEGA_MOD_ABI_MAJOR, 0U, SEGA_MOD_PLATFORM, "castle-of-illusion-widescreen-practice", 1U, provider_init, provider_phase, NULL, provider_save, provider_load,
                                         {NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL}};

const SegaModProvider *segarecomp_mod_provider(void **state_out) {
  if (state_out != NULL) *state_out = &st;
  return &provider;
}
