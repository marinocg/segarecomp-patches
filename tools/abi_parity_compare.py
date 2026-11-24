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


def merge_pad(lines, extra, end):
    """The level pad with hotkey presses (`<poll> K|M|Y`) inserted in poll order and the run ended at poll `end` (the viewer applies the script in order)."""
    items = [(int(l.split()[0]), l) for l in lines if not l.endswith(" Q")]
    items = [(f, l) for f, l in items if f <= end] + [(int(l.split()[0]), l) for l in extra]
    items.sort(key=lambda t: t[0])
    return [l for _, l in items] + [f"{end} Q"]


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
        self.a = a
        self.root = pathlib.Path(a.product_root).resolve()
        sys.path.insert(0, str(self.root / "tests"))
        import viewer_mod_support as vms
        self.vms = vms
        self.segapatch = load(self.root / "tools/segapatch.py", "segapatch")
        self.work = pathlib.Path(a.work).resolve()
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
    def play(self, key, name, mode, pad, schedule=None, save=None, budget=4_000_000_000, extra=None, replay=None):
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
            pad = ["0 -"]
        run, lines, frame, ram = self.run_program(prog, name, "\n".join(pad) + "\n", save, ident, env, budget, session={"replay": replay[0]} if replay is not None else None)
        wall = time.time() - t0
        trace = lines.get("VIEWER_TEST_TRACE", [])
        cov = json.loads(report.read_text()) if report.is_file() else None
        scene = cov["scenes"][0]["components"] if cov and cov.get("scenes") else None
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

    def equal(self, key, a, b, minimum=30, restore=None):
        names, counts = self.compare(key, a, b)
        problems = validate_run(a, key + " [abi1]", a["end_poll"], restore=restore) + validate_run(b, key + " [abi2]", b["end_poll"], restore=restore, mod=True)
        for p in problems:
            self.check(False, p)
        names = names | ({"incomplete-run"} if problems else set())
        if not key.endswith("orig"):   # a scenario that never exercised the components it compares proves nothing (the presentation setting can silently be Original): scenery and HUD must have been offered
            for what, n in (("scenery", counts["scenery_frames_a1"]), ("hud", counts["hud_frames_a1"])):
                if n == 0:
                    self.check(False, f"{key}: the ABI 1 run never presented {what} (the scenario does not exercise it)")
                    names = names | {"component-not-exercised"}
        self.report.setdefault("scenarios", {})[key] = {"differences": sorted(names), **counts}
        ok = self.check(not names and counts["frames"] >= minimum, f"{key}: ABI 2 == ABI 1 in every mechanism ({sorted(names)}, {counts})")
        healthy = self.check(b["summary"].get("faulted") is False, f"{key}: the ABI 2 provider is healthy (a refusal is not a fault)")
        return ok and healthy

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
    c = Cmp(a)
    if a.diag:
        d = pathlib.Path(a.diag).resolve()
        top = pathlib.Path(__file__).resolve().parent.parent
        if d == top or top in d.parents:
            sys.exit("--diag must be a directory OUTSIDE the repository (real-game captures are never committed)")
        d.mkdir(parents=True, exist_ok=True)
        c.diag = d
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
        if want("zones"):
            probe = ("static unsigned g_probe_zone = 0xFFFFU;\n  { const unsigned zone = ram[S2_ZONE] | (unsigned)ram[S2_ZONE + 1U] << 8U | (level_mode(ram) ? 0x10000U : 0U); if (zone != g_probe_zone && host->log != NULL) {"
                     " char b[16]; b[0] = 'Z'; b[1] = (char)('A' + (ram[S2_ZONE] & 15U)); b[2] = (char)('0' + (ram[S2_ZONE + 1U] & 7U)); b[3] = level_mode(ram) ? 'L' : 'h'; host->log(b, 4); g_probe_zone = zone; } }\n")
            pool.submit(c.abi2_program, "probe", lambda t: t.replace("  hud_now = hud_state(ram);\n", probe + "  hud_now = hud_state(ram);\n", 1), lambda m: m.replace('required = [', 'required = ["host.log", ', 1) if '"host.log"' not in m else m).result()
        for f in futs:
            f.result()
    if c.failures:
        print(json.dumps({"ok": False, "failures": c.failures}, indent=1))
        return 1
    master = c.record("master", level) if (want("level") or want("transitions") or want("falsify") or want("zones") or want("visual") or not only) else None
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
    results = c.run_pairs(jobs) if jobs else {}
    for key, (x, y) in results.items():
        c.equal(key, x, y, minimum=100)
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
