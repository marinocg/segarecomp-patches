#!/usr/bin/env python3
"""LOCAL real-image comparison of one ABI 1 (schema 2) widescreen package against its ABI 2 (schema 3) successor (SEG-152-T009/T010). Needs a product checkout (its CLI, SDL3 and the viewer test seams),
the legally held original image and a compiler; it is never run by public CI and it writes nothing into the repository. Output is AGGREGATE ONLY (counts and pass/fail classes): no frame, digest, trace line or RAM byte.

  abi_parity_compare.py --product-root DIR --cli BIN --sdl DIR --cc CC --rom IMAGE --abi1 PATCH_DIR --abi1-id ID --abi2 PROJECT_DIR --work DIR [--quick] [--only SCENARIO,...]

Both packages are built into the same real viewer program (the product's `segarecomp build`; the schema 2 one from the image its BPS produces, the schema 3 one from the original, exactly as the launcher does) and
played with the same scripted input and the same video settings. Every scenario compares, frame by frame, the producer's verdict of the two packages (frame identity, status, side, placement, accepted component mask,
refusal reason, authored status), the coverage accounting (offered / accepted / presented / rejected per component), the presented final picture byte for byte and the final guest work RAM. There is no tolerance,
no skipped frame and no normalisation. Falsification variants of the ABI 2 provider (a wrong frame lag, state cleared, state dropped on restore, a faulting callback) must FAIL the same comparison for named reasons.
"""
import argparse, concurrent.futures, importlib.util, json, os, pathlib, re, shutil, subprocess, sys, tempfile, threading, time

MODES = {"wide": ("32:9", None), "w219": ("21:9", None), "w169": ("16:9", None), "orig": ("32:9", "10:orig"), "43": ("32:9", "10:4:3")}
ENHANCED = "video.widescreen=enhanced_gameplay\nvideo.widescreen_side_style=raw\nvideo.scale=1\nvideo.aspect=0\nvideo.widescreen_ratio=%s\n"
VERDICT = ("status", "side", "shift", "acc", "reason", "auth")
SPECIAL_STAGE_DOWNS = 19   # level-select lines below the first one (Sonic 1 USA/Europe REV00)
ACCOUNT = ("offered", "accepted", "presented", "rejected")


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def level_pad(title_starts, run_from, until, jump_every=100):
    """Start presses to leave the title/menus, then run right with a jump every `jump_every` polls."""
    lines = ["0 -"]
    for f in title_starts:
        lines += [f"{f} S", f"{f + 2} -"]
    f = run_from
    lines.append(f"{f} R")
    while f < until:
        f += jump_every
        lines += [f"{f} RA", f"{f + 40} R"]
    return lines


def act_pad(act, jump, until=4800, downs=None):
    """The game's own level-select route to Green Hill act 2 or 3 (title press, the code U D L R, then Start+A, one Down per act, Start), then run right with a jump every `jump` polls."""
    pad = ["0 -", "300 S", "302 -"]
    f = 600
    for b in "UDLR":
        pad += [f"{f} {b}", f"{f + 3} -"]
        f += 8
    pad += [f"{f + 10} SA", f"{f + 14} -"]
    f += 40
    for _ in range(act - 1 if downs is None else downs):
        pad += [f"{f} D", f"{f + 3} -"]
        f += 10
    pad += [f"{f + 20} S", f"{f + 24} -"]
    g = f + 300
    pad.append(f"{g} R")
    while g < until:
        g += jump
        pad += [f"{g} RA", f"{g + 40} R"]
    return pad + [f"{until + 200} Q"]


def merge_pad(lines, extra, end):
    """The level pad with hotkey presses (`<poll> K|M|Y`) inserted in poll order and the run ended at poll `end` (the viewer applies the script in order)."""
    items = [(int(l.split()[0]), l) for l in lines if not l.endswith(" Q")]
    items = [(f, l) for f, l in items if f <= end] + [(int(l.split()[0]), l) for l in extra]
    items.sort(key=lambda t: t[0])
    return [l for _, l in items] + [f"{end} Q"]


def require_outside_repo(path, what):
    """Real-game material (intermediate images, captures, RAM snapshots, recordings) must never sit in the public repository checkout: `path` is resolved (symlinks included) and refused when it is the repository or inside it. Returns the resolved path."""
    top = pathlib.Path(__file__).resolve().parent.parent
    d = pathlib.Path(path).resolve()
    if d == top or top in d.parents:
        sys.exit(f"{what} must be a directory OUTSIDE the repository (real-game material is never committed): {d}")
    return d


def bmp_info(data):
    """Geometry and pixel rows of a 24/32-bit BMP as the viewer's capture seam writes it: (width, height, bytes per pixel, rows top to bottom as bytes). Raises ValueError for anything else."""
    if len(data) < 54 or data[:2] != b"BM":
        raise ValueError("not a BMP")
    off, w = int.from_bytes(data[10:14], "little"), int.from_bytes(data[18:22], "little", signed=True)
    h, bpp = int.from_bytes(data[22:26], "little", signed=True), int.from_bytes(data[28:30], "little")
    if bpp not in (24, 32) or w <= 0 or h == 0:
        raise ValueError("unsupported BMP")
    step, stride, rows = bpp // 8, ((w * (bpp // 8) + 3) & ~3), []
    for y in range(abs(h)):
        src = (abs(h) - 1 - y) if h > 0 else y
        raw = data[off + src * stride: off + src * stride + w * step]
        if len(raw) != w * step:
            raise ValueError("truncated BMP")
        rows.append(raw)
    return w, abs(h), step, rows


def bmp_diff(a, b):
    """Pixel-for-pixel comparison of two captures: {'geometry': bool, 'width', 'height', 'differing', 'bbox': (x0, y0, x1, y1) | None, 'mask': [(y, [x...])]}. Different geometry is a difference, never a pass."""
    wa, ha, sa, ra = bmp_info(a)
    wb, hb, sb, rb = bmp_info(b)
    if (wa, ha, sa) != (wb, hb, sb):
        return {"geometry": False, "width": wa, "height": ha, "differing": None, "bbox": None, "mask": []}
    count, x0, y0, x1, y1, mask = 0, wa, ha, -1, -1, []
    for y in range(ha):
        if ra[y] == rb[y]:
            continue
        xs = [x for x in range(wa) if ra[y][x * sa:(x + 1) * sa] != rb[y][x * sa:(x + 1) * sa]]
        count += len(xs)
        mask.append((y, xs))
        x0, x1, y0, y1 = min(x0, xs[0]), max(x1, xs[-1]), min(y0, y), max(y1, y)
    return {"geometry": True, "width": wa, "height": ha, "differing": count, "bbox": (x0, y0, x1, y1) if count else None, "mask": mask}


def content_rect(data):
    """The bounding box (x0, y0, x1, y1 exclusive) of the non-black pixels of a capture: the presented picture inside the viewer's black surround."""
    w, h, step, rows = bmp_info(data)
    x0, y0, x1, y1 = w, h, 0, 0
    for y, r in enumerate(rows):
        if not any(r):
            continue
        xs = [x for x in range(w) if any(r[x * step:(x + 1) * step])]
        x0, x1, y0, y1 = min(x0, xs[0]), max(x1, xs[-1] + 1), min(y0, y), y + 1
    return x0, y0, x1, y1


def write_png(path, width, height, rows_rgb):
    """A minimal PNG writer (zlib + struct), so a local diagnostic can be looked at: rows_rgb is a list of `width * 3` byte strings."""
    import struct, zlib
    def chunk(tag, body):
        return struct.pack(">I", len(body)) + tag + body + struct.pack(">I", zlib.crc32(tag + body) & 0xFFFFFFFF)
    raw = b"".join(b"\0" + r for r in rows_rgb)
    pathlib.Path(path).write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


def bmp_to_rgb_rows(data):
    w, h, step, rows = bmp_info(data)
    return w, h, [b"".join(bytes((r[x * step + 2], r[x * step + 1], r[x * step])) for x in range(w)) for r in rows]


def diff_visual(a, b, d):
    """A diagnostic picture: the ABI 1 frame dimmed, every differing pixel in saturated magenta (plus a one-pixel frame around the bounding rectangle)."""
    w, h, rows = bmp_to_rgb_rows(a)
    out = [bytearray(bytes(v // 3 for v in r)) for r in rows]
    for y, xs in d["mask"]:
        for x in xs:
            out[y][x * 3:x * 3 + 3] = b"\xff\x00\xff"
    if d["bbox"]:
        x0, y0, x1, y1 = d["bbox"]
        for x in range(max(0, x0 - 1), min(w, x1 + 2)):
            for y in (max(0, y0 - 1), min(h - 1, y1 + 1)):
                out[y][x * 3:x * 3 + 3] = b"\xff\xff\x00"
        for y in range(max(0, y0 - 1), min(h, y1 + 2)):
            for x in (max(0, x0 - 1), min(w - 1, x1 + 1)):
                out[y][x * 3:x * 3 + 3] = b"\xff\xff\x00"
    return w, h, [bytes(r) for r in out]



# ------------------------------------------------------------------ the special stage's wrapped planes, modelled independently of the provider and of the host (SEG-152-T009)
def sgstate_vdp(data):
    """(registers[24], vram, cram, vsram) of a quicksave (the documented SGSTATE container: a section table, section 3 = the VDP: 24 little-endian register words, 32 bytes of port/DMA state, VRAM, CRAM, VSRAM)."""
    import struct
    hb, sc = struct.unpack_from("<I", data, 20)[0], struct.unpack_from("<I", data, 28)[0]
    for i in range(sc):
        sid, _flags, off, length = struct.unpack_from("<HHII", data, hb + 12 * i)
        if sid == 3:
            sec = data[off:off + length]
            regs = list(struct.unpack_from("<24H", sec, 0))
            v0 = 48 + 32
            return regs, sec[v0:v0 + 65536], sec[v0 + 65536:v0 + 65536 + 128], sec[v0 + 65536 + 128:v0 + 65536 + 128 + 80]
    raise ValueError("no VDP section")


def ss_plane_model(regs, vram, cram, vsram, cvt):
    """The picture of the two scrolling planes alone (no sprites) for the special stage's configuration, from the VDP state: per-line horizontal scroll of both planes, full-screen vertical scroll, both planes 64 cells wide, tile
    selection with flips, palette lines, colour 0 transparent, plane priority. Returns a function (guest x, line) -> (r, g, b) valid for ANY x (the planes wrap), plus the sprite attribute table boxes [(x, y, w, h)]."""
    hbase = (regs[13] & 0x3F) << 10
    abase, bbase = (regs[2] & 0x38) << 10, (regs[4] & 7) << 13
    rows = 32 if ((regs[16] >> 4) & 3) == 0 else 64
    w16 = lambda b, o: (b[o & 0xFFFF] << 8) | b[(o + 1) & 0xFFFF]   # noqa: E731
    vs = [w16(vsram, 0) & 0x3FF, w16(vsram, 2) & 0x3FF]
    back = ((regs[7] >> 4) & 3) * 16 + (regs[7] & 15)
    def rgb(index):
        w = (cram[index * 2] << 8) | cram[index * 2 + 1]
        return cvt((w >> 1) & 7), cvt((w >> 5) & 7), cvt((w >> 9) & 7)   # the host maps a 3-bit channel v to floor(v * 255 / 7)
    def plane(base, which, x, line):
        hs = w16(vram, hbase + line * 4 + which * 2) & 0x3FF
        px, py = (x - hs) % 512, (line + vs[which]) % (rows * 8)
        word = w16(vram, base + ((py >> 3) * 64 + (px >> 3)) * 2)
        tx, ty = px & 7, py & 7
        if word & 0x800: tx = 7 - tx   # noqa: E701
        if word & 0x1000: ty = 7 - ty   # noqa: E701
        b = vram[((word & 0x7FF) * 32 + ty * 4 + (tx >> 1)) & 0xFFFF]
        idx = (b >> 4) if (tx & 1) == 0 else (b & 15)
        return (((word >> 13) & 3) * 16 + idx if idx else None), (word >> 15) & 1
    def at(x, line):
        a, b = plane(abase, 0, x, line), plane(bbase, 1, x, line)
        for layer, pri in ((a, 1), (b, 1), (a, 0), (b, 0)):
            if layer[0] is not None and layer[1] == pri:
                return rgb(layer[0])
        return rgb(back)
    sat = ((regs[5] & 0x7E) << 9)
    boxes, link, n = [], 0, 0
    while n < 80:
        o = (sat + link * 8) & 0xFFFF
        e = vram[o:o + 8]
        size = e[2] & 15
        boxes.append(((((e[6] << 8) | e[7]) & 0x1FF) - 128, (((e[0] << 8) | e[1]) & 0x3FF) - 128, (((size >> 2) & 3) + 1) * 8, ((size & 3) + 1) * 8))
        link = e[3] & 0x7F
        n += 1
        if link == 0:
            break
    return at, boxes


def selfbad_edit(text):
    """A deliberately wrong reconstruction (the derived tile ignores the type's own art-tile base): the self-test must catch it."""
    text = selfmaze_edit(text)
    a = "(uint16_t)(g_sstype[u].tile[q] + u16(ram, ot + 6U) - u16(ram, ou + 6U))"
    if a not in text:
        raise ValueError("selfbad edit target missing")
    return text.replace(a, "(uint16_t)g_sstype[u].tile[q]", 1)


def selfmaze_edit(text):
    """The test-only variant behind `maze_selftest` (never shipped): redraw every reconstructed piece of the blocks the GAME itself drew (its own window and cull), whole and unclipped, over the picture, and force the derivation path."""
    rep = [("if ((x >= 0 && x + w <= 320) || x + w <= -lpx || x >= 320 + right_px) continue;", "if (kept == 0 || x + w <= -lpx || x >= 320 + right_px) continue;"),
           ("        if (kept) sp->flags = GENESIS_VSPRITE_FLAG_HARDWARE_PIECE;", "        (void)kept;"),
           ("if (x < 0 && x + w > 0) {", "if (0) {"), ("else if (x < 320 && x + w > 320) {", "else if (0) {"),
           ("g_vset.budget_mode = GENESIS_VSPRITE_BUDGET_EXTENDED;", "g_vset.budget_mode = GENESIS_VSPRITE_BUDGET_LIMIT;"),   # the hardware's per-line sprite budget applies to the redraw too, as it did to the game's own sprites
           ("  ss_derive(ram);\n", "  for (unsigned st = 1U; st <= SS_TYPE_MAX; ++st) for (unsigned su = 1U; su < st; ++su) if (g_sstype[su].n != 0U && g_sstype[st].n != 0U && u16(ram, SS_ITEMS + su * 8U) == u16(ram, SS_ITEMS + st * 8U) && u16(ram, SS_ITEMS + su * 8U + 2U) == u16(ram, SS_ITEMS + st * 8U + 2U) && u16(ram, SS_ITEMS + su * 8U + 4U) == u16(ram, SS_ITEMS + st * 8U + 4U)) { g_sstype[st].n = 0U; break; }\n  ss_derive(ram);\n")]
    for a, b in rep:
        if a not in text:
            raise ValueError("selfmaze edit target missing: " + a)
        text = text.replace(a, b, 1)
    return text


_COVERAGE_STATS = r'''
static const SegaModHost *g_host;
static int dg_why, dg_fit, dg_learn, dg_nsat, dg_ncell, dg_elig, dg_edge, dg_cand;
static int dg_unl_t[0x50];
static void dg_put(char *b, int *n, int v) { char t[12]; int m = 0; unsigned u; if (v < 0) { b[(*n)++] = '-'; u = (unsigned)(-v); } else u = (unsigned)v; do { t[m++] = (char)('0' + u % 10U); u /= 10U; } while (u); while (m) b[(*n)++] = t[--m]; b[(*n)++] = ' '; }
static void dg_reset(void) { unsigned i; dg_why = 0; dg_fit = 2; dg_learn = 2; dg_nsat = dg_ncell = dg_elig = dg_edge = dg_cand = 0; for (i = 0U; i < 0x50U; ++i) dg_unl_t[i] = 0; }
static void dg_flush(void) {
  char b[256]; int n = 0; unsigned i;
  b[n++] = 'Z'; b[n++] = ' ';
  dg_put(b, &n, (int)g_host->frame); dg_put(b, &n, dg_fit); dg_put(b, &n, dg_learn); dg_put(b, &n, dg_nsat); dg_put(b, &n, dg_ncell); dg_put(b, &n, dg_elig); dg_put(b, &n, dg_edge); dg_put(b, &n, dg_cand); dg_put(b, &n, dg_why);
  for (i = 1U; i < 0x50U; ++i) if (dg_unl_t[i] != 0 && n < 235) dg_put(b, &n, 10000 + dg_unl_t[i] * 100 + (int)i);
  for (i = 1U; i < 0x50U; ++i) if (g_ssblank[i] != 0U && n < 235) dg_put(b, &n, 2000 + (int)i);
  g_host->log(b, (uint32_t)n);
}
'''


def coverage_edit(text):
    """The test-only logging variant behind `special_coverage` (never shipped): the production code plus one log line per special-stage frame saying whether the margin maze was fitted, learned and delivered, and why not."""
    rep = [("static int ss_fit(", _COVERAGE_STATS + "\nstatic int ss_fit("),
           ("  Sonic1Frame *f = &g_frame;\n", "  Sonic1Frame *f = &g_frame;\n  g_host = host;\n"),
           ("  if (ss_fit(ram, &s, &c, &dx0, &dy0) != 0) return;\n", "  dg_fit = 1;\n  if (ss_fit(ram, &s, &c, &dx0, &dy0) != 0) return;\n  dg_fit = 0;\n"),
           ("  nsat = ss_read_sat(v);\n", "  nsat = ss_read_sat(v);\n  dg_nsat = (int)nsat; dg_ncell = (int)ncell;\n"),
           ("  if (ss_learn(nsat, ncell) != 0) return;\n", "  dg_learn = 1;\n  if (ss_learn(nsat, ncell) != 0) return;\n  dg_learn = 0;\n"),
           ("        if (off * 4U > ncell + 3U) { ok = 0U; break; }", "        if (off * 4U > ncell + 3U) { dg_why |= 1; ok = 0U; break; }"),
           ("      } else if (g_sstype[t].n != g) {\n        ok = 0U;\n      } else {", "      } else if (g_sstype[t].n != g) {\n        ok = 0U; dg_why |= 2;\n      } else {"),
           ("g_sstype[t].tile[q] != (uint16_t)sp->tile) ok = 0U;\n        }", "g_sstype[t].tile[q] != (uint16_t)sp->tile) { ok = 0U; dg_why |= 4; }\n        }"),
           ("      if (t == 0U || t > SS_TYPE_MAX || g_sstype[t].n == 0U) continue;\n",
            "      if (t != 0U && t <= SS_TYPE_MAX && (cx < 16 || cx >= 304)) { ++dg_elig; if (g_sstype[t].n == 0U && g_ssblank[t] == 0U) ++dg_unl_t[t]; if (i == -24 || i == 39 || j == -24 || j == 39) ++dg_edge; }\n      if (t == 0U || t > SS_TYPE_MAX || g_sstype[t].n == 0U) continue;\n"),
           ("  if (ncand == 0U) return;\n", "  dg_cand = (int)ncand;\n  if (ncand == 0U) return;\n"),
           ("      if (v->side != 0U) ss_margin_maze(r, v, ram, left_px, margin_px);", "      if (v->side != 0U) { dg_reset(); ss_margin_maze(r, v, ram, left_px, margin_px); dg_flush(); }")]
    for a, b in rep:
        if a not in text:
            raise ValueError("coverage edit target missing: " + a)
        text = text.replace(a, b, 1)
    return text


def coverage_manifest(m):
    return m.replace("required = [", 'required = ["host.log", ', 1) if '"host.log"' not in m else m


_INVENTORY_STATS = r'''
static const SegaModHost *g_host;
static void iv_put(char *b, int *n, int v) { char t[12]; int m = 0; unsigned u; if (v < 0) { b[(*n)++] = '-'; u = (unsigned)(-v); } else u = (unsigned)v; do { t[m++] = (char)('0' + u % 10U); u /= 10U; } while (u); while (m) b[(*n)++] = t[--m]; b[(*n)++] = ' '; }
static void iv_dump(unsigned ncand, int lpx, int rpx) {
  char b[250]; int n = 0; unsigned q, per = 0U;
  b[n++] = 'I'; b[n++] = ' '; iv_put(b, &n, (int)g_host->frame); iv_put(b, &n, (int)ncand); iv_put(b, &n, lpx); iv_put(b, &n, rpx); g_host->log(b, (uint32_t)n);
  n = 0; b[n++] = 'J'; b[n++] = ' ';
  for (q = 0U; q < ncand; ++q) {
    const GenesisVirtualSprite *s = &g_cand[q].s;
    const int word = (s->layer == GENESIS_VSPRITE_LAYER_ABOVE_ALL ? 0x8000 : 0) | (s->palette << 13) | (s->v_flip << 12) | (s->h_flip << 11) | s->tile_index;
    iv_put(b, &n, s->x); iv_put(b, &n, s->y); iv_put(b, &n, s->width_cells * 10 + s->height_cells); iv_put(b, &n, word); iv_put(b, &n, (s->has_clip != 0U ? (s->clip_x < 0 ? 1 : 2) : 0) + 10 * (int)s->flags); b[n++] = ';';
    if (++per == 8U) { g_host->log(b, (uint32_t)n); n = 0; b[n++] = 'J'; b[n++] = ' '; per = 0U; }
  }
  if (per != 0U) g_host->log(b, (uint32_t)n);
}
'''


def inventory_edit(text):
    """The test-only logging variant behind `overflow_investigation` (never shipped): one `I` line and `J` lines per frame with the COMPLETE ordered piece inventory before the command limit is applied."""
    for a, b in (("static int ss_fit(", _INVENTORY_STATS + "\nstatic int ss_fit("), ("  Sonic1Frame *f = &g_frame;\n", "  Sonic1Frame *f = &g_frame;\n  g_host = host;\n"),
                 ("  if (ncand == 0U) return;\n", "  if (ncand > 0U) iv_dump(ncand, lpx, right_px);\n  if (ncand == 0U) return;\n")):
        if a not in text:
            raise ValueError("inventory edit target missing: " + a)
        text = text.replace(a, b, 1)
    return text


def parse_inventories(run):
    """The complete ordered piece inventories a logging run recorded: [{frame, n, lpx, rpx, pieces: [(x, y, w_cells, h_cells, tile_word, clip_code + 10 * hardware_flag)]}]."""
    out, cur = [], None
    for m in run["lines"].get("MOD_LOG", []):
        line = m.get("line", "")
        if line.startswith("I "):
            v = [int(x) for x in line[2:].split()]
            cur = {"frame": v[0], "n": v[1], "lpx": v[2], "rpx": v[3], "pieces": []}
            out.append(cur)
        elif line.startswith("J ") and cur is not None:
            for e in line[2:].split(";"):
                if e.strip():
                    x, y, sz, word, clip = [int(t) for t in e.split()]
                    cur["pieces"].append((x, y, sz // 10, sz % 10, word, clip))
    return [c for c in out if len(c["pieces"]) == c["n"]]


def compose_expected(base_bmp, pieces, vram, cram, lpx, rpx, skip_flagged=False, height=224):
    """The INDEPENDENT expected picture of a complete piece inventory: the maze-free picture with every piece composited from the frame's VRAM/CRAM exactly as a hardware sprite is drawn (column-major tiles, flips, palette line,
    colour 0 transparent, the clip of a straddling piece), in the game's order (first wins; a priority-bit piece above the others), margins only. With `skip_flagged` the pieces the host draws itself (HARDWARE_PIECE) are left to the base
    picture, which is how the production stacking works. Returns (rows, rect, bytes per pixel)."""
    _, _, st, rows = bmp_info(base_bmp)
    r0, r1, r2, r3 = content_rect(base_bmp)
    out = [bytearray(r) for r in rows]
    conv = lambda v: v * 255 // 7   # noqa: E731

    def pixel(piece, gx, gy):
        x, y, wc, hc, word, clipf = piece
        clip, cx, cy = clipf % 10, gx - x, gy - y
        if not (0 <= cx < wc * 8 and 0 <= cy < hc * 8) or (clip == 1 and not -lpx <= gx < 0) or (clip == 2 and not 320 <= gx < 320 + rpx):
            return None
        sx = wc * 8 - 1 - cx if (word >> 11) & 1 else cx
        sy = hc * 8 - 1 - cy if (word >> 12) & 1 else cy
        b = vram[(((word & 0x7FF) + (sx >> 3) * hc + (sy >> 3)) & 0x7FF) * 32 + (sy & 7) * 4 + ((sx & 7) >> 1)]
        idx = (b >> 4) if (sx & 1) == 0 else b & 15
        if idx == 0:
            return None
        c = ((word >> 13) & 3) * 16 + idx
        w = (cram[c * 2] << 8) | cram[c * 2 + 1]
        return conv((w >> 1) & 7), conv((w >> 5) & 7), conv((w >> 9) & 7)
    ps = [p for p in pieces if not (skip_flagged and p[5] // 10)]
    order = [p for p in ps if p[4] & 0x8000] + [p for p in ps if not p[4] & 0x8000]
    for line in range(height):
        for g in range(-lpx, 320 + rpx):
            for p in order:
                col = pixel(p, g, line)
                if col is not None:
                    X, Y = r0 + g + lpx, r1 + line
                    out[Y][X * st + 2], out[Y][X * st + 1], out[Y][X * st] = col
                    break
    return [bytes(r) for r in out], (r0, r1, r2, r3), st


def rows_diff(a, b, st, rect):
    """The set of presented pixels (x, y) at which two pictures (lists of rows) differ inside `rect`."""
    r0, r1, r2, r3 = rect
    return {(x, y) for y in range(r1, r3) if a[y] != b[y] for x in range(r0, r2) if a[y][x * st:(x + 1) * st] != b[y][x * st:(x + 1) * st]}


_OVERFLOW_RASTER = r'''
/* EXPERIMENT (test-only): the pixel of a piece exactly as a hardware sprite shows it (column-major tiles, flips, palette line, colour 0 transparent, clip). Returns 1 and the RGBA when opaque. */
static int ss_px(const SegaGenesisFrameView *v, const GenesisVirtualSprite *sp, int cx, int cy, uint8_t o[4]) {
  const unsigned w = (unsigned)sp->width_cells * 8U, h = (unsigned)sp->height_cells * 8U;
  const unsigned px = (unsigned)cx, py = (unsigned)cy;
  const unsigned sx = sp->h_flip != 0U ? w - 1U - px : px, sy = sp->v_flip != 0U ? h - 1U - py : py;
  const unsigned tile = ((unsigned)sp->tile_index + (sx >> 3) * (unsigned)sp->height_cells + (sy >> 3)) & 0x7FFU;
  const uint8_t b = v->vram[(tile * 32U + (sy & 7U) * 4U + ((sx & 7U) >> 1)) & 0xFFFFU];
  const unsigned idx = (sx & 1U) == 0U ? (unsigned)(b >> 4) : (unsigned)(b & 15U);
  const int gx = sp->x + cx, gy = sp->y + cy;
  if (idx == 0U) return 0;
  if (sp->has_clip != 0U && (gx < sp->clip_x || gx >= sp->clip_x + (int)sp->clip_w || gy < sp->clip_y || gy >= sp->clip_y + (int)sp->clip_h)) return 0;
  { const unsigned c = (unsigned)sp->palette * 16U + idx, word = ((unsigned)v->lines[0].cram[c * 2U] << 8) | v->lines[0].cram[c * 2U + 1U];
    o[0] = (uint8_t)(((word >> 1) & 7U) * 255U / 7U); o[1] = (uint8_t)(((word >> 5) & 7U) * 255U / 7U); o[2] = (uint8_t)(((word >> 9) & 7U) * 255U / 7U); o[3] = 255U; }
  return 1;
}
/* the listed pieces composited into ONE RGBA layer (the lowest piece first, so the first command wins as in the game), cropped to the presented extent [lo, hi) x [0, height): the host rejects a layer that is not wholly inside */
static uint8_t g_ovr[256 * 256 * 4];
static int ss_layer_group(const SegaGenesisRenderApi *r, const SegaGenesisFrameView *v, const unsigned *list, unsigned cnt, unsigned layer, int lo, int hi) {
  unsigned k;
  int bx0 = 1 << 20, by0 = 1 << 20, bx1 = -(1 << 20), by1 = -(1 << 20);
  for (k = 0U; k < cnt; ++k) {
    const GenesisVirtualSprite *sp = &g_cand[list[k]].s;
    int x0 = sp->x, y0 = sp->y, x1 = sp->x + sp->width_cells * 8, y1 = sp->y + sp->height_cells * 8;
    if (x0 < lo) x0 = lo;
    if (x1 > hi) x1 = hi;
    if (y0 < 0) y0 = 0;
    if (y1 > (int)v->height) y1 = (int)v->height;
    if (x1 <= x0 || y1 <= y0) continue;
    if (x0 < bx0) bx0 = x0;
    if (y0 < by0) by0 = y0;
    if (x1 > bx1) bx1 = x1;
    if (y1 > by1) by1 = y1;
  }
  if (bx1 > bx0 && by1 > by0) {
    const unsigned cw = (unsigned)(bx1 - bx0), ch = (unsigned)(by1 - by0);
    if (cw > 256U || ch > 256U) return 1;   /* fail closed: one layer holds at most 256 x 256 */
    for (unsigned z = 0U; z < cw * ch * 4U; ++z) g_ovr[z] = 0U;
    for (k = cnt; k > 0U; --k) {
      const GenesisVirtualSprite *sp = &g_cand[list[k - 1U]].s;
      for (int cy = by0; cy < by1; ++cy) for (int cx = bx0; cx < bx1; ++cx) {
        uint8_t o[4];
        if (cx < sp->x || cx >= sp->x + sp->width_cells * 8 || cy < sp->y || cy >= sp->y + sp->height_cells * 8 || cx < lo || cx >= hi) continue;
        if (ss_px(v, sp, cx - sp->x, cy - sp->y, o)) { uint8_t *d = &g_ovr[((unsigned)(cy - by0) * cw + (unsigned)(cx - bx0)) * 4U]; d[0] = o[0]; d[1] = o[1]; d[2] = o[2]; d[3] = o[3]; }
      }
    }
    if (r->overlay_layer_bitmap(layer, 0U, 1U, bx0 - lo, by0, cw, ch, 0U) != 0) return 1;   /* presentation coordinates: picture x - lo */
    if (r->overlay_target(layer) != 0) return 1;
    if (r->overlay_bitmap(0, 0, cw, ch, g_ovr, cw * 4U) != 0) return 1;
  }
  return 0;
}
'''


def overflow_edit(text, mode="one-layer"):
    """EXPERIMENT (never shipped): the pieces the production rule drops over the host's 64-command limit are composited into RGBA overlay layers instead (`one-layer`: one layer for all of them; `per-side`: one layer for the left and one
    for the right margin) and the remaining pieces stay sprites in the game's order. A layer that would exceed 256 x 256 fails closed (the maze is then not submitted for that frame)."""
    start = "  /* at most GENESIS_VSPRITE_MAX commands"
    end = "  for (n = 0U; n < ncand; ++n) g_vset.sprites[n] = g_cand[n].s;\n"
    marker = "/* Submits the maze blocks that reach into the margins"
    if start not in text or end not in text or marker not in text or mode not in ("one-layer", "per-side"):
        raise ValueError("overflow edit targets missing")
    a, b = text.index(start), text.index(end) + len(end)
    if mode == "one-layer":
        call = "    if (nd != 0U && ss_layer_group(r, v, dropped, nd, 1U, -lpx, 320 + right_px) != 0) return;   /* fail closed */\n"
    else:
        call = ("    { static unsigned dl[512], dr[512]; unsigned nl = 0U, nr = 0U, kk;\n"
                "      for (kk = 0U; kk < nd; ++kk) { const GenesisVirtualSprite *dp = &g_cand[dropped[kk]].s; if (dp->x + dp->width_cells * 4 < 160) dl[nl++] = dropped[kk]; else dr[nr++] = dropped[kk]; }\n"
                "      if (nl != 0U && ss_layer_group(r, v, dl, nl, 1U, -lpx, 320 + right_px) != 0) return;\n"
                "      if (nr != 0U && ss_layer_group(r, v, dr, nr, 2U, -lpx, 320 + right_px) != 0) return; }\n")
    new = ("  {\n    static unsigned alive[512], dropped[512];\n    unsigned na = ncand, nd = 0U, qq;\n    for (qq = 0U; qq < ncand; ++qq) alive[qq] = 1U;\n"
           "    while (na > GENESIS_VSPRITE_MAX) { unsigned far = 0U; int have = 0; for (qq = 0U; qq < ncand; ++qq) if (alive[qq] != 0U) { if (have == 0 || g_cand[qq].dist >= g_cand[far].dist) { far = qq; have = 1; } } alive[far] = 0U; --na; }\n"
           "    for (qq = 0U; qq < ncand; ++qq) if (alive[qq] == 0U) dropped[nd++] = qq;\n" + call +
           "    for (n = 0U, qq = 0U; qq < ncand; ++qq) if (alive[qq] != 0U) g_vset.sprites[n++] = g_cand[qq].s;\n  }\n")
    text = text[:a] + new + text[b:]
    return text.replace(marker, _OVERFLOW_RASTER + "\n" + marker, 1)


def scene_totals(scenes):
    """The coverage accounting of a run as per-component totals over EVERY scene of the report. A schema 2 package has one unnamed scene ('*'); a schema 3 package attributes frames to its declared scenes
    ('level', 'special-stage') and to '*' for the frames outside them (an attract demo), so a positional read of one scene would compare different frames. Summing every scene is strictly stronger than
    reading one: a counted frame outside the first scene can no longer be missed. `declared` is true when any scene declares the component."""
    out = {}
    for sc in scenes:
        for comp, d in sc["components"].items():
            t = out.setdefault(comp, {})
            for k, v in d.items():
                t[k] = (bool(t.get(k)) or v) if isinstance(v, bool) else t.get(k, 0) + v
    return out

def validate_run(run, label, end_poll, restore=None, mod=False, slack=(0, 12)):
    """Everything that must hold for a run to count as evidence at all; returns the list of problems (empty = a complete, healthy run). `end_poll`: the pad's final poll (the run is ended by it).
    `restore`: None for an uninterrupted run, 'load' (one forward discontinuity) or 'rewind' (one backward discontinuity with repeated frame numbers)."""
    bad = []
    if run.get("rc") != 0:
        bad.append(f"{label}: exit status {run.get('rc')}")
    if run.get("outcome") != "window_closed":
        bad.append(f"{label}: terminal outcome {run.get('outcome')!r}, expected the scripted end (window_closed)")
    if run.get("replay") and not str((run.get("session") or {}).get("outcome", "")).startswith("complete"):
        bad.append(f"{label}: the recorded session did not replay to its end ({run.get('session')})")
    ev = run.get("events") or []
    if not ev:
        bad.append(f"{label}: no trace at all")
        return bad
    frames = [e[0] for e in ev]
    jumps = [i for i in range(1, len(frames)) if frames[i] != frames[i - 1] + 1]
    if restore is None:
        if jumps:
            bad.append(f"{label}: frame numbers are not consecutive (discontinuities at {[(frames[i - 1], frames[i]) for i in jumps][:3]})")
        if frames[0] > 1 or not (end_poll + slack[0] <= frames[-1] <= end_poll + slack[1]):
            bad.append(f"{label}: frame progression {frames[0]}..{frames[-1]} does not cover the scripted run to poll {end_poll}")
    else:
        fwd = [i for i in jumps if frames[i] > frames[i - 1] + 1]
        back = [i for i in jumps if frames[i] <= frames[i - 1]]
        if len(jumps) != 1 or (restore == "load" and len(fwd) != 1) or (restore == "rewind" and (len(back) != 1 or len(frames) == len(set(frames)))):
            bad.append(f"{label}: expected exactly one {restore} discontinuity, got {[(frames[i - 1], frames[i]) for i in jumps][:3]}")
    if (run.get("native") or {}).get("frames", 0) <= 0:
        bad.append(f"{label}: no native summary (the provider never ran)")
    cov = run.get("coverage")
    if not cov or any(c not in cov for c in ("scenery", "hud")) or any(not isinstance(cov[c], dict) or any(k not in cov[c] for k in ACCOUNT) for c in ("scenery", "hud")):
        bad.append(f"{label}: coverage information missing or incomplete")
    try:
        w, h, _, _ = bmp_info(run.get("bmp") or b"")
        if w < 64 or h < 64:
            bad.append(f"{label}: capture too small ({w}x{h})")
    except ValueError as e:
        bad.append(f"{label}: no valid final capture ({e})")
    if len(run.get("ram") or b"") != 65536:
        bad.append(f"{label}: guest RAM capture is {len(run.get('ram') or b'')} bytes, expected 65536")
    if mod and (run.get("summary") or {}).get("faulted") is None:
        bad.append(f"{label}: no mod summary")
    return bad


def compare_checkpoint(ra, rb, want, label, window=3, restore=None):
    """A visual checkpoint: both runs must end on the SAME guest frame, that frame must be the requested one (within `window` frames of the scripted end), and the two captures must be pixel-identical in geometry and content.
    Returns (problems, diff)."""
    bad = validate_run(ra, label + " [abi1]", want, restore=restore, slack=(0, window)) + validate_run(rb, label + " [abi2]", want, restore=restore, slack=(0, window), mod=True)
    d = None
    if ra.get("events") and rb.get("events"):
        fa, fb = ra["events"][-1][0], rb["events"][-1][0]
        if fa != fb:
            bad.append(f"{label}: the runs ended on different guest frames ({fa} / {fb})")
    if not bad:
        try:
            d = bmp_diff(ra["bmp"], rb["bmp"])
        except ValueError as e:
            bad.append(f"{label}: capture unreadable ({e})")
        else:
            if not d["geometry"]:
                bad.append(f"{label}: the captures differ in geometry")
            elif d["differing"] != 0:
                bad.append(f"{label}: {d['differing']} pixels differ (bounding rectangle {d['bbox']})")
    return bad, d


class Cmp:
    def __init__(self, a):
        self.work = require_outside_repo(a.work, "--work")   # it holds the intermediate ROM images, captures and RAM snapshots: checked before anything is written
        self.a = a
        self.root = pathlib.Path(a.product_root).resolve()
        sys.path.insert(0, str(self.root / "tests"))
        import viewer_mod_support as vms
        self.vms = vms
        self.segapatch = load(self.root / "tools/segapatch.py", "segapatch")
        self.work.mkdir(parents=True, exist_ok=True)
        self.h = vms.Harness(a.cli, a.cc, self.root, a.sdl, self.work)
        self.rom = pathlib.Path(a.rom)
        self.image = self.rom.read_bytes()
        self.image_sha = vms.sha(self.image)
        self.failures = []
        self.report = {}
        self.progs = {}
        self.diag = None
        self.cp_runs = {}
        self.recs = {}
        self.rec_lock = threading.Lock()
        (self.work / "rec.cfg").write_text(ENHANCED % "32:9")

    # ------------------------------------------------------------------ results
    def check(self, cond, what):
        if not cond:
            self.failures.append(what)
            print("FAIL:", what, flush=True)
        return cond

    # ------------------------------------------------------------------ builds
    def abi1_program(self):
        a, src = self.a, pathlib.Path(self.a.abi1) / "source"
        files = [("manifest.json", (src / f"{a.abi1_id}.manifest.json").read_bytes()), ("game.bps", (src / f"{a.abi1_id}.bps").read_bytes())]
        if (src / "provider.c").is_file():
            files.append(("provider.c", (src / "provider.c").read_bytes()))
        pkg = self.work / "abi1.segapatch"
        self.segapatch.write_zip(pkg, files)
        patched = self.work / "abi1-effective.rom"
        patched.write_bytes(self.segapatch.bps_apply(files[1][1], self.image))
        ident = json.loads(self.h.run_cli("patch", "inspect", pkg).stdout)["package_identity"]
        stamp = self.work / "abi1" / ".identity"
        if a.reuse and (self.work / "abi1" / "game").is_file() and stamp.is_file() and stamp.read_text() == ident:
            self.progs["abi1"] = (self.work / "abi1", ident)
            self.report["abi1_package_sha256"] = self.vms.sha(pkg.read_bytes())
            return
        r = self.h.run_cli("build", "--rom", patched, "--output", self.work / "abi1", "--cc", a.cc, "--runtime-dir", self.root / "platforms/genesis", "--optimize", "0", "--runtime-optimize", "1",
                           "--sdl3-include", pathlib.Path(a.sdl) / "include", "--sdl3-lib", pathlib.Path(a.sdl) / "lib", "--test-frame-seam", "1", "--patch-package", pkg, "--patch-identity", ident)
        self.check(r.returncode == 0, f"ABI 1 program builds: {r.stdout[-200:]}{r.stderr[-200:]}")
        if r.returncode == 0:
            stamp.write_text(ident)
        self.progs["abi1"] = (self.work / "abi1", ident)
        self.report["abi1_package_sha256"] = self.vms.sha(pkg.read_bytes())

    def abi2_program(self, name, provider_edit=None, manifest_edit=None):
        d = self.work / (name + "-src")
        if d.exists():
            shutil.rmtree(d)
        shutil.copytree(self.a.abi2, d, ignore=shutil.ignore_patterns("README.md", "package.json", "tests"))
        if provider_edit:
            p = d / "src/provider.c"
            before = p.read_text()
            after = provider_edit(before)
            self.check(after != before, f"{name}: the provider edit applied")
            p.write_text(after)
        if manifest_edit:
            m = d / "mod.toml"
            m.write_text(manifest_edit(m.read_text()))
        out = self.work / (name + ".segapatch")
        r = self.h.run_cli("mod", "pack", d, "--out", out)
        try:
            doc = json.loads(r.stdout)
        except ValueError:
            doc = {}
        self.check(r.returncode == 0 and doc.get("ok"), f"pack {name}: {r.stdout[:300]}")
        stamp = self.work / name / ".identity"
        if self.a.reuse and (self.work / name / "game").is_file() and stamp.is_file() and stamp.read_text() == str(doc.get("package_identity")):
            pass   # the same package identity was built into this program before: reuse it (the runtime and the SDK are those of the same product checkout)
        else:
            b = self.h.build(self.rom, self.work / name, out, doc.get("package_identity"), native=True)
            self.check(b.returncode == 0, f"{name} builds: {b.stdout[-200:]}{b.stderr[-200:]}")
            if b.returncode == 0:
                stamp.write_text(str(doc.get("package_identity")))
        self.progs[name] = (self.work / name, doc.get("package_identity"))
        if name == "abi2":
            self.report["abi2_package_sha256"] = self.vms.sha(out.read_bytes())
            self.report["abi2_package_identity"] = doc.get("package_identity")
        return doc

    def run_program(self, prog, name, pad, save, ident, env, budget, timeout=1500, session=None):
        """The product harness' `play` with a longer wall-clock bound (a real image runs thousands of frames): the same environment, the same tags, an explicit instruction budget."""
        frame, ram = self.work / (name + ".bmp"), self.work / (name + ".ram")
        for p in (frame, ram):
            p.unlink(missing_ok=True)
        extras = dict(SEGARECOMP_VIEWER_FINAL_FRAME=str(frame), SEGARECOMP_VIEWER_FINAL_RAM=str(ram))
        pad_file = self.work / (name + ".pad")
        pad_file.write_text(pad)
        extras["SEGARECOMP_VIEWER_PAD_SCRIPT"] = str(pad_file)
        home = self.work / "homes" / name   # one private HOME per run: the viewer keeps the player's per-variant choices (an Original-mode run of an earlier scenario must never leak into a later run)
        (home / "config").mkdir(parents=True, exist_ok=True)
        (home / "data").mkdir(parents=True, exist_ok=True)
        extras.update(HOME=str(home), XDG_CONFIG_HOME=str(home / "config"), XDG_DATA_HOME=str(home / "data"))
        if save is not None:
            pathlib.Path(save).mkdir(parents=True, exist_ok=True)
            extras.update(SEGARECOMP_SAVE_DIR=str(save), SEGARECOMP_ROM_SHA256=self.image_sha, SEGARECOMP_REWIND_INTERVAL_MS="100", SEGARECOMP_REWIND="on", SEGARECOMP_SAVE_VARIANT=ident)
        if session is not None:   # {"record": file} or {"replay": file}: frame-exact input (the viewer's session seam, identity from the original image)
            extras["SEGARECOMP_ROM_SHA256"] = self.image_sha
            extras.update({"SEGARECOMP_RECORD" if "record" in session else "SEGARECOMP_REPLAY": str(session.get("record") or session.get("replay"))})
        extras.update(env)
        run = subprocess.run([str(pathlib.Path(prog) / "game"), "--instruction-budget", str(budget)], text=True, capture_output=True, env=self.h.env(**extras), timeout=timeout, cwd=self.work)
        lines = {}
        for line in run.stderr.splitlines():
            tag, _, rest = line.partition(" ")
            if tag in self.vms.TAGS or tag == "SESSION_SUMMARY":
                try:
                    lines.setdefault(tag, []).append(json.loads(rest))
                except ValueError:
                    lines.setdefault(tag, []).append({"raw": rest})
        return run, lines, frame, ram

    def record(self, name, pad):
        """Records the scripted pad with the ABI 1 program through the viewer's session seam and returns (file, recorded guest frames). The pad is keyed by host poll and can land a frame or two differently in two build routes
        (the guests then diverge); a RECORDED session replays the SAME input at the SAME guest frame in both programs. Cached by name."""
        with self.rec_lock:
            return self._record(name, pad)

    def _record(self, name, pad):
        if name in self.recs:
            return self.recs[name]
        path = self.work / (name + ".sgs")
        path.unlink(missing_ok=True)
        prog, ident = self.progs["abi1"]
        run, lines, _, _ = self.run_program(prog, "rec-" + name, "\n".join(pad) + "\n", None, ident, {"SEGARECOMP_VIEWER_SETTINGS": str(self.work / "rec.cfg")}, 4_000_000_000, session={"record": path})
        sess = (lines.get("SESSION_SUMMARY") or [{}])[0]
        self.check(run.returncode == 0 and sess.get("outcome") == "complete" and path.is_file() and sess.get("frame", 0) > 0, f"recording {name}: {sess} exit {run.returncode}")
        self.recs[name] = (str(path), int(sess.get("frame", 0)))
        return self.recs[name]

    # ------------------------------------------------------------------ one run
    def play(self, key, name, mode, pad, schedule=None, save=None, budget=4_000_000_000, extra=None, replay=None, hot=None):
        """`replay` = (session file, recorded frames): the recorded input is injected frame-exactly (the scripted `pad` is then only `0 -`); the run ends with the recording."""
        prog, ident = self.progs[key]
        aspect, mode_schedule = MODES[mode]
        cfg = self.work / (name + ".cfg")
        cfg.write_text(ENHANCED % aspect)
        report = self.work / (name + ".coverage.json")
        report.unlink(missing_ok=True)
        env = {"SEGARECOMP_VIEWER_SETTINGS": str(cfg), "SEGARECOMP_VIEWER_FINAL_FRAME_NO_NOTICES": "1", "SEGARECOMP_VIEWER_TEST_TRACE": "1", "SEGARECOMP_COVERAGE_REPORT": str(report)}
        if (save is not None or replay is not None) and mode_schedule is None:   # a run with a game identity (saves, a session) takes its presentation from the player's per-variant settings (default: Original), not from the settings file: set the aspect through the real settings path at frame 1
            mode_schedule = f"1:{aspect}"
        sched = ",".join(x for x in (mode_schedule, schedule) if x)
        if sched:
            env["SEGARECOMP_VIEWER_TEST_VIDEO_AT"] = sched
        env.update(extra or {})
        t0 = time.time()
        if replay is not None:
            pad = ["0 -"] + list(hot or [])   # hotkeys (a quicksave) may ride on a replayed session; the input itself is the recording
        run, lines, frame, ram = self.run_program(prog, name, "\n".join(pad) + "\n", save, ident, env, budget, session={"replay": replay[0]} if replay is not None else None)
        wall = time.time() - t0
        trace = lines.get("VIEWER_TEST_TRACE", [])
        cov = json.loads(report.read_text()) if report.is_file() else None
        scene = scene_totals(cov["scenes"]) if cov and cov.get("scenes") else None
        nat = (lines.get("VIEWER_NATIVE_SUMMARY") or [{}])[0]
        return {"bmp": frame.read_bytes() if frame.is_file() else b"", "ram": ram.read_bytes() if ram.is_file() else b"", "events": [tuple(t[k] for k in ("f",) + VERDICT) for t in trace],
                "trace": {t["f"]: t for t in trace}, "coverage": scene, "summary": (lines.get("MOD_SUMMARY") or [{}])[0], "native": nat, "lines": lines, "wall": wall, "state": lines.get("VIEWER_STATE", []),
                "outcome": (lines.get("VIEWER_SUMMARY") or [{}])[0].get("outcome"), "stderr": run.stderr[-300:], "rc": run.returncode, "end_poll": replay[1] if replay is not None else (int(pad[-1].split()[0]) if pad else 0),
                "replay": replay is not None, "session": (lines.get("SESSION_SUMMARY") or [None])[0]}

    # ------------------------------------------------------------------ comparison
    def checkpoint(self, name, frame, mode, pad, extras=(), schedule=None, save=None, restore=None, gameplay=False):
        """One visual checkpoint: ABI 1 and ABI 2 run the same input to the same end, must end on the SAME guest frame and capture pixel-identical pictures. `gameplay`: the input is a recorded PREFIX session of the scripted pad
        (frame-exact in both programs); otherwise the pad itself is the input (idle scenes: no input edge is sensitive to the build route). Saves the local diagnostics when --diag is set."""
        if gameplay:
            rec = self.record(f"prefix-{frame}", merge_pad(pad, list(extras), frame))
            end_pad, want, replay = ["0 -"], rec[1], rec
        else:
            end_pad, want, replay = merge_pad(pad, list(extras), frame), frame, None
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            fa = pool.submit(self.play, "abi1", f"cp-{name}-a1", mode, end_pad, schedule=schedule, save=(self.work / f"{save}-abi1") if save else None, replay=replay)
            fb = pool.submit(self.play, "abi2", f"cp-{name}-a2", mode, end_pad, schedule=schedule, save=(self.work / f"{save}-abi2") if save else None, replay=replay)
            ra, rb = fa.result(), fb.result()
        bad, d = compare_checkpoint(ra, rb, want, name, restore=restore)
        for b in bad:
            self.check(False, b)
        ram = rb["ram"]
        info = {"name": name, "mode": mode, "requested_frame": frame, "input": "recorded session replay" if gameplay else "scripted pad (no gameplay input)", "guest_frame": ra["events"][-1][0] if ra["events"] else None, "zone_act": [ram[0xFE10], ram[0xFE11]] if len(ram) == 65536 else None,
                "game_mode": ram[0xF600] if len(ram) == 65536 else None, "verdict_abi1": list(ra["events"][-1][1:]) if ra["events"] else None, "verdict_abi2": list(rb["events"][-1][1:]) if rb["events"] else None,
                "differing_pixels": d["differing"] if d else None, "bbox": d["bbox"] if d else None, "geometry": [d["width"], d["height"]] if d else None, "ok": not bad}
        if self.diag is not None and ra["bmp"] and rb["bmp"]:
            try:
                for tag, data in (("abi1", ra["bmp"]), ("abi2", rb["bmp"])):
                    w, h, rows = bmp_to_rgb_rows(data)
                    write_png(self.diag / f"{name}.{tag}.png", w, h, rows)
                if d and d["geometry"]:
                    w, h, rows = diff_visual(ra["bmp"], rb["bmp"], d)
                    write_png(self.diag / f"{name}.diff.png", w, h, rows)
            except ValueError:
                pass
        self.report.setdefault("checkpoints", []).append(info)
        self.cp_runs[name] = (ra, rb)
        return info


    @staticmethod
    def verdicts(run):
        return {f: tuple(t[k] for k in VERDICT) for f, t in run["trace"].items()}

    def compare(self, key, a, b):
        """The equality verdict of two runs: per-frame verdicts, coverage accounting, final picture, final RAM. Returns (names of the mechanisms that differ, counts)."""
        va, vb = self.verdicts(a), self.verdicts(b)
        names = set()
        if a["events"] != b["events"]:   # every ordered occurrence (repeated frame numbers after a rewind included), not only the last one of a frame number
            names.add("ordered-occurrences")
        diff = [f for f in sorted(set(va) | set(vb)) if va.get(f) != vb.get(f)]
        if sorted(va) != sorted(vb):
            names.add("frame-identity")
        for f in diff:
            x, y = va.get(f), vb.get(f)
            if x is None or y is None:
                continue
            for i, label in enumerate(("status", "side", "placement", "accepted-components", "reason", "authored")):
                if x[i] != y[i]:
                    names.add(label)
        ca, cb = a["coverage"], b["coverage"]
        if ca is None or cb is None or any(c not in ca or c not in cb or any(k not in ca[c] or k not in cb[c] for k in ACCOUNT) for c in ("scenery", "hud")) or any({k: ca[c][k] for k in ACCOUNT} != {k: cb[c][k] for k in ACCOUNT} for c in ("scenery", "hud")):   # declared/covered/requested depend on a geometry declaration the schema 2 package cannot carry (SEG-152-T008)
            names.add("coverage-accounting")
        if a["bmp"] != b["bmp"]:
            names.add("picture")
        if a["ram"] != b["ram"]:
            names.add("guest-ram")
        acc = lambda r: sum(1 for t in r["trace"].values() if t["acc"] != 0)  # noqa: E731
        counts = {"frames": len(va), "frames_differing": len(diff), "accepted_a1": acc(a), "accepted_a2": acc(b),
                  "scenery_frames_a1": sum(1 for t in a["trace"].values() if t["acc"] & 2), "scenery_frames_a2": sum(1 for t in b["trace"].values() if t["acc"] & 2),
                  "hud_frames_a1": sum(1 for t in a["trace"].values() if t["acc"] & 1), "hud_frames_a2": sum(1 for t in b["trace"].values() if t["acc"] & 1),
                  "authored_a1": sum(1 for t in a["trace"].values() if t["auth"]), "authored_a2": sum(1 for t in b["trace"].values() if t["auth"])}
        return names, counts

    def equal(self, key, a, b, minimum=30, restore=None, need=("scenery", "hud")):
        names, counts = self.compare(key, a, b)
        problems = validate_run(a, key + " [abi1]", a["end_poll"], restore=restore) + validate_run(b, key + " [abi2]", b["end_poll"], restore=restore, mod=True)
        for p in problems:
            self.check(False, p)
        names = names | ({"incomplete-run"} if problems else set())
        if not key.endswith("orig"):   # a scenario that never exercised the components it compares proves nothing (the presentation setting can silently be Original): scenery and HUD must have been offered
            for what, n in (("scenery", counts["scenery_frames_a1"]), ("hud", counts["hud_frames_a1"])):
                if n == 0 and what in need:
                    self.check(False, f"{key}: the ABI 1 run never presented {what} (the scenario does not exercise it)")
                    names = names | {"component-not-exercised"}
        self.report.setdefault("scenarios", {})[key] = {"differences": sorted(names), **counts}
        ok = self.check(not names and counts["frames"] >= minimum, f"{key}: ABI 2 == ABI 1 in every mechanism ({sorted(names)}, {counts})")
        healthy = self.check(b["summary"].get("faulted") is False, f"{key}: the ABI 2 provider is healthy (a refusal is not a fault)")
        return ok and healthy


    def maze_frames(self, a, b):
        """The frames in which ABI 2 delivered the special-stage margin maze (its accepted mask carries one more bit than ABI 1's); a difference of any other kind in any frame is returned as `bad`."""
        extra, bad = [], []
        for f in sorted(set(a["trace"]) | set(b["trace"])):
            x, y = a["trace"].get(f), b["trace"].get(f)
            if x is None or y is None:
                bad.append(f)
                continue
            if tuple(x[k] for k in VERDICT) == tuple(y[k] for k in VERDICT):
                continue
            if all(x[k] == y[k] for k in VERDICT if k != "acc") and x["acc"] & 1 == 0 and y["acc"] == x["acc"] | 1:
                extra.append(f)
            else:
                bad.append(f)
        return extra, bad

    def equal_maze(self, key, a, b, mode, minimum=100):
        """The special stage with the margin maze (SEG-152-T009, operator-approved difference: the maze blocks the game culls at the picture edges are drawn into the margins). ABI 2 must equal ABI 1 in EVERY mechanism
        except exactly this: in a frame that delivers the maze only the accepted mask gains one bit (every other verdict field equal), the final picture, the coverage accounting of scenery and HUD and the final RAM
        stay equal, and where no margin is presented (Original, exact 4:3) there is no difference at all."""
        names, counts = self.compare(key, a, b)
        extra, bad = self.maze_frames(a, b)
        margin = mode not in ("orig", "43")
        if bad or (margin and not extra) or (not margin and extra):
            names = names | {"maze-verdict"}
        else:
            names = names - {"accepted-components", "ordered-occurrences"}
        problems = validate_run(a, key + " [abi1]", a["end_poll"]) + validate_run(b, key + " [abi2]", b["end_poll"], mod=True)
        for pr in problems:
            self.check(False, pr)
        names = names | ({"incomplete-run"} if problems else set())
        counts = dict(counts, maze_frames=len(extra), other_differing_frames=len(bad))
        self.report.setdefault("scenarios", {})[key] = {"differences": sorted(names), **counts}
        ok = self.check(not names and counts["frames"] >= minimum, f"{key}: ABI 2 == ABI 1 except the margin maze ({sorted(names)}, {counts})")
        healthy = self.check(b["summary"].get("faulted") is False, f"{key}: the ABI 2 provider is healthy")
        return ok and healthy

    def maze_checkpoint(self, name, poll, mode, pad):
        """One picture of a special-stage frame that delivers the margin maze: every pixel of the native picture equals ABI 1's, and (where a margin is presented) the margins differ; Original / exact 4:3 are fully equal."""
        rec = self.record(f"prefix-{name}", merge_pad(pad, [], poll))
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            fa, fb = pool.submit(self.play, "abi1", f"cp-{name}-a1", mode, ["0 -"], replay=rec), pool.submit(self.play, "abi2", f"cp-{name}-a2", mode, ["0 -"], replay=rec)
            ra, rb = fa.result(), fb.result()
        d = bmp_diff(ra["bmp"], rb["bmp"])
        ok = self.check(d["geometry"], f"{name}: both pictures have the same geometry")
        ram = rb["ram"]
        in_ss = len(ram) == 65536 and ram[0xF600] == 0x10
        ok = self.check(in_ss, f"{name}: the checkpoint is a special-stage frame") and ok
        if d["geometry"]:
            w, h = d["width"], d["height"]
            r0, r1, r2, r3 = content_rect(ra["bmp"])   # the presented picture; the native picture is centred in it (the baseline) at the scale rect height / 224
            pw = (r3 - r1) * 320 // 224
            x0, x1 = (r0 + r2 - pw) // 2, (r0 + r2 - pw) // 2 + pw
            inside = sum(1 for _, xs in d["mask"] for x in xs if x0 <= x < x1)
            if mode in ("orig", "43"):
                ok = self.check(d["differing"] == 0, f"{name}: no margin is presented, so the pictures are equal ({d['differing']} pixels differ)") and ok
            else:
                ok = self.check(inside == 0, f"{name}: the native picture is pixel-identical to ABI 1 ({inside} pixels differ inside it)") and ok
            self.report.setdefault("checkpoints", []).append({"name": name, "mode": mode, "geometry": [w, h], "differing_pixels": d["differing"], "differing_inside_native_picture": inside, "ok": ok})
            if self.diag is not None:
                for tag, data in (("abi1", ra["bmp"]), ("abi2", rb["bmp"])):
                    ww, hh, rows = bmp_to_rgb_rows(data)
                    write_png(self.diag / f"{name}.{tag}.png", ww, hh, rows)
        return ok


    def special_planes(self, sp, polls, modes=("wide", "w219", "w169", "orig", "43")):
        """SEG-152-T009, the operator's mandatory special-stage extension: on REAL special-stage frames (game mode 0x10, the game PAUSED so the picture is static and a quicksave describes exactly the presented frame) the
        presented pixels of the two scrolling planes, margins included, equal an independent model of the VDP (line scroll, vertical scroll, tile selection, flips, palette, plane priority) built from the quicksave's VRAM/CRAM/VSRAM/registers.
        Pixels under the game's own sprites are excluded (the sprite attribute table's boxes). Also: the provider's output is the cause (a variant that withholds the credited per-row call loses the verdict), ABI 1 is the reference
        (ABI 1 == ABI 2 without the maze pixel for pixel, margins included), the margin maze differs from it only outside the native picture, and Original / exact 4:3 are unchanged."""
        agg = self.report.setdefault("special_planes", {})
        cvt = lambda v: v * 255 // 7   # noqa: E731
        for poll in polls:
            pad = merge_pad(sp, [f"{poll} S", f"{poll + 2} -", f"{poll + 40} K", f"{poll + 41} -"], poll + 80)
            rec = self.record(f"spp-{poll}", merge_pad(sp, [f"{poll} S", f"{poll + 2} -"], poll + 70))   # the same pause, recorded: a frame-exact input for the ABI 1 reference
            for mode in modes:
                rows_out = {}
                for key in ("abi2", "nomaze", "nogen"):
                    sd = self.work / f"save-spp-{key}-{mode}-{poll}"
                    shutil.rmtree(sd, ignore_errors=True)
                    rows_out[key] = (self.play(key, f"spp-{key}-{mode}-{poll}", mode, pad, save=sd), sd)
                ra, rn = rows_out["abi2"][0], rows_out["nomaze"][0]
                tag = f"{mode}@{poll}"
                ok = self.check(len(ra["ram"]) == 65536 and ra["ram"][0xF600] == 0x10 and len(rn["ram"]) == 65536 and rn["ram"][0xF600] == 0x10, f"planes {tag}: the game is in the special stage (mode 0x10)")
                ok = self.check(ra["ram"][0xF63A:0xF63C] == b"\x00\x01", f"planes {tag}: the game is paused (a static frame)") and ok
                last = ra["events"][-1][1:]   # status side shift acc reason auth
                if mode == "orig":
                    ok = self.check(last[3] & 2 == 0, f"planes {tag}: Original offers no scenery") and ok
                elif mode == "43":
                    pass   # exact 4:3 is still offered scenery at the nominal margin; the host asks no cell (nothing is presented beyond the picture), which the pixel checks below cover
                else:
                    ok = self.check(last[3] & 2 != 0 and last[5] == 1, f"planes {tag}: the provider's scenery is accepted and authored (verdict {last})") and ok
                    ng = rows_out["nogen"][0]["events"][-1][1:]
                    ok = self.check(not (ng[3] & 2 != 0 and ng[5] == 1), f"planes {tag}: withholding the provider's per-row answer loses the authored scenery verdict ({ng}), so the margin pixels are the provider's output") and ok
                regs, vram, cram, vsram = sgstate_vdp((rows_out["nomaze"][1] / "states/quick.sgstate").read_bytes())
                at, boxes = ss_plane_model(regs, vram, cram, vsram, cvt)
                for label, run in (("nomaze", rn), ("maze", ra)):
                    w, h, step, rows = bmp_info(run["bmp"])
                    r0, r1, r2, r3 = content_rect(run["bmp"])
                    k = (r3 - r1) // 224
                    margin = ((r2 - r0) // k - 320) // 2
                    mism = {"native": 0, "left": 0, "right": 0}
                    tot = {"native": 0, "left": 0, "right": 0}
                    covered = 0
                    for line in range(224):
                        row = rows[r1 + line * k]
                        under = [b for b in boxes if b[1] <= line < b[1] + b[3]]
                        for g in range(-margin, 320 + margin):
                            if any(b[0] <= g < b[0] + b[2] for b in under):
                                covered += 1
                                continue
                            part = "left" if g < 0 else ("right" if g >= 320 else "native")
                            X = r0 + (g + margin) * k
                            if label == "maze" and part != "native":
                                continue   # the maze pieces cover part of the margins: the margin is verified on the maze-free run and the two runs are compared below
                            tot[part] += 1
                            if (row[X * step + 2], row[X * step + 1], row[X * step]) != at(g, line):
                                mism[part] += 1
                    ok = self.check(mism["native"] == 0 and mism["left"] == 0 and mism["right"] == 0 and tot["native"] > 10000, f"planes {tag} [{label}]: presented pixels equal the independent VDP model (mismatches {mism} of {tot}; margin {margin} px per side)") and ok
                    agg[f"{tag}-{label}"] = {"compared": tot, "mismatching": mism, "excluded_under_game_sprites": covered, "margin_px": margin}
                # the maze run differs from the maze-free run only outside the native picture
                d = bmp_diff(ra["bmp"], rn["bmp"])
                r0, r1, r2, r3 = content_rect(rn["bmp"])
                k = (r3 - r1) // 224
                pw = 320 * k
                x0 = (r0 + r2 - pw) // 2
                inside = sum(1 for _, xs in d["mask"] for x in xs if x0 <= x < x0 + pw) if d["geometry"] else -1
                ok = self.check(d["geometry"] and inside == 0, f"planes {tag}: the margin maze leaves the native picture untouched ({inside} pixels differ inside it)") and ok
                if mode in ("orig", "43"):
                    ok = self.check(d["geometry"] and d["differing"] == 0, f"planes {tag}: Original / exact 4:3 are unchanged by the maze ({d['differing']} pixels)") and ok
                agg[f"{tag}-maze-vs-nomaze"] = {"differing_outside_native": d["differing"], "differing_inside_native": inside}
            # ABI 1 as the equivalent reference: ABI 2 without the maze == ABI 1, pixel for pixel, margins included
            for mode in modes:
                r1_, rn_ = self.play("abi1", f"spp-ref-abi1-{mode}-{poll}", mode, ["0 -"], replay=rec), self.play("nomaze", f"spp-ref-nomaze-{mode}-{poll}", mode, ["0 -"], replay=rec)
                d = bmp_diff(r1_["bmp"], rn_["bmp"])
                self.check(d["geometry"] and d["differing"] == 0 and r1_["ram"] == rn_["ram"] and r1_["ram"][0xF600] == 0x10, f"planes {mode}@{poll}: ABI 2 without the maze equals ABI 1 pixel for pixel in the special stage, margins included ({d['differing']} differing)")
                agg[f"{mode}@{poll}-abi1-vs-nomaze"] = {"differing_pixels": d["differing"]}


    def maze_selftest(self, sp, polls, variant="selfmaze", expect_clean=True):
        """SEG-152-T009: validates the margin maze's RECONSTRUCTION on real frames, where the answer is known. A test-only provider variant redraws EVERY reconstructed piece of the blocks the game itself drew (whole, unclipped, in the
        game's cell order, in the pieces' own priority layer, under the hardware's per-line budget) and, to exercise the derivation path, throws away every learned block type that has a same-mapping sibling so it must be derived from that
        sibling. If position, size, tile, palette, flips, layer and order of the reconstruction are exact, the native picture stays pixel-identical to the maze-free run; a missing, misplaced, mis-tiled or mis-ordered block changes pixels.
        Excluded: only the pixels under the game's own leading non-maze sprites (the player and effects, which the game draws OVER the blocks and a virtual sprite cannot go under). Non-vacuous: pieces must really have been drawn."""
        agg = self.report.setdefault("maze_selftest", {})
        for poll in polls:
            pad = merge_pad(sp, [f"{poll} S", f"{poll + 2} -", f"{poll + 30} K", f"{poll + 31} -"], poll + 50)
            sd = self.work / f"save-mst-{poll}"
            shutil.rmtree(sd, ignore_errors=True)
            ref = self.play("nomaze", f"mst-ref-{poll}", "wide", pad, save=sd)
            run = self.play(variant, f"mst-self-{poll}", "wide", pad)
            cov = json.loads((self.work / f"mst-self-{poll}.coverage.json").read_text())["virtual_sprites"]
            ram = ref["ram"]
            ok = self.check(len(ram) == 65536 and ram[0xF600] == 0x10 and ram[0xF63A:0xF63C] == b"\x00\x01" and run["ram"] == ram, f"selftest {poll}: a paused special-stage frame, the same state in both runs")
            regs, vram, cram, vsram = sgstate_vdp((sd / "states/quick.sgstate").read_bytes())
            _, boxes = ss_plane_model(regs, vram, cram, vsram, lambda v: v)
            # the leading sprites: those before the first sprite whose box is centred on a block position the game computed
            u16 = lambda o: (ram[o] << 8) | ram[o + 1]   # noqa: E731
            centres = set()
            for i in range(16):
                for j in range(16):
                    px, py = u16(0x8000 + (i * 16 + j) * 4), u16(0x8000 + (i * 16 + j) * 4 + 2)
                    centres.add((((px + 0x8000) & 0xFFFF) - 0x8000 + 160, ((py + 0x8000) & 0xFFFF) - 0x8000 + 112))
            lead = next((n for n, b in enumerate(boxes) if n > 0 and (b[0] + b[2] // 2, b[1] + b[3] // 2) in centres), 1)
            d = bmp_diff(run["bmp"], ref["bmp"])
            r0, r1, r2, r3 = content_rect(ref["bmp"])
            k = (r3 - r1) // 224
            x0 = (r0 + r2 - 320 * k) // 2
            inside = covered = 0
            if d["geometry"]:
                for y, xs in d["mask"]:
                    for x in xs:
                        g, line = (x - x0) // k, (y - r1) // k
                        if 0 <= g < 320 and 0 <= line < 224:
                            if any(b[0] <= g < b[0] + b[2] and b[1] <= line < b[1] + b[3] for b in boxes[:lead]):
                                covered += 1
                            else:
                                inside += 1
            else:
                inside = -1
            ok = self.check(cov["pixels_picture"] > 0 and cov["sets"] > 0, f"selftest {poll}: the reconstruction was really drawn over the picture ({cov['pixels_picture']} picture pixels from {cov['sets']} set)") and ok
            if expect_clean:
                ok = self.check(inside == 0, f"selftest {poll}: every reconstructed block (derived types included) reproduces the game's own sprite pixel for pixel ({inside} pixels differ outside the {lead} leading non-maze sprites)") and ok
            else:
                ok = self.check(inside != 0, f"FALSIFY selftest {poll} [{variant}]: a deliberately wrong reconstruction is caught ({inside} pixels differ)") and ok
            agg[f"{variant}-{poll}" if variant != "selfmaze" else str(poll)] = {"picture_pixels_redrawn": cov["pixels_picture"], "differing_outside_leading_sprites": inside, "differing_under_leading_sprites": covered, "leading_sprites": lead}


    def special_coverage(self, sp):
        """SEG-152-T009: for EVERY special-stage frame at each margin presentation, why the margin maze is or is not delivered. Eligible block = a layout block (work RAM) whose computed centre puts it where a piece can reach a margin
        (centre < 16 px from the picture's left edge or beyond 304, inside the presented margin and the game's vertical cull). Per frame exactly one class: `fit_failed` (the game's block-position grid could not be reproduced), `learn_refused`
        (the frame's sprite table could not be aligned with its blocks, or a type contradicted itself: fail-closed), `no_eligible_blocks` (the layout has no block there), `eligible_not_reconstructed` (blocks exist but none could be
        drawn) or `delivered`; and, in delivered frames, the count of eligible blocks that were omitted because their type was not on screen that frame (by type), and whether the 64-piece limit dropped pieces. Hard invariants:
        the fit never fails, every frame is classified, and `delivered` equals the production run's delivery verdicts frame for frame."""
        agg = self.report.setdefault("special_coverage", {})
        for mode in ("wide", "w219", "w169"):
            rec = self.record("special", sp)
            a1, a2 = self.run_pairs([(f"cov-{mode}", dict(mode=mode, pad=sp, replay=rec))])[f"cov-{mode}"]
            au = self.play("audit", f"cov-audit-{mode}", mode, sp, replay=rec)
            extra, bad = self.maze_frames(a1, a2)
            rows = []
            for m in au["lines"].get("MOD_LOG", []):
                line = m.get("line", "")
                if line.startswith("Z "):
                    v = [int(x) for x in line[2:].split()]
                    rows.append({"f": v[0], "fit": v[1], "learn": v[2], "nsat": v[3], "ncell": v[4], "elig": v[5], "edge": v[6], "cand": v[7], "why": v[8],
                                 "unl": {x % 100: (x - 10000) // 100 for x in v[9:] if 10000 <= x < 20000}, "blank": [x - 2000 for x in v[9:] if 2000 <= x < 3000]})
            def klass(r):
                if r["fit"] != 0:
                    return "fit_failed"
                if r["learn"] != 0:
                    return "learn_refused"
                if r["elig"] == 0:
                    return "no_eligible_blocks"
                return "eligible_not_reconstructed" if r["cand"] == 0 else "delivered"
            cls = {}
            for r in rows:
                cls.setdefault(klass(r), []).append(r)
            delivered = sorted(r["f"] for r in cls.get("delivered", []))
            # the audit log numbers the provider's own frame counter; the production verdicts carry the viewer's: they differ by one constant offset (as for the scenery logs), which must be one constant
            off = {a - b for a, b in zip(delivered, sorted(extra))} if len(delivered) == len(extra) else None
            ok = self.check(not cls.get("fit_failed") and len(cls.get("fit_failed", [])) == 0 and all(r["fit"] != 2 for r in rows), f"coverage {mode}: the game's block-position grid is reproduced in every special-stage frame")
            ok = self.check(len(delivered) == len(extra) and off is not None and len(off) == 1 and not bad, f"coverage {mode}: the frames the audit calls delivered ({len(delivered)}) are exactly the production run's delivery verdicts ({len(extra)}; one constant frame-number offset {sorted(off) if off else off}; other differing frames {len(bad)})") and ok
            omitted, eligible = {}, 0
            for r in cls.get("delivered", []):
                for t, n in r["unl"].items():
                    omitted[t] = omitted.get(t, 0) + n
            for r in rows:
                if klass(r) in ("delivered", "eligible_not_reconstructed"):
                    eligible += r["elig"]
            blank_seen = sorted({t for r in rows for t in r["blank"]})
            learn_refused = sorted(r["f"] for r in cls.get("learn_refused", []))
            agg[mode] = {"special_stage_frames": len(rows), "classes": {k: len(v) for k, v in sorted(cls.items())},
                         "learn_refused_with_no_blocks": sum(1 for r in cls.get("learn_refused", []) if r["ncell"] == 0), "learn_refused_first_last": [learn_refused[0], learn_refused[-1]] if learn_refused else None,
                         "learn_refused_reason_bits": {str(w): sum(1 for r in cls.get("learn_refused", []) if r["why"] == w) for w in sorted({r["why"] for r in cls.get("learn_refused", [])})},
                         "eligible_block_instances": eligible, "omitted_type_not_on_screen": {str(t): n for t, n in sorted(omitted.items())}, "omitted_total": sum(omitted.values()),
                         "omitted_blank_type_instances": omitted.get(74, 0), "blank_types_observed": blank_seen,
                         "frames_with_an_omission": sum(1 for r in cls.get("delivered", []) if r["unl"]), "frames_over_the_64_piece_limit": sum(1 for r in rows if r["cand"] > 64), "max_pieces": max([r["cand"] for r in rows] or [0]),
                         "window_edge_hits": sum(r["edge"] for r in rows)}
            self.check(ok, f"coverage {mode}: {agg[mode]['classes']}")


    def overflow_investigation(self, sp):
        """SEG-152-T009: can the RGBA overlay (an existing output) carry the pieces over the host's 64-command limit EXACTLY? For every frame of the recorded special stage whose complete inventory exceeds the limit: (1) the complete
        ordered inventory is recorded before truncation; (2) an INDEPENDENT expected picture is composed from the frame's own VRAM/CRAM (the model is first validated on frames within the limit, where production's output is
        known: it must reproduce production's stacking pixel for pixel); (3) the pieces production drops are composited into overlay layers and the picture compared with the expected one. Differences are classified: `restored` =
        pixels production got wrong because it dropped pieces and the composition got right; `errors` = pixels where the composition differs from the expected picture. The frames are paused (the game's pause makes the picture
        static, a quicksave describes it), reached by the same input; the paused frame is checked to be the frame it is meant to be (equal inventory). Test-only variants; the provider is not changed."""
        agg = self.report.setdefault("overflow_investigation", {})
        run_a = self.play("inv", "oiv-all", "wide", merge_pad(sp, [], 1480))
        invs = {i["frame"]: i for i in parse_inventories(run_a)}
        over = sorted(f for f, i in invs.items() if i["n"] > 64)
        ok = self.check(len(over) > 0, f"overflow investigation: the recorded stage has frames over the command limit ({len(over)})")
        quiet = sorted(f for f, i in invs.items() if 20 <= i["n"] <= 64)
        targets = [("validation", f) for f in (quiet[len(quiet) // 6], quiet[len(quiet) // 2], quiet[5 * len(quiet) // 6])] + [("over", f) for f in over]
        for kind, frame in targets:
            sd = self.work / f"save-oiv-{frame}"
            near = None
            exact = False
            for delta in (3, 2, 4, 1, 5):   # a pause at poll P freezes the picture of guest frame P + delta (3 usually, the input timing moves it by one)
                poll = frame - delta
                shutil.rmtree(sd, ignore_errors=True)
                run_i = self.play("inv", f"oiv-inv-{frame}", "wide", merge_pad(sp, [f"{poll} S", f"{poll + 2} -", f"{poll + 30} K", f"{poll + 31} -"], poll + 50), save=sd)
                inv = parse_inventories(run_i)[-1]
                if inv["pieces"] == invs[frame]["pieces"]:
                    exact = True
                    break
                if near is None and inv["n"] == invs[frame]["n"] and all(abs(p[0] - q[0]) <= 4 and abs(p[1] - q[1]) <= 4 and p[2:5] == q[2:5] and p[5] % 10 == q[5] % 10 for p, q in zip(inv["pieces"], invs[frame]["pieces"])):
                    near = (poll, delta, shutil.copytree(sd, self.work / f"save-oiv-{frame}-near", dirs_exist_ok=True), run_i, inv)
            if not exact and near is not None:   # no pause timing freezes exactly this frame: the nearest reproducible state (same pieces and clips, every one within four pixels)
                poll, delta, _, run_i, inv = near
                shutil.rmtree(sd, ignore_errors=True)
                shutil.copytree(self.work / f"save-oiv-{frame}-near", sd)
            run_b = self.play("nomaze", f"oiv-base-{frame}", "wide", merge_pad(sp, [f"{poll} S", f"{poll + 2} -"], poll + 50))
            ok = self.check(exact or near is not None, f"overflow investigation {frame}: the paused frame is the frame under test ({inv['n']} pieces, pause offset {delta}; {'identical complete inventory' if exact else 'nearest reproducible state: same pieces and clips, every one within four pixels'})") and ok
            _, vram, cram, _ = sgstate_vdp((sd / "states/quick.sgstate").read_bytes())
            exp, rect, st = compose_expected(run_b["bmp"], inv["pieces"], vram, cram, inv["lpx"], inv["rpx"])
            prod = bmp_info(run_i["bmp"])[3]
            if kind == "validation":
                expp, _, _ = compose_expected(run_b["bmp"], inv["pieces"], vram, cram, inv["lpx"], inv["rpx"], skip_flagged=True)
                d = len(rows_diff(prod, expp, st, rect))
                ok = self.check(d == 0, f"overflow investigation {frame}: the independent model reproduces production's output pixel for pixel on a frame within the limit ({inv['n']} pieces, {d} pixels differ)") and ok
                agg[f"validation-{frame}"] = {"pieces": inv["n"], "model_vs_production": d, "game_cell_order_vs_production": len(rows_diff(prod, exp, st, rect))}
                continue
            restored = rows_diff(prod, exp, st, rect)
            entry = {"pieces": inv["n"], "excess": inv["n"] - 64, "restored_pixels_needed": len(restored), "reproduced_exactly": exact, "max_shift_px": 0 if exact else max(max(abs(p[0] - q[0]), abs(p[1] - q[1])) for p, q in zip(inv["pieces"], invs[frame]["pieces"]))}
            for mode, key in (("one-layer", "ovf-one"), ("per-side", "ovf-side")):
                run_v = self.play(key, f"oiv-{key}-{frame}", "wide", merge_pad(sp, [f"{poll} S", f"{poll + 2} -"], poll + 50))
                d = rows_diff(bmp_info(run_v["bmp"])[3], exp, st, rect)
                entry[mode] = {"errors": len(d), "restored_correctly": len(restored - d), "new_errors": len(d - restored), "faulted": run_v["summary"].get("faulted")}
            ok = self.check(entry["one-layer"]["errors"] == 0 and entry["one-layer"]["restored_correctly"] == len(restored) and entry["one-layer"]["faulted"] is False,
                            f"overflow investigation {frame}: the dropped pieces carried by ONE overlay layer reproduce the complete expected picture exactly ({entry['one-layer']}, {entry['restored_pixels_needed']} pixels restored)") and ok
            agg[str(frame)] = entry
        agg["over_limit_frames"] = over

    # ------------------------------------------------------------------ scenarios
    def run_pairs(self, jobs):
        """jobs: [(key, name_a1_args, name_a2_args)] run in parallel; returns {key: (a1, a2)}."""
        out = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.a.jobs) as pool:
            futs = {}
            for key, kw in jobs:
                futs[key] = (pool.submit(self.play, "abi1", key + "-a1", **kw), pool.submit(self.play, "abi2", key + "-a2", **kw))
            for key, (fa, fb) in futs.items():
                out[key] = (fa.result(), fb.result())
        return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    for k in ("--product-root", "--cli", "--sdl", "--cc", "--rom", "--abi1", "--abi1-id", "--abi2", "--work"):
        ap.add_argument(k, required=True)
    ap.add_argument("--jobs", type=int, default=6)
    ap.add_argument("--reuse", action="store_true", help="reuse a program already built from the same package identity in --work")
    ap.add_argument("--scenario-set", default="s2", choices=("s1", "s2"))
    ap.add_argument("--only", default="")
    ap.add_argument("--json", default="")
    ap.add_argument("--diag", default="", help="a LOCAL directory OUTSIDE this repository for the visual checkpoints (screenshots and difference pictures of the real game: never committed)")
    a = ap.parse_args(argv)
    diag = require_outside_repo(a.diag, "--diag") if a.diag else None
    c = Cmp(a)   # refuses a --work directory inside the repository too
    if diag is not None:
        diag.mkdir(parents=True, exist_ok=True)
        c.diag = diag
    only = set(x for x in a.only.split(",") if x)
    want = lambda n: not only or n in only  # noqa: E731
    pads = {
        "s1": level_pad([300, 700], 900, 4800), "s2": level_pad([400, 700, 1000], 1400, 6000),   # a fourth Start in a level PAUSES the game: three leave the title and the menus
    }
    level, level_end = pads[a.scenario_set], 6200 if a.scenario_set == "s2" else 5000
    level = level + [f"{level_end} Q"]
    idle = ["0 -", "14000 Q"]
    idle_level = [ln for ln in level if ln.split()[1] in ("-", "S")] + [f"{level_end} Q"]   # the title and the menus, then a level left alone: no input edge after the Starts, so no route-dependent timing
    # builds (the ABI 1 program and the ABI 2 program; the falsification variants only when selected)
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:   # each `segarecomp build` already compiles with every core
        futs = [pool.submit(c.abi1_program), pool.submit(c.abi2_program, "abi2")]
        if want("falsify"):
            futs += [
                pool.submit(c.abi2_program, "mut-lag", lambda t: t.replace("#define RENDER_LAG 1U", "#define RENDER_LAG 2U")),
                pool.submit(c.abi2_program, "mut-cleared-prev", lambda t: t.replace("prev_level = prev_rec != NULL && prev_rec->hud != 0U;", "prev_level = 0; (void)prev_rec;")),
                pool.submit(c.abi2_program, "mut-cleared-label", lambda t: t.replace("f->hud_frame = cur_rec != NULL ? cur_rec->label :", "f->hud_frame = cur_rec != NULL ? 0U :")),
                pool.submit(c.abi2_program, "mut-dropped-on-restore", lambda t: t.replace("for (unsigned i = 0U; i < RING; ++i) g_ring[i] = tmp[i];", "for (unsigned i = 0U; i < RING; ++i) { g_ring[i] = tmp[i]; g_ring[i].valid = 0U; }")),
                pool.submit(c.abi2_program, "mut-fault", lambda t: t.replace("  r = feat->render;\n", "  r = feat->render;\n  (void)r->overlay_layer_bitmap(2U, 2U, 0U, 0, 0, 257U, 16U, 1U);\n", 1)),
            ]
        if want("fault"):
            futs.append(pool.submit(c.abi2_program, "mut-fault", lambda t: t.replace("  r = feat->render;\n", "  r = feat->render;\n  (void)r->overlay_layer_bitmap(2U, 2U, 0U, 0, 0, 257U, 16U, 1U);\n", 1)))
        if want("coverage"):
            futs.append(pool.submit(c.abi2_program, "audit", coverage_edit, coverage_manifest))
        if want("overflow"):
            futs += [pool.submit(c.abi2_program, "inv", inventory_edit, coverage_manifest), pool.submit(c.abi2_program, "nomaze", lambda t: t.replace("if (v->side != 0U) ss_margin_maze(", "if (v->side == 99U) ss_margin_maze(")),
                     pool.submit(c.abi2_program, "ovf-one", lambda t: overflow_edit(t, "one-layer")), pool.submit(c.abi2_program, "ovf-side", lambda t: overflow_edit(t, "per-side"))]
        if want("planes"):
            futs += [pool.submit(c.abi2_program, "nomaze", lambda t: t.replace("if (v->side != 0U) ss_margin_maze(", "if (v->side == 99U) ss_margin_maze(")),
                     pool.submit(c.abi2_program, "selfmaze", selfmaze_edit), pool.submit(c.abi2_program, "selfbad", selfbad_edit),
                     pool.submit(c.abi2_program, "nogen", lambda t: t.replace("if (r->scenery_generic_rows(0U, mask, 224U, 28U) != 0 || r->scenery_generic_rows(1U, mask, 224U, 28U) != 0) return;", "(void)mask;"))]
        if want("zones"):
            probe = ("static unsigned g_probe_zone = 0xFFFFU;\n  { const unsigned zone = ram[S2_ZONE] | (unsigned)ram[S2_ZONE + 1U] << 8U | (level_mode(ram) ? 0x10000U : 0U); if (zone != g_probe_zone && host->log != NULL) {"
                     " char b[16]; b[0] = 'Z'; b[1] = (char)('A' + (ram[S2_ZONE] & 15U)); b[2] = (char)('0' + (ram[S2_ZONE + 1U] & 7U)); b[3] = level_mode(ram) ? 'L' : 'h'; host->log(b, 4); g_probe_zone = zone; } }\n")
            pool.submit(c.abi2_program, "probe", lambda t: t.replace("  hud_now = hud_state(ram);\n", probe + "  hud_now = hud_state(ram);\n", 1), lambda m: m.replace('required = [', 'required = ["host.log", ', 1) if '"host.log"' not in m else m).result()
        for f in futs:
            f.result()
    if c.failures:
        print(json.dumps({"ok": False, "failures": c.failures}, indent=1))
        return 1
    master = c.record("master", level) if (want("level") or want("transitions") or want("falsify") or want("zones") or want("visual") or want("fault") or not only) else None
    if c.failures:
        print(json.dumps({"ok": False, "failures": c.failures}, indent=1))
        return 1
    c.report["recorded_gameplay_frames"] = master[1] if master else None
    # scenario A: the level run at every presentation mode
    jobs = [(f"level-{m}", dict(mode=m, pad=level, replay=master)) for m in MODES if want("level") or want(f"level-{m}") or (want("visual") and m == "wide")]
    # scenario B: attract-mode demos (idle title), widest and 16:9
    if want("demos") or want("visual"):
        jobs += [("demos-wide", dict(mode="wide", pad=idle)), ("demos-w169", dict(mode="w169", pad=idle))]
    # scenario C: aspect transitions in a level and replay determinism
    sched = "1600:21:9,1900:16:9,2200:orig,2500:4:3,2800:32:9"
    if want("transitions"):
        jobs += [("transitions", dict(mode="wide", pad=level, schedule=sched, replay=master)), ("transitions-again", dict(mode="wide", pad=level, schedule=sched, replay=master))]
    if want("acts") and a.scenario_set == "s1":   # Green Hill acts 2 and 3 by the level-select route, three recorded sessions each (jump cadence 70/100/140 polls); the 100-poll sessions at every presentation mode, the others at 32:9 and 16:9
        for act in (2, 3):
            for jump in (70, 100, 140):
                rec = c.record(f"act{act}-j{jump}", act_pad(act, jump))
                jobs += [(f"act{act}-j{jump}-{m}", dict(mode=m, pad=act_pad(act, jump), replay=rec)) for m in MODES if jump == 100 or m in ("wide", "w169")]
    if want("special") and a.scenario_set == "s1":   # the special stage (wrapped plane through the per-row generic mask) by the level-select route: the menu line 19 (SPECIAL_STAGE_DOWNS Downs from the first line)
        sp = act_pad(1, 100, until=2400, downs=SPECIAL_STAGE_DOWNS)
        rec = c.record("special", sp)
        jobs += [(f"special-{m}", dict(mode=m, pad=sp, replay=rec)) for m in MODES]
    results = c.run_pairs(jobs) if jobs else {}
    for key, (x, y) in results.items():
        if key.startswith("special-") or (key.startswith("demos-") and a.scenario_set == "s1"):   # the Sonic 1 attract demo plays a special stage too
            c.equal_maze(key, x, y, key.split("-", 1)[1])
            continue
        c.equal(key, x, y, minimum=100, need=("scenery",) if key.startswith("demos") and a.scenario_set == "s1" else ("scenery", "hud"))   # the Sonic 1 attract demo runs outside the verified HUD scope (both packages present no HUD there; the HUD accounting is still compared)
    if want("overflow") and a.scenario_set == "s1":
        c.overflow_investigation(act_pad(1, 100, until=2400, downs=SPECIAL_STAGE_DOWNS))
    if want("coverage") and a.scenario_set == "s1":
        c.special_coverage(act_pad(1, 100, until=2400, downs=SPECIAL_STAGE_DOWNS))
    if want("planes") and a.scenario_set == "s1":   # the mandatory special-stage extension on real special-stage frames
        sp_pad = act_pad(1, 100, until=2400, downs=SPECIAL_STAGE_DOWNS)
        a1, a2 = c.run_pairs([("planes-probe", dict(mode="wide", pad=sp_pad, replay=c.record("special", sp_pad)))])["planes-probe"]
        ext, _ = c.maze_frames(a1, a2)
        c.special_planes(sp_pad, [ext[len(ext) // 6], ext[len(ext) // 2], ext[5 * len(ext) // 6]])
        c.maze_selftest(sp_pad, [ext[len(ext) * n // 10] for n in range(1, 10)])
        c.maze_selftest(sp_pad, [ext[len(ext) // 2]], variant="selfbad", expect_clean=False)
    if want("special") and a.scenario_set == "s1":   # pictures of three special-stage frames that deliver the maze, at every presentation mode (the frames are chosen from ABI 2's own run)
        extra, _ = c.maze_frames(*results["special-wide"])
        picks = [extra[len(extra) // 6], extra[len(extra) // 2], extra[5 * len(extra) // 6]] if len(extra) >= 6 else extra
        for n, poll in enumerate(picks):
            for m in MODES:
                c.maze_checkpoint(f"special-maze-{n}-{m}", poll, m, sp)
        for m in MODES:   # a narrow margin can hold no block in one picked frame; every margin mode must show the maze in at least one
            if m not in ("orig", "43"):
                shown = [cp["differing_pixels"] for cp in c.report.get("checkpoints", []) if cp["name"].startswith("special-maze-") and cp["name"].endswith("-" + m)]
                c.check(any(x > 0 for x in shown), f"special-maze checkpoints at {m}: the margins show the maze in at least one picked frame ({shown})")
    if "transitions" in results:
        for i, label in ((0, "abi1"), (1, "abi2")):
            t1, t2 = results["transitions"][i], results["transitions-again"][i]
            c.check(t1["events"] == t2["events"] and t1["bmp"] == t2["bmp"], f"replay determinism ({label}): the second run reproduces every per-frame verdict and the final picture")
        c.check(len({t["side"] for t in results["transitions"][1]["trace"].values()}) >= 3, "the aspect changed several times (three different planned sides)")
    # scenario D: save/load/rewind through the real viewer, ABI 1 against ABI 2
    if want("lifecycle") or want("visual"):
        for k in ('abi1', 'abi2'):
            for d in (c.work / f'save-{k}', c.work / f'save-rw-{k}'):
                shutil.rmtree(d, ignore_errors=True)
        # run the saving runs first (they create the slots), then load/rewind runs
        with concurrent.futures.ThreadPoolExecutor(max_workers=a.jobs) as pool:
            save_at = 2300
            base_pad = merge_pad(idle_level, [], 3400)   # longer than the restoring runs, whose frame numbers run ahead (load) or repeat (rewind)
            save_pad = merge_pad(idle_level, [f"{save_at} K", f"{save_at + 1} -"], 2700)
            fut = {(k, t): pool.submit(c.play, k, f"life-{t}-{k}", "wide", p, save=(c.work / f"save-{k}") if t == "save" else None) for k in ("abi1", "abi2") for t, p in (("base", base_pad), ("save", save_pad))}
            res = {kt: f.result() for kt, f in fut.items()}
            load_pad = merge_pad(idle_level, ["1900 M", "1901 -"], 2700)
            rw_pad = merge_pad(idle_level, ["2500 Y", "2501 -"], 2700)
            fut2 = {}
            for k in ("abi1", "abi2"):
                fut2[(k, "load")] = pool.submit(c.play, k, f"life-load-{k}", "wide", load_pad, save=c.work / f"save-{k}")
                fut2[(k, "rewind")] = pool.submit(c.play, k, f"life-rewind-{k}", "wide", rw_pad, save=c.work / f"save-rw-{k}")
            res.update({kt: f.result() for kt, f in fut2.items()})
        counts = {}
        for kind in ("load", "rewind"):
            for k in ("abi1", "abi2"):
                run, base = res[(k, kind)], res[(k, "base")]
                events, bv = run["events"], c.verdicts(base)
                frames = [e[0] for e in events]
                jumps = [i for i in range(1, len(frames)) if frames[i] != frames[i - 1] + 1]
                restored = [e for e in run["state"] if e.get("event") in (kind, "load", "rewind")]
                # every occurrence equals the uninterrupted run's verdict for its frame number, but the one newly produced frame after the restore (the host's STALE_STATE for both ABIs)
                wrong = [(i, e) for i, e in enumerate(events) if e[1:] != bv.get(e[0]) and not (i - 1 in jumps and e[1:][3] == 0 and e[1:][4] == 1 and e[1:][2] == 0)]
                shape = len(jumps) >= 1 and (kind == "load" and frames[jumps[0]] > frames[jumps[0] - 1] + 1 or kind == "rewind" and frames[jumps[0]] <= frames[jumps[0] - 1])
                c.check(shape and not wrong, f"({k}) {kind}: a real discontinuity (jumps {[(frames[i - 1], frames[i]) for i in jumps][:3]}) and all {len(events)} occurrences equal the uninterrupted run's verdicts but the STALE_STATE restore frame (wrong: {len(wrong)}, first {wrong[:2]})")
                counts[f"{k}-{kind}"] = {"occurrences": len(events), "repeated_frame_numbers": len(events) - len(set(frames)), "discontinuities": len(jumps), "wrong": len(wrong)}
        for kind in ("base", "save", "load", "rewind"):
            x, y = res[("abi1", kind)], res[("abi2", kind)]
            c.equal(f"lifecycle-{kind}", x, y, minimum=100, restore=kind if kind in ("load", "rewind") else None)
        c.report["lifecycle"] = counts
        c.results_life = res
    # scenario V: intermediate visual checkpoints keyed to guest-frame identities (a small representative set; every picture pixel for pixel)
    if want("visual"):
        lw = results["level-wide"][0]["trace"]
        picks = {}
        scroll = next((f for f in sorted(lw) if f >= 3500 and lw[f]["acc"] == 3), None)
        fade = next((f for f in sorted(lw) if f > 1600 and lw[f]["acc"] == 1 and lw.get(f - 1, {}).get("acc") == 3), None)
        refused = next((f for f in sorted(lw) if lw[f]["status"] == 2 and lw[f]["acc"] == 0 and f > 5), None)
        dm = results["demos-wide"][0]["trace"]
        accepted = [f for f in sorted(dm) if dm[f]["acc"] == 3]
        cps = []
        G = {"gameplay": True}
        if scroll:
            cps += [("level-scroll-wide", scroll, "wide", level, dict(G)), ("level-scroll-flash", scroll + 8, "wide", level, dict(G)), ("level-scroll-w219", scroll, "w219", level, dict(G)), ("level-scroll-w169", scroll, "w169", level, dict(G)),
                    ("level-scroll-orig", scroll, "orig", level, dict(G)), ("level-scroll-43", scroll, "43", level, dict(G))]
        if fade:
            cps.append(("level-restart-fade", fade + 2, "wide", level, dict(G)))
        if refused:
            cps.append(("level-refused-generic", refused, "wide", idle_level, {}))
        hud_only = next((f for f in sorted(results["demos-wide"][0]["trace"]) if results["demos-wide"][0]["trace"][f]["acc"] == 1 and f > 1000), None)   # a HUD-only frame (no scenery accepted) of the attract demos: the level-restart / transition fade
        if hud_only:
            cps.append(("demo-hud-only", hud_only, "wide", idle, {}))
        for tag, q in (("a", 0.12), ("b", 0.5), ("c", 0.88)):
            if accepted:
                cps.append((f"demo-{tag}", accepted[int(q * (len(accepted) - 1))], "wide", idle, {}))
        cps += [("hud-rings-zero-a", 1300, "wide", level, dict(G)), ("hud-rings-zero-b", 1308, "wide", level, dict(G))]   # the start of the level: no rings yet, the RINGS label flashes between its two palettes every eight frames
        cps += [("transition-169", 1950, "wide", level, dict(G, schedule=sched)), ("transition-orig", 2350, "wide", level, dict(G, schedule=sched)), ("transition-back-wide", 2950, "wide", level, dict(G, schedule=sched)),
                ("restore-load", 2400, "wide", idle_level, {"extras": ["1900 M", "1901 -"], "save": "save", "restore": "load"}), ("restore-rewind", 2560, "wide", idle_level, {"extras": ["2500 Y", "2501 -"], "save": "save-rw", "restore": "rewind"})]
        with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, a.jobs // 2)) as pool:
            futs = [pool.submit(c.checkpoint, n, f, m, pad, **kw) for n, f, m, pad, kw in cps]
            for fu in futs:
                fu.result()
        c.report["visual_checkpoints_total"] = len(cps)
        # liveness: a run that equals itself because the guest is paused or stuck proves nothing. Eight guest frames apart the picture AND the guest RAM must differ, and a later checkpoint must differ from an earlier one.
        if "level-scroll-wide" in c.cp_runs and "level-scroll-flash" in c.cp_runs:
            x, y = c.cp_runs["level-scroll-wide"][0], c.cp_runs["level-scroll-flash"][0]
            c.check(x["bmp"] != y["bmp"] and x["ram"] != y["ram"], "liveness: the guest advances between two checkpoints eight frames apart (picture and RAM differ)")
            c.report["liveness_pair_differs"] = x["bmp"] != y["bmp"] and x["ram"] != y["ram"]
        if "level-scroll-wide" in c.cp_runs and "transition-back-wide" in c.cp_runs:
            x, y = c.cp_runs["level-scroll-wide"][0], c.cp_runs["transition-back-wide"][0]
            c.check(x["ram"] != y["ram"] and x["bmp"] != y["bmp"], "liveness: a later checkpoint differs from an earlier one (the guest is not paused)")
        for i in c.report.get("checkpoints", []):
            c.check(i["ok"], f"visual checkpoint {i['name']}: {i['differing_pixels']} differing pixels")
        if c.diag is not None:
            (c.diag / "manifest.json").write_text(json.dumps(c.report.get("checkpoints", []), indent=1, sort_keys=True))
    # scenario E: falsification
    if want("fault") and not want("falsify"):   # a provider fault on the real provider: the provider is disabled, the host keeps presenting and the game keeps running (the Sonic 1 package has no other mutants)
        ref = c.play("abi1", "flt-ref", "wide", level, replay=master)
        bad = c.play("mut-fault", "flt-fault", "wide", level, replay=master)
        names, counts = c.compare("mut-fault", ref, bad)
        c.check(bad["summary"].get("faulted") is True, f"FAULT: the injected fault disables the provider (summary {bad['summary']})")
        c.check(bad["rc"] == 0 and bad["outcome"] == "window_closed" and len(bad["events"]) >= 0.95 * len(ref["events"]), f"FAULT: the viewer keeps running and presenting after the fault (rc {bad['rc']}, {len(bad['events'])} of {len(ref['events'])} frames)")
        c.check(bool(names), f"FAULT: the comparison tells the disabled provider from the healthy ABI 1 package ({sorted(names)})")
        c.check(bad["ram"][0xF600] == ref["ram"][0xF600] and bad["ram"][0xFE20:0xFE22] == ref["ram"][0xFE20:0xFE22], "FAULT: the guest itself is unaffected (same game mode and ring count at the end)")
        c.report["fault"] = {"faulted": bad["summary"].get("faulted"), "frames": len(bad["events"]), "differences": sorted(names)}
    if want("falsify"):
        ref = c.play("abi1", "fal-ref", "wide", level, replay=master)
        out = {}
        for name in ("mut-lag", "mut-cleared-prev", "mut-cleared-label", "mut-dropped-on-restore", "mut-fault"):
            if name in ("mut-dropped-on-restore", "mut-cleared-label"):
                continue   # the first is tested at a restore below; the second needs a frame whose label is not the default (rings 0), see below
            bad = c.play(name, f"fal-{name}", "wide", level, replay=master)
            names, counts = c.compare(name, ref, bad)
            out[name] = sorted(names)
            c.check(bool(names), f"FALSIFY {name}: the comparison fails the mutant ({sorted(names)})")
        # the held/selected HUD label: at the very start of the level the player has no rings and the label flashes; clearing the label state must change the PICTURE there
        rec_hud = c.record("prefix-1300", merge_pad(level, [], 1300))
        hud_ref = c.play("abi1", "fal-hud-ref", "wide", ["0 -"], replay=rec_hud)
        hud_bad = c.play("mut-cleared-label", "fal-hud-mut", "wide", ["0 -"], replay=rec_hud)
        names = c.compare("mut-cleared-label", hud_ref, hud_bad)[0]
        out["mut-cleared-label"] = sorted(names)
        c.check("picture" in names, f"FALSIFY mut-cleared-label: at the rings-zero frame the comparison fails the mutant on the picture ({sorted(names)})")
        c.report["falsification"] = out
        # a restore that drops the maintained state must differ from the uninterrupted run (the state is essential)
        sv = c.play("mut-dropped-on-restore", "fal-drop-save", "wide", merge_pad(idle_level, ["2300 K", "2301 -"], 2700), save=c.work / "save-drop")
        ld = c.play("mut-dropped-on-restore", "fal-drop-load", "wide", merge_pad(idle_level, ["1900 M", "1901 -"], 2700), save=c.work / "save-drop")
        good = c.results_life[("abi2", "load")] if want("lifecycle") else None
        c.report["falsification"]["mut-dropped-on-restore"] = {"verdict_occurrences": len(ld["events"])}
        if good is not None:
            c.check(ld["events"] != good["events"], "FALSIFY mut-dropped-on-restore: dropping the maintained state on restore changes an occurrence the real provider keeps")
        bad = c.play("mut-fault", "fal-fault", "wide", level, replay=master)
        vanilla_prog = c.work / "vanilla"
        b = c.h.build(c.work / "abi1-effective.rom", vanilla_prog)   # the BPS-patched image with NO provider (the BPS alone changes the guest: it moves the original HUD off screen)
        c.check(b.returncode == 0, "the patched image without a provider builds")
        c.progs["vanilla"] = (vanilla_prog, None)
        van = c.play("vanilla", "fal-vanilla", "wide", level, replay=master)
        logs = [m.get("line") for m in bad["lines"].get("MOD_LOG", [])]
        faults = [l for l in logs if l and l.startswith("E_MOD_FAULT")]
        c.check(len(faults) == 1 and "cause=range" in faults[0] and bad["summary"].get("faulted") is True, f"injected fault: one range fault disables the provider ({faults[:1]})")
        c.check(bad["bmp"] == van["bmp"] and bad["ram"] == van["ram"], "injected fault: the presented frame and the guest RAM equal those of the patched image without a provider (the fault never touches the guest; nothing of the provider is presented)")
        c.report["injected_fault"] = {"faults": len(faults), "equals_vanilla_picture": bad["bmp"] == van["bmp"], "equals_vanilla_ram": bad["ram"] == van["ram"]}
    # scenario F: the scene classes the verified frames cover (zone / act of every accepted frame, from a probe build)
    if want("zones"):
        classes = {}
        for tag, pad in (("level", level), ("demos", idle)):
            run = c.play("probe", f"zones-{tag}", "wide", pad, replay=master if tag == "level" else None)
            for m in run["lines"].get("MOD_LOG", []):
                line = m.get("line", "")
                if line.startswith("Z"):
                    classes.setdefault(tag, []).append(line[1:])
        c.report["scene_classes"] = {k: sorted(set(v)) for k, v in classes.items()}
    # performance: wall-clock of the matching level runs (class-level: both include the same guest and viewer work)
    if "level-wide" in results:
        x, y = results["level-wide"]
        frames = max(1, len(x["trace"]))
        c.report["performance"] = {"level_wide_wall_s": {"abi1": round(x["wall"], 1), "abi2": round(y["wall"], 1)}, "frames": frames, "per_frame_ms": {"abi1": round(1000 * x["wall"] / frames, 3), "abi2": round(1000 * y["wall"] / frames, 3)},
                                   "note": "the two runs were concurrent with others: class-level only"}
    c.report["ok"] = not c.failures
    c.report["failures"] = c.failures
    print(json.dumps(c.report, indent=1, sort_keys=True))
    if a.json:
        pathlib.Path(a.json).write_text(json.dumps(c.report, indent=1, sort_keys=True))
    return 0 if not c.failures else 1


if __name__ == "__main__":
    sys.exit(main())
