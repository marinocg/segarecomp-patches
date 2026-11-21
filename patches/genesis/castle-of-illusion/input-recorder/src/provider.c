/* Castle of Illusion (Genesis, USA/Europe): INPUT RECORDER, one native ABI 2 provider (strict C11). A developer tool: it reads player 1's and player 2's controller once per guest frame (the `input` phase; `host.frame` is the guest frame number) and
 * logs `START <frame>` at the first sample, `REC <frame> <pad1> <pad2>` (hexadecimal masks) whenever either pad changed, `TICK <frame>` every 300 frames (a heartbeat that bounds an unmarked end) and `LOAD <frame>` if a state is loaded (the recording is then invalid) and `END <frame>` when player 2 presses Start (the explicit end of the recording; nothing is logged after it). It never writes anything to the game and never intercepts the pad, so a recorded session plays exactly as an unrecorded one.
 * The lines reach the viewer's standard error as `MOD_LOG {"line":"REC ..."}`; tools/record_to_pad_script.py turns them into guest-frame-keyed pad scripts. No commercial data is involved: a recording is a list of button masks and frame numbers. */
#include <segarecomp_mod_genesis.h>

#define TICK_FRAMES 300U        /* a heartbeat every 5 s: the longest an unnoticed end can go unbounded */
#define P2_START 0x80U          /* player 2's Start is the explicit END marker (the 1-player game does not use it; the converter strips it from the scripts) */

static SegaModHost g_host;      /* a copy of the host table (its log function and the latest frame): the load callback receives no host */
static uint32_t have_host;
static uint32_t last1 = 0xFFFFFFFFU, last2 = 0xFFFFFFFFU, next_tick, started, ended, dummy_state;

static void hex2(char *out, uint32_t *n, uint32_t v) {
  static const char digits[] = "0123456789abcdef";
  out[(*n)++] = digits[(v >> 4U) & 15U];
  out[(*n)++] = digits[v & 15U];
}

/* "<tag> <frame>" and, for REC, " <pad1> <pad2>" */
static void emit(const SegaModHost *h, const char *tag, uint64_t frame, int pads, uint32_t p1, uint32_t p2) {
  char m[48];
  uint32_t n = 0U, k = 0U;
  char t[24];
  while (*tag != 0) m[n++] = *tag++;
  m[n++] = ' ';
  do { t[k++] = (char)('0' + frame % 10U); frame /= 10U; } while (frame != 0U);
  while (k != 0U) m[n++] = t[--k];
  if (pads) { m[n++] = ' '; hex2(m, &n, p1); m[n++] = ' '; hex2(m, &n, p2); }
  h->log(m, n);
}

static void sample(const SegaModHost *h) {
  uint32_t p1 = 0U, p2 = 0U;
  if (ended != 0U) return;
  if (h->input_get(1U, &p1) != 0) return;
  if (h->input_get(2U, &p2) != 0) p2 = 0U;
  if (started == 0U) { started = 1U; next_tick = (uint32_t)h->frame + TICK_FRAMES; emit(h, "START", h->frame, 0, 0U, 0U); }
  if ((last2 != 0xFFFFFFFFU && (last2 & P2_START) == 0U && (p2 & P2_START) != 0U) || (last2 == 0xFFFFFFFFU && (p2 & P2_START) != 0U)) {
    ended = 1U;                                                                          /* the explicit end: the frame at which the player pressed P2 Start; the recording stops here */
    emit(h, "END", h->frame, 0, 0U, 0U);
    return;
  }
  if (p1 != last1 || p2 != last2) { last1 = p1; last2 = p2; emit(h, "REC", h->frame, 1, p1, p2); }
  if ((uint32_t)h->frame >= next_tick) { next_tick = (uint32_t)h->frame + TICK_FRAMES; emit(h, "TICK", h->frame, 0, 0U, 0U); }
}

static int provider_init(void *state, const SegaModHost *host) {
  (void)state;
  g_host = *host; have_host = 1U;
  return host->platform == SEGA_MOD_PLATFORM ? 0 : 1;
}

static void provider_phase(void *state, const SegaModHost *host) {
  (void)state;
  g_host = *host; have_host = 1U;
  if (host->phase == SEGA_MOD_PHASE_RESET) { last1 = last2 = 0xFFFFFFFFU; started = ended = next_tick = 0U; }
  else if (host->phase == SEGA_MOD_PHASE_INPUT) sample(host);
}

static int provider_save(void *state, uint8_t *out, uint32_t cap, uint32_t *len) { (void)state; (void)out; (void)cap; *len = 0U; return 0; }
/* A state load (quick-load, rewind, restore) runs this callback: it explicitly INVALIDATES the recording by logging `LOAD <frame>` (the converter refuses any LOAD) and stops logging; timestamps and heartbeats alone cannot detect every restore. */
static int provider_load(void *state, const uint8_t *in, uint32_t len) {
  (void)state; (void)in;
  if (have_host != 0U && started != 0U && ended == 0U) emit(&g_host, "LOAD", g_host.frame, 0, 0U, 0U);
  ended = 1U;
  return len == 0U ? 0 : 1;
}

static const SegaModProvider provider = {sizeof(SegaModProvider), SEGA_MOD_ABI_MAJOR, 0U, SEGA_MOD_PLATFORM, "castle-of-illusion-input-recorder", 1U, provider_init, provider_phase, NULL, provider_save, provider_load,
                                         {NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL}};

const SegaModProvider *segarecomp_mod_provider(void **state_out) {
  if (state_out != NULL) *state_out = &dummy_state;
  return &provider;
}
