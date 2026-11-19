/* Castle of Illusion starring Mickey Mouse (Genesis, USA/Europe): DEBUG FREE-FLY, one native ABI 2 provider (strict C11). A user-invoked mode in the spirit of Sonic's debug mode: Mickey floats freely through the level, ignoring floors,
 * walls, ceilings, enemies and pits, so a level can be explored. NOTHING is read from, or copied out of, the cartridge; every address is a fact about the game's WORK RAM for ONE exact image (README).
 *
 * Toggle: A+B+C together on pad 1 (an edge, never a held repeat). While flying the pad is taken away from the game except Start (the game neither walks, jumps nor throws), the d-pad moves Mickey (3 px per frame; 6 with A held) inside the visible part of the screen (the game's own camera follows him at its own limited speed; he waits at the edge), his
 * vertical velocity is zeroed every frame, his position is written before the game's frame logic and asserted again at the frame's end (so a collision correction of the game cannot move him), and his power is kept full so nothing can hurt or kill him.
 * Leaving the mode hands Mickey back to the game exactly where he is: it applies its own gravity and collision again from that position. Nothing else is touched. The mode state is part of the save state. */
#include <segarecomp_mod_genesis.h>

#define MICKEY 0xDC00U         /* Mickey's object slot (0x40 bytes) */
#define OBJ_X 0x10U            /* word: x (pixels); +2: its fraction word */
#define OBJ_Y 0x14U            /* word: y (pixels); +2: its fraction word */
#define OBJ_VY_LO 0x1AU        /* the vertical velocity, 16.16: low word, then high word */
#define OBJ_VY_HI 0x1CU
#define POWER 0xF322U
#define POWER_MAX 5U
#define HUD_SLOTS 0xF244U
#define HUD_SLOT_FILLED 0x807CU
#define HUD_FLAGS 0xF409U
#define CHORD 0x70U            /* A (0x40) + B (0x10) + C (0x20) */
#define PAD_UP 0x01U
#define PAD_DOWN 0x02U
#define PAD_LEFT 0x04U
#define PAD_RIGHT 0x08U
#define PAD_A 0x40U
#define PAD_START 0x80U
#define SPEED 3
#define SPEED_FAST 6
#define POS_MAX 0x3FFF
#define CAM_X 0xFA84U          /* the game's own scroll record (plane A): the camera x (pixels) and, at 0xFA80, the vertical scroll; read only, never written: the game's streamer loads the level column by column as the camera moves */
#define CAM_Y 0xFA80U
#define MARGIN_X_LO 32         /* Mickey stays inside this part of the screen: the camera follows at its own limited speed, so he waits at the edge instead of leaving the picture */
#define MARGIN_X_HI 272
#define MARGIN_Y_LO 16
#define MARGIN_Y_HI 176

typedef struct ModState {
  uint32_t fly;          /* the mode is on */
  uint32_t chord_held;   /* the chord was down at the latest sample (an edge needs it up first) */
  uint32_t pad;          /* this frame's d-pad/A sample, for the position update */
  int32_t x, y;          /* the tracked position while flying */
} ModState;
static ModState st;

static int rd(const SegaModHost *h, uint32_t offset, uint32_t width, uint32_t *value) { return h->read(SEGA_GEN_SPACE_M68K_WORK_RAM, offset, width, value); }
static int wr(const SegaModHost *h, uint32_t offset, uint32_t width, uint32_t value) { return h->write(SEGA_GEN_SPACE_M68K_WORK_RAM, offset, width, value); }

static int32_t clampi(int32_t v) { return v < 0 ? 0 : (v > POS_MAX ? POS_MAX : v); }

/* Writes the tracked position and clears the vertical velocity. */
static void place(const SegaModHost *h) {
  (void)wr(h, MICKEY + OBJ_X, 2U, (uint32_t)st.x);
  (void)wr(h, MICKEY + OBJ_X + 2U, 2U, 0U);
  (void)wr(h, MICKEY + OBJ_Y, 2U, (uint32_t)st.y);
  (void)wr(h, MICKEY + OBJ_Y + 2U, 2U, 0U);
  (void)wr(h, MICKEY + OBJ_VY_LO, 2U, 0U);
  (void)wr(h, MICKEY + OBJ_VY_HI, 2U, 0U);
}

/* Keeps the power full exactly the way the game's own refresh routine leaves its state (the power word, the five HUD slot words and the HUD-upload flag), and only when it is not already full (no write per frame). */
static void keep_power(const SegaModHost *h) {
  uint32_t power = 0U, flags = 0U, i;
  if (rd(h, POWER, 2U, &power) != 0 || power >= POWER_MAX || power == 0U || rd(h, HUD_FLAGS, 1U, &flags) != 0) return;   /* a dead Mickey (0) is the game's own sequence: not touched */
  (void)wr(h, POWER, 2U, POWER_MAX);
  for (i = 0U; i < POWER_MAX; ++i) (void)wr(h, HUD_SLOTS + 2U * i, 2U, HUD_SLOT_FILLED);
  (void)wr(h, HUD_FLAGS, 1U, flags | 1U);
}

/* `input`: the pad sample. The chord toggles; while flying the game sees only Start. */
static void intercept(const SegaModHost *h) {
  uint32_t pad = 0U;
  if (h->input_get(1U, &pad) != 0) return;
  {
    const uint32_t chord = (pad & CHORD) == CHORD ? 1U : 0U;
    if (chord != 0U && st.chord_held == 0U) {
      uint32_t x = 0U, y = 0U;
      if (st.fly == 0U) {
        if (rd(h, MICKEY + OBJ_X, 2U, &x) == 0 && rd(h, MICKEY + OBJ_Y, 2U, &y) == 0) { st.x = clampi((int32_t)x); st.y = clampi((int32_t)y); st.fly = 1U; }   /* start where Mickey is */
      } else {
        st.fly = 0U;
      }
    }
    st.chord_held = chord;
  }
  st.pad = pad;
  if (st.fly != 0U) (void)h->input_set(1U, pad & PAD_START);
}

/* `post-input` (before the game's frame logic): move, and clear the velocity. */
static void move(const SegaModHost *h) {
  int32_t step;
  if (st.fly == 0U) return;
  step = (st.pad & PAD_A) != 0U ? SPEED_FAST : SPEED;
  {
    uint32_t cx = 0U, cy = 0U;
    int32_t sx, sy;
    if (rd(h, CAM_X, 2U, &cx) != 0 || rd(h, CAM_Y, 2U, &cy) != 0) { cx = 0U; cy = 0U; }
    sx = st.x - (int32_t)cx;
    sy = st.y - (int32_t)((cy + 512U) & 1023U) + 512;   /* the vertical scroll is a 10-bit value: use its signed form */
    if ((st.pad & PAD_RIGHT) != 0U && sx + step <= MARGIN_X_HI) st.x += step;
    if ((st.pad & PAD_LEFT) != 0U && sx - step >= MARGIN_X_LO) st.x -= step;
    if ((st.pad & PAD_DOWN) != 0U && sy + step <= MARGIN_Y_HI) st.y += step;
    if ((st.pad & PAD_UP) != 0U && sy - step >= MARGIN_Y_LO) st.y -= step;
  }
  st.x = clampi(st.x);
  st.y = clampi(st.y);
  place(h);
  keep_power(h);
}

/* `frame-end` (after the game's frame logic): assert the position again, so nothing the game's collision code did to it survives. */
static void settle(const SegaModHost *h) {
  if (st.fly == 0U) return;
  place(h);
  keep_power(h);
}

static int provider_init(void *state, const SegaModHost *host) {
  (void)state;
  return host->platform == SEGA_MOD_PLATFORM ? 0 : 1;
}

static void provider_phase(void *state, const SegaModHost *host) {
  (void)state;
  if (host->phase == SEGA_MOD_PHASE_RESET) { st.fly = st.chord_held = st.pad = 0U; st.x = st.y = 0; }
  else if (host->phase == SEGA_MOD_PHASE_INPUT) intercept(host);
  else if (host->phase == SEGA_MOD_PHASE_POST_INPUT) move(host);
  else if (host->phase == SEGA_MOD_PHASE_FRAME_END) settle(host);
}

static int provider_save(void *state, uint8_t *out, uint32_t cap, uint32_t *len) {
  const uint32_t values[4] = {st.fly, st.chord_held, (uint32_t)st.x, (uint32_t)st.y};
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
  if (values[0] > 1U || values[1] > 1U || (int32_t)values[2] < 0 || (int32_t)values[2] > POS_MAX || (int32_t)values[3] < 0 || (int32_t)values[3] > POS_MAX) return 1;
  st.fly = values[0];
  st.chord_held = values[1];
  st.x = (int32_t)values[2];
  st.y = (int32_t)values[3];
  st.pad = 0U;
  return 0;
}

static const SegaModProvider provider = {sizeof(SegaModProvider), SEGA_MOD_ABI_MAJOR, 0U, SEGA_MOD_PLATFORM, "castle-of-illusion-debug-fly", 1U, provider_init, provider_phase, NULL, provider_save, provider_load,
                                         {NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL}};

const SegaModProvider *segarecomp_mod_provider(void **state_out) {
  if (state_out != NULL) *state_out = &st;
  return &provider;
}
