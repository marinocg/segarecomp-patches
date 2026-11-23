#!/usr/bin/env python3
"""LOCAL real-image comparison of one ABI 1 (schema 2) widescreen package against its ABI 2 (schema 3) successor (SEG-152-T009/T010). Needs a product checkout (its CLI, SDL3 and the viewer test seams),
the legally held original image and a compiler; it is never run by public CI and it writes nothing into the repository. Output is AGGREGATE ONLY (counts and pass/fail classes): no frame, digest, trace line or RAM byte.

  abi_parity_compare.py --product-root DIR --cli BIN --sdl DIR --cc CC --rom IMAGE --abi1 PATCH_DIR --abi1-id ID --abi2 PROJECT_DIR --work DIR [--quick] [--only SCENARIO,...]

Both packages are built into the same real viewer program (the product's `segarecomp build`; the schema 2 one from the image its BPS produces, the schema 3 one from the original, exactly as the launcher does) and
played with the same scripted input and the same video settings. Every scenario compares, frame by frame, the producer's verdict of the two packages (frame identity, status, side, placement, accepted component mask,
refusal reason, authored status), the coverage accounting (offered / accepted / presented / rejected per component), the presented final picture byte for byte and the final guest work RAM. There is no tolerance,
no skipped frame and no normalisation. Falsification variants of the ABI 2 provider (a wrong frame lag, state cleared, state dropped on restore, a faulting callback) must FAIL the same comparison for named reasons.
"""
import argparse, concurrent.futures, importlib.util, json, os, pathlib, re, shutil, subprocess, sys, tempfile, time

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

    def run_program(self, prog, name, pad, save, ident, env, budget, timeout=1500):
        """The product harness' `play` with a longer wall-clock bound (a real image runs thousands of frames): the same environment, the same tags, an explicit instruction budget."""
        frame, ram = self.work / (name + ".bmp"), self.work / (name + ".ram")
        for p in (frame, ram):
            p.unlink(missing_ok=True)
        extras = dict(SEGARECOMP_VIEWER_FINAL_FRAME=str(frame), SEGARECOMP_VIEWER_FINAL_RAM=str(ram))
        pad_file = self.work / (name + ".pad")
        pad_file.write_text(pad)
        extras["SEGARECOMP_VIEWER_PAD_SCRIPT"] = str(pad_file)
        if save is not None:
            pathlib.Path(save).mkdir(parents=True, exist_ok=True)
            extras.update(SEGARECOMP_SAVE_DIR=str(save), SEGARECOMP_ROM_SHA256=self.image_sha, SEGARECOMP_REWIND_INTERVAL_MS="100", SEGARECOMP_REWIND="on", SEGARECOMP_SAVE_VARIANT=ident)
        extras.update(env)
        run = subprocess.run([str(pathlib.Path(prog) / "game"), "--instruction-budget", str(budget)], text=True, capture_output=True, env=self.h.env(**extras), timeout=timeout, cwd=self.work)
        lines = {}
        for line in run.stderr.splitlines():
            tag, _, rest = line.partition(" ")
            if tag in self.vms.TAGS:
                try:
                    lines.setdefault(tag, []).append(json.loads(rest))
                except ValueError:
                    lines.setdefault(tag, []).append({"raw": rest})
        return run, lines, frame, ram

    # ------------------------------------------------------------------ one run
    def play(self, key, name, mode, pad, schedule=None, save=None, budget=4_000_000_000, extra=None):
        prog, ident = self.progs[key]
        aspect, mode_schedule = MODES[mode]
        cfg = self.work / (name + ".cfg")
        cfg.write_text(ENHANCED % aspect)
        report = self.work / (name + ".coverage.json")
        report.unlink(missing_ok=True)
        env = {"SEGARECOMP_VIEWER_SETTINGS": str(cfg), "SEGARECOMP_VIEWER_FINAL_FRAME_NO_NOTICES": "1", "SEGARECOMP_VIEWER_TEST_TRACE": "1", "SEGARECOMP_COVERAGE_REPORT": str(report)}
        sched = ",".join(x for x in (mode_schedule, schedule) if x)
        if sched:
            env["SEGARECOMP_VIEWER_TEST_VIDEO_AT"] = sched
        env.update(extra or {})
        t0 = time.time()
        run, lines, frame, ram = self.run_program(prog, name, "\n".join(pad) + "\n", save, ident, env, budget)
        wall = time.time() - t0
        trace = lines.get("VIEWER_TEST_TRACE", [])
        cov = json.loads(report.read_text()) if report.is_file() else None
        scene = cov["scenes"][0]["components"] if cov and cov.get("scenes") else None
        nat = (lines.get("VIEWER_NATIVE_SUMMARY") or [{}])[0]
        return {"bmp": frame.read_bytes() if frame.is_file() else b"", "ram": ram.read_bytes() if ram.is_file() else b"", "events": [tuple(t[k] for k in ("f",) + VERDICT) for t in trace],
                "trace": {t["f"]: t for t in trace}, "coverage": scene, "summary": (lines.get("MOD_SUMMARY") or [{}])[0], "native": nat, "lines": lines, "wall": wall, "state": lines.get("VIEWER_STATE", []),
                "outcome": (lines.get("VIEWER_SUMMARY") or [{}])[0].get("outcome"), "stderr": run.stderr[-300:]}

    # ------------------------------------------------------------------ comparison
    @staticmethod
    def verdicts(run):
        return {f: tuple(t[k] for k in VERDICT) for f, t in run["trace"].items()}

    def compare(self, key, a, b):
        """The equality verdict of two runs: per-frame verdicts, coverage accounting, final picture, final RAM. Returns (names of the mechanisms that differ, counts)."""
        va, vb = self.verdicts(a), self.verdicts(b)
        names = set()
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
        if ca is None or cb is None or any({k: ca[c][k] for k in ACCOUNT} != {k: cb[c][k] for k in ACCOUNT} for c in ("scenery", "hud")):
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

    def equal(self, key, a, b, minimum=30):
        names, counts = self.compare(key, a, b)
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
    a = ap.parse_args(argv)
    c = Cmp(a)
    only = set(x for x in a.only.split(",") if x)
    want = lambda n: not only or n in only  # noqa: E731
    pads = {
        "s1": level_pad([300, 700], 900, 4800), "s2": level_pad([400, 700, 1000, 1300], 1400, 6000),
    }
    level, level_end = pads[a.scenario_set], 6200 if a.scenario_set == "s2" else 5000
    level = level + [f"{level_end} Q"]
    idle = ["0 -", "14000 Q"]
    # builds (the ABI 1 program and the ABI 2 program; the falsification variants only when selected)
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
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
    # scenario A: the level run at every presentation mode
    jobs = [(f"level-{m}", dict(mode=m, pad=level)) for m in MODES if want("level") or want(f"level-{m}")]
    # scenario B: attract-mode demos (idle title), widest and 16:9
    if want("demos"):
        jobs += [("demos-wide", dict(mode="wide", pad=idle)), ("demos-w169", dict(mode="w169", pad=idle))]
    # scenario C: aspect transitions in a level and replay determinism
    sched = "1600:21:9,1900:16:9,2200:orig,2500:4:3,2800:32:9"
    if want("transitions"):
        jobs += [("transitions", dict(mode="wide", pad=level, schedule=sched)), ("transitions-again", dict(mode="wide", pad=level, schedule=sched))]
    results = c.run_pairs(jobs) if jobs else {}
    for key, (x, y) in results.items():
        c.equal(key, x, y)
    if "transitions" in results:
        for i, label in ((0, "abi1"), (1, "abi2")):
            t1, t2 = results["transitions"][i], results["transitions-again"][i]
            c.check(t1["events"] == t2["events"] and t1["bmp"] == t2["bmp"], f"replay determinism ({label}): the second run reproduces every per-frame verdict and the final picture")
        c.check(len({t["side"] for t in results["transitions"][1]["trace"].values()}) >= 3, "the aspect changed several times (three different planned sides)")
    # scenario D: save/load/rewind through the real viewer, ABI 1 against ABI 2
    if want("lifecycle"):
        for k in ('abi1', 'abi2'):
            for d in (c.work / f'save-{k}', c.work / f'save-rw-{k}'):
                shutil.rmtree(d, ignore_errors=True)
        # run the saving runs first (they create the slots), then load/rewind runs
        with concurrent.futures.ThreadPoolExecutor(max_workers=a.jobs) as pool:
            save_at = 2300
            base_pad = merge_pad(level, [], 3400)   # longer than the restoring runs, whose frame numbers run ahead (load) or repeat (rewind)
            save_pad = merge_pad(level, [f"{save_at} K", f"{save_at + 1} -"], 2700)
            fut = {(k, t): pool.submit(c.play, k, f"life-{t}-{k}", "wide", p, save=(c.work / f"save-{k}") if t == "save" else None) for k in ("abi1", "abi2") for t, p in (("base", base_pad), ("save", save_pad))}
            res = {kt: f.result() for kt, f in fut.items()}
            load_pad = merge_pad(level, ["1900 M", "1901 -"], 2700)
            rw_pad = merge_pad(level, ["2500 Y", "2501 -"], 2700)
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
            c.check(x["events"] == y["events"] and x["bmp"] == y["bmp"] and x["ram"] == y["ram"], f"lifecycle ({kind}): ABI 2 per-frame verdicts (every occurrence), picture and RAM equal the ABI 1 run's")
        c.report["lifecycle"] = counts
        c.results_life = res
    # scenario E: falsification
    if want("falsify"):
        ref = c.play("abi1", "fal-ref", "wide", level)
        out = {}
        for name in ("mut-lag", "mut-cleared-prev", "mut-cleared-label", "mut-dropped-on-restore", "mut-fault"):
            if name == "mut-dropped-on-restore":
                continue
            bad = c.play(name, f"fal-{name}", "wide", level)
            names, counts = c.compare(name, ref, bad)
            out[name] = sorted(names)
            c.check(bool(names), f"FALSIFY {name}: the comparison fails the mutant ({sorted(names)})")
        c.report["falsification"] = out
        # a restore that drops the maintained state must differ from the uninterrupted run (the state is essential)
        sv = c.play("mut-dropped-on-restore", "fal-drop-save", "wide", merge_pad(level, ["2300 K", "2301 -"], 2700), save=c.work / "save-drop")
        ld = c.play("mut-dropped-on-restore", "fal-drop-load", "wide", merge_pad(level, ["1900 M", "1901 -"], 2700), save=c.work / "save-drop")
        good = c.results_life[("abi2", "load")] if want("lifecycle") else None
        c.report["falsification"]["mut-dropped-on-restore"] = {"verdict_occurrences": len(ld["events"])}
        if good is not None:
            c.check(ld["events"] != good["events"], "FALSIFY mut-dropped-on-restore: dropping the maintained state on restore changes an occurrence the real provider keeps")
        bad = c.play("mut-fault", "fal-fault", "wide", level)
        vanilla_prog = c.work / "vanilla"
        b = c.h.build(c.work / "abi1-effective.rom", vanilla_prog)   # the BPS-patched image with NO provider (the BPS alone changes the guest: it moves the original HUD off screen)
        c.check(b.returncode == 0, "the patched image without a provider builds")
        c.progs["vanilla"] = (vanilla_prog, None)
        van = c.play("vanilla", "fal-vanilla", "wide", level)
        logs = [m.get("line") for m in bad["lines"].get("MOD_LOG", [])]
        faults = [l for l in logs if l and l.startswith("E_MOD_FAULT")]
        c.check(len(faults) == 1 and "cause=range" in faults[0] and bad["summary"].get("faulted") is True, f"injected fault: one range fault disables the provider ({faults[:1]})")
        c.check(bad["bmp"] == van["bmp"] and bad["ram"] == van["ram"], "injected fault: the presented frame and the guest RAM equal those of the patched image without a provider (the fault never touches the guest; nothing of the provider is presented)")
        c.report["injected_fault"] = {"faults": len(faults), "equals_vanilla_picture": bad["bmp"] == van["bmp"], "equals_vanilla_ram": bad["ram"] == van["ram"]}
    # scenario F: the scene classes the verified frames cover (zone / act of every accepted frame, from a probe build)
    if want("zones"):
        classes = {}
        for tag, pad in (("level", level), ("demos", idle)):
            run = c.play("probe", f"zones-{tag}", "wide", pad)
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
