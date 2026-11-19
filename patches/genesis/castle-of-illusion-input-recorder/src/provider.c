/* Castle of Illusion (Genesis, USA/Europe): INPUT RECORDER, one native ABI 2 provider (strict C11). A developer tool: it reads player 1's and player 2's controller once per guest frame (the `input` phase; `host.frame` is the guest frame number) and
 * logs one line `REC <frame> <pad1> <pad2>` (hexadecimal masks) whenever either changed, plus a first line at the first sample. It never writes anything to the game and never intercepts the pad, so a recorded session plays exactly as an unrecorded one.
 * The lines reach the viewer's standard error as `MOD_LOG {"line":"REC ..."}`; tools/record_to_pad_script.py turns them into guest-frame-keyed pad scripts. No commercial data is involved: a recording is a list of button masks and frame numbers. */
#include <segarecomp_mod_genesis.h>

static uint32_t last1 = 0xFFFFFFFFU, last2 = 0xFFFFFFFFU, dummy_state;

static void hex2(char *out, uint32_t *n, uint32_t v) {
  static const char digits[] = "0123456789abcdef";
  out[(*n)++] = digits[(v >> 4U) & 15U];
  out[(*n)++] = digits[v & 15U];
}

static void sample(const SegaModHost *h) {
  uint32_t p1 = 0U, p2 = 0U;
  char m[48];
  uint32_t n = 0U, i;
  static const char tag[] = "REC ";
  if (h->input_get(1U, &p1) != 0) return;
  if (h->input_get(2U, &p2) != 0) p2 = 0U;
  if (p1 == last1 && p2 == last2) return;
  last1 = p1;
  last2 = p2;
  for (i = 0U; i + 1U < sizeof tag; ++i) m[n++] = tag[i];
  { uint32_t k = 0U; char t[12]; uint64_t f = h->frame; do { t[k++] = (char)('0' + f % 10U); f /= 10U; } while (f != 0U); while (k != 0U) m[n++] = t[--k]; }
  m[n++] = ' ';
  hex2(m, &n, p1);
  m[n++] = ' ';
  hex2(m, &n, p2);
  h->log(m, n);
}

static int provider_init(void *state, const SegaModHost *host) {
  (void)state;
  return host->platform == SEGA_MOD_PLATFORM ? 0 : 1;
}

static void provider_phase(void *state, const SegaModHost *host) {
  (void)state;
  if (host->phase == SEGA_MOD_PHASE_RESET) { last1 = last2 = 0xFFFFFFFFU; }
  else if (host->phase == SEGA_MOD_PHASE_INPUT) sample(host);
}

static int provider_save(void *state, uint8_t *out, uint32_t cap, uint32_t *len) { (void)state; (void)out; (void)cap; *len = 0U; return 0; }
static int provider_load(void *state, const uint8_t *in, uint32_t len) { (void)state; (void)in; last1 = last2 = 0xFFFFFFFFU; return len == 0U ? 0 : 1; }

static const SegaModProvider provider = {sizeof(SegaModProvider), SEGA_MOD_ABI_MAJOR, 0U, SEGA_MOD_PLATFORM, "castle-of-illusion-input-recorder", 1U, provider_init, provider_phase, NULL, provider_save, provider_load,
                                         {NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL}};

const SegaModProvider *segarecomp_mod_provider(void **state_out) {
  if (state_out != NULL) *state_out = &dummy_state;
  return &provider;
}
