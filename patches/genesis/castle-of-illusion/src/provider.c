/* Castle of Illusion starring Mickey Mouse (Genesis, USA/Europe): authored widescreen scenery, native ABI 2 (strict C11).
 *
 * Everything here is a fact about the game's WORK RAM for ONE exact image (see mod.toml / README.md); nothing is read from, or copied out of, the cartridge. The game keeps, for each scrolling plane, a small record
 * (plane A at 0xFA80, plane B at 0xFAC0, big-endian words) and a byte map of 16 x 16 pixel blocks plus a table that expands a block to four VDP name-table words:
 *   +0 vertical scroll   +4 horizontal scroll (the camera x)   +8/+10 map address (long)   +12 map rows   +14 map columns (blocks)   +16/+18 block-table address (long)
 * A block b of the table is four words (top-left, top-right, bottom-left, bottom-right cell) at table + 8 * b. This provider rebuilds the name-table words of the cells BESIDE the picture from those two
 * structures and hands them to the host as an authored scenery window. It is presentation only: it never writes guest memory in this file's scenery path. */
#include <segarecomp_mod_genesis.h>

#define REC_A 0xFA80U
#define REC_B 0xFAC0U
#define MAP_A 0x2000U
#define MAP_B 0x5000U
#define TABLE_A 0x0000U
#define TABLE_B 0x0800U
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
static void place(Plane *p, uint32_t span_cells, uint32_t max_rows_cells) {
  int32_t hs = -p->cam;
  hs = ((hs + 512) & 1023) - 512;
  p->shift_cells = (p->cam + hs) / 8;                    /* exact: cam + hs is a multiple of 1024 */
  p->cell_x0 = (p->cam / 8 - 40) - p->shift_cells;      /* 40 cells of slack on the left: more than the widest side style needs */
  p->cell_y0 = p->vscroll / 8 - 1;
  if (p->cell_y0 < 0) p->cell_y0 = 0;
  p->window_rows = WROWS;
  if ((uint32_t)p->cell_y0 + p->window_rows > max_rows_cells) p->window_rows = (uint32_t)p->cell_y0 >= max_rows_cells ? 0U : max_rows_cells - (uint32_t)p->cell_y0;
  (void)span_cells;
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

static void provider_frame_end(const SegaModHost *h) {
  uint32_t cols_a = 0U, cols_b = 0U;
  ready = 0U;
  scene_id = 0U;
  if (!record(h, REC_A, MAP_A, TABLE_A, &plane_a, &cols_a) || !record(h, REC_B, MAP_B, TABLE_B, &plane_b, &cols_b)) return;
  plane_a.cols = cols_a;
  plane_b.cols = B_STRIDE;
  if (plane_a.rows == 16U && plane_a.cols == 240U && plane_b.rows == 16U) scene_id = 1U;        /* Enchanted Forest */
  else if (plane_a.rows == 32U && plane_a.cols == 112U && plane_b.rows == 32U) scene_id = 2U;    /* the castle interior of the attract demo */
  if (scene_id == 0U) return;
  if (plane_a.vscroll > 511 || plane_b.vscroll > 511 || plane_a.cam < 0 || plane_b.cam < 0 || plane_a.cam >= (int32_t)plane_a.cols * 16 || plane_b.cam >= 1024) { scene_id = 0U; return; }
  place(&plane_a, WCOLS, plane_a.rows * 2U);
  place(&plane_b, WCOLS, plane_b.rows * 2U);
  if (!build_plane(h, &plane_a, MAP_A, TABLE_A, plane_a.cols, A_BLOCKS, 0, words_a) || !build_plane(h, &plane_b, MAP_B, TABLE_B, B_STRIDE, B_BLOCKS, 1, words_b)) { scene_id = 0U; return; }
  ready = 1U;
}

static void provider_render(const SegaModHost *h) {
  const SegaGenesisFeatures *features = (const SegaGenesisFeatures *)h->platform_features;
  const SegaGenesisRenderApi *render;
  if (features == NULL || features->size < sizeof(SegaGenesisFeatures) || features->render == NULL || ready == 0U || scene_id == 0U) return;
  render = features->render;
  (void)render->scene(scene_id == 1U ? "enchanted-forest" : "castle-interior", scene_id == 1U ? 16U : 15U);
  if (plane_a.window_rows != 0U) (void)render->scenery_window(0U, plane_a.cell_x0, plane_a.cell_y0, WCOLS, plane_a.window_rows, words_a);
  if (plane_b.window_rows != 0U) (void)render->scenery_window(1U, plane_b.cell_x0, plane_b.cell_y0, WCOLS, plane_b.window_rows, words_b);
}

static int provider_init(void *state, const SegaModHost *host) {
  (void)state;
  return host->platform == SEGA_MOD_PLATFORM && host->platform_features != NULL ? 0 : 1;
}

static void provider_phase(void *state, const SegaModHost *host) {
  (void)state;
  if (host->phase == SEGA_MOD_PHASE_RESET) ready = scene_id = 0U;
  else if (host->phase == SEGA_MOD_PHASE_FRAME_END) provider_frame_end(host);
  else if (host->phase == SEGA_MOD_PHASE_RENDER) provider_render(host);
}

static int provider_save(void *state, uint8_t *out, uint32_t cap, uint32_t *len) {
  (void)state;
  if (cap < 4U) return 1;
  out[0] = out[1] = out[2] = out[3] = 0U;   /* no mod state yet: the window is rebuilt from guest RAM at every frame-end */
  *len = 4U;
  return 0;
}

static int provider_load(void *state, const uint8_t *in, uint32_t len) {
  (void)state;
  (void)in;
  ready = scene_id = 0U;
  return len == 4U ? 0 : 1;
}

static const SegaModProvider provider = {sizeof(SegaModProvider), SEGA_MOD_ABI_MAJOR, 0U, SEGA_MOD_PLATFORM, "castle-of-illusion-widescreen", 1U, provider_init, provider_phase, NULL, provider_save, provider_load,
                                         {NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL}};

const SegaModProvider *segarecomp_mod_provider(void **state_out) {
  if (state_out != NULL) *state_out = &ready;
  return &provider;
}
