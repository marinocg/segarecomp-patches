"""Executes the ACTUAL assembled retry code (patches/genesis/castle-of-illusion-activation-21x9/src/retry.asm) on a synthetic image through the product's generated-native path.

The asm text is the shipped file with only its addresses remapped into a 16 KiB synthetic image; the "original game" it hooks is a handful of hand-assembled stubs (a fake section loader that logs its
arguments and can be told to fail, plus continuation markers). Nothing commercial is involved. Needs SEGARECOMP_CLI, SEGARECOMP_SDK_DIR (the product's platforms directory) and a C compiler."""
import hashlib, os, pathlib, re, shutil, struct, subprocess, tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
ASM = ROOT / "patches/genesis/castle-of-illusion-activation-21x9/src/retry.asm"
ASM_DIR = lambda v: ROOT / f"patches/genesis/castle-of-illusion-activation-{v}/src/retry.asm"
STATE = 0xFFFC00
STUB_RTS = {"slot_scan": 0x3300, "next_entry": 0x3400, "streamer_tail": 0x3600, "vertical_loader": 0x3500, "level_init": 0x3700, "cull_continue": 0x3800, "cull_delete": 0x3900}
SLOT = lambda i: STATE + 0x10 + 8 * i
LOG = 0xFF0300          # stub counters: +0 loader calls, +4 d2, +6 d5, +8 a2, +c a1, +10 fail knob, +14 loop, +18 next, +1c vertical, +20 tail, +24 level init
def consts(asm):
    """(window_left, window_right, cull_left, cull_right) the retry code of `asm` was generated with."""
    text = asm.read_text()
    leas = [int(v, 16) for v in re.findall(r"lea (0x[0-9a-f]+)\(a1\),a1", text) if int(v, 16) >= 0x3000]
    return (0x4000 - min(v for v in leas if v < 0x4000), max(v for v in leas if v > 0x4000) - 0x4000,
            -int(re.search(r"cmpi\.w #(-0x[0-9a-f]+),d4", text).group(1), 16), int(re.search(r"cmpi\.w #(0x[0-9a-f]+),d4", text).group(1), 16))
WINDOW_L, WINDOW_R, CULL_LEFT, CULL_RIGHT = consts(ASM)
CALLER = 0x3C00     # a faithful caller of the section loader: JSR section_load; ADDI.W #$80,D0 (as both real callers do); the CCR capture; the marker (LOG+0x3C); RTS
SYM = {"section_load": 0x3000, "section_load_body": 0x3006, "slot_scan": 0x3300, "next_entry": 0x3400, "streamer_tail": 0x3600, "vertical_loader": 0x3500, "level_init": 0x3700, "cull_continue": 0x3800, "cull_delete": 0x3900}
FAIL_SITE = 0x3200
MAP = {0x00060c80: 0x2000, 0x00060d40: 0x2100, 0x00060f00: 0x2400, 0x00061200: 0x2800, 0x00061260: 0x2840, 0x00061300: 0x2900}
STATE_END = 0xFCB6      # the retry state and its diagnostics occupy 0xFFFC00..0xFFFCB5


def available():
    return bool(os.environ.get("SEGARECOMP_CLI") and os.environ.get("SEGARECOMP_SDK_DIR"))


def _stubs(entry, fail_hook, hooks):
    def jmp(a): return struct.pack(">HI", 0x4EF9, a)
    def addq(a): return struct.pack(">HII", 0x23FC, 1, a) + struct.pack(">H", 0x4E75)   # move.l #1,abs.l ; rts: a marker that leaves the CCR X bit alone
    img = bytearray(0x4000)
    struct.pack_into(">II", img, 0, 0x01000000, 0x1000)
    img[0x100:0x110] = b"SEGA MEGA DRIVE "
    img[0x1000:0x100A] = bytes.fromhex("4eb90000100c60fe4e75")
    img[0x3000:0x3006] = jmp(entry)                                  # the patched loader entry: jumps into the entry hook
    body = bytes.fromhex("241f" "2a1f" "2e1f" "245f")                 # the original epilogue's restore of d2, d5, d7, a2 (lowest address first)
    body += struct.pack(">HI", 0x33C2, LOG + 4) + struct.pack(">HI", 0x33C5, LOG + 6) + struct.pack(">HI", 0x23CA, LOG + 8) + struct.pack(">HI", 0x23C9, LOG + 12)
    body += bytes.fromhex("0a3c0010")                                 # eori #$10,ccr: the synthetic loader DELIBERATELY changes X on every call (the real one's add.w/add.w d3,d3 do)
    body += struct.pack(">HI", 0x52B9, LOG)                           # calls += 1
    body += struct.pack(">HI", 0x4AB9, LOG + 0x10) + bytes.fromhex("670c")   # tst.l knob; beq ok (skips the 12 bytes of "lea $dc00.w,a3; moveq #0,d6; jmp FAIL_SITE")
    body += bytes.fromhex("47f8dc00" "7C00") + jmp(FAIL_SITE)                    # allocation failure: a3 = the end of the pool scan (the real loader reloads a3 before scanning; the hook's entry decision uses a3 as scratch because it is dead there), d6 = 0, jump to the patched site
    body += bytes.fromhex("4e75")
    img[0x3006:0x3006 + len(body)] = body
    img[FAIL_SITE:FAIL_SITE + 6] = jmp(fail_hook)
    for i, (name, target) in enumerate(hooks.items()):              # a prelude per hook: load the CCR the scenario asks for (RAM 0x334), then jump to the hook
        a = 0x3A00 + 0x10 * i; img[a:a + 12] = struct.pack(">HI", 0x44F9, LOG + 0x34) + struct.pack(">HI", 0x4EF9, target)
    for sym, c in (("slot_scan", 0x14), ("next_entry", 0x18), ("vertical_loader", 0x1C), ("streamer_tail", 0x20), ("level_init", 0x24), ("cull_continue", 0x28), ("cull_delete", 0x2C)):
        a = SYM[sym]; code = addq(LOG + c)
        code = struct.pack(">HI", 0x40F9, LOG + 0x38) + code                                  # move.w sr,abs.l: capture the CCR at the continuation, before the marker
        if sym == "vertical_loader": code = struct.pack(">HII", 0x33F9, 0x00FFFC0E, LOG + 0x30) + code        # snapshot the retry-state key at the original vertical loader's entry
        img[a:a + len(code)] = code
    code = struct.pack(">HI", 0x4EB9, 0x3000) + bytes.fromhex("06400080") + struct.pack(">HI", 0x40F9, LOG + 0x38) + struct.pack(">HII", 0x23FC, 1, LOG + 0x3C) + struct.pack(">H", 0x4E75)
    img[CALLER:CALLER + len(code)] = code
    return img


class Harness:
    def __init__(self, asm=None, mapping=None, free_len=0x1000, state_end=STATE_END):
        self.cli, self.sdk, self.cc = os.environ["SEGARECOMP_CLI"], pathlib.Path(os.environ["SEGARECOMP_SDK_DIR"]), os.environ.get("SEGARECOMP_CC", "cc")
        self.work = pathlib.Path(tempfile.mkdtemp(prefix="castle-activation-exec-"))
        text = (asm or ASM).read_text()
        for old, new in (mapping or MAP).items():
            text = text.replace("0x%08x" % old, "0x%04x" % new)
        text = re.sub(r"^free usa-europe .*$", "free fixture 0x2000 0x%x 0x00" % free_len, text, flags=re.M).replace("org usa-europe", "org fixture")
        proj = self.work / "proj"; (proj / "asm").mkdir(parents=True); (proj / "asm/retry.asm").write_text(text)
        entry, fail_hook, frame_hook, reset = 0x2000, 0x2100, 0x2400, 0x2800
        hooks = {"entry": entry, "fail": fail_hook, "frame": frame_hook, "reset": reset, "cull": 0x2840, "noop": 0x3600, "caller": 0x3C00}
        image = bytes(_stubs(entry, fail_hook, hooks))
        sha = hashlib.sha256(image).hexdigest()
        toml = f'[mod]\nid = "castle-exec"\nversion = "1.0.0"\nname = "Exec"\nlicense = "CC0-1.0"\n\n[target]\nplatform = "genesis"\n\n[[target.revision]]\nlabel = "fixture"\nsha256 = "{sha}"\n\n[[source]]\nkind = "guest-asm"\npath = "asm/retry.asm"\ncpu = "m68k"\n'
        for n, a in SYM.items():
            toml += f'\n[[symbol]]\nname = "{n}"\nrevision = "fixture"\naddress = "{a:#x}"\nprovenance = "verified"\n'
        (proj / "mod.toml").write_text(toml)
        (self.work / "vanilla.bin").write_bytes(image)
        r = subprocess.run([self.cli, "mod", "apply", str(proj), "--rom", str(self.work / "vanilla.bin"), "--out", str(self.work / "modded.bin")], capture_output=True, text=True)
        assert r.returncode == 0 and '"ok":true' in r.stdout, r.stdout + r.stderr
        self.image = (self.work / "modded.bin").read_bytes()
        self.entries = {name: 0x3A00 + 0x10 * i for i, name in enumerate(hooks)}
        gen = subprocess.run([self.cli, "emit-general-startup-bridge-c", "--rom", str(self.work / "modded.bin"), "--entry", "00001000", "--mapping-base", "00000000", "--rom-sha256", hashlib.sha256(self.image).hexdigest(), "--immutable-rom-aot"], capture_output=True, text=True).stdout
        assert "genesis_runtime_run" in gen and "translation rejected" not in gen[:200], gen[:300]
        seed = r'''
 runtime.pc = UINT32_C(0x00001000);
 { const char *e = getenv("T_PC"); if (e) runtime.pc = (uint32_t)strtoul(e, NULL, 16);
   e = getenv("T_REGS"); if (e) { char b[2048]; char *t; strncpy(b, e, sizeof b - 1); b[sizeof b - 1] = 0; for (t = strtok(b, ","); t; t = strtok(NULL, ",")) { char *q = strchr(t, '='); unsigned long v; if (!q) continue; *q = 0; v = strtoul(q + 1, NULL, 16);
       if (t[0] == 's' && t[1] == 'r') runtime.sr = (uint16_t)v; else if (t[0] == 'd') runtime.d[t[1] - '0'] = (uint32_t)v; else if (t[0] == 'a') runtime.a[t[1] - '0'] = (uint32_t)v; } }
   e = getenv("T_RAM"); if (e) { char b[8192]; char *t; strncpy(b, e, sizeof b - 1); b[sizeof b - 1] = 0; for (t = strtok(b, ","); t; t = strtok(NULL, ",")) { char *q = strchr(t, '='); unsigned long a, i; if (!q) continue; *q = 0; a = strtoul(t, NULL, 16) & 0xFFFFU; q++;
       for (i = 0; q[i] && q[i + 1]; i += 2) { char h[3] = {q[i], q[i + 1], 0}; runtime.work_ram[a++ & 0xFFFFU] = (uint8_t)strtoul(h, NULL, 16); } } } }
'''
        gen = gen.replace("runtime.pc = UINT32_C(0x00001000);", seed, 1)
        observe = r'''
 { unsigned i; unsigned long h = 1469598103934665603UL; for (i = 0; i < 0x10000U; ++i) { if (i >= 0x0300U && i < 0x0340U) continue; if (i >= 0xFC00U && i < 0xFC30U) continue; if (i >= 0xFF00U) continue; h = (h ^ runtime.work_ram[i]) * 1099511628211UL; }
   fprintf(stderr, "OUT"); for (i = 0; i < 8; ++i) fprintf(stderr, " d%u=%08X", i, (unsigned)runtime.d[i]); for (i = 0; i < 8; ++i) fprintf(stderr, " a%u=%08X", i, (unsigned)runtime.a[i]);
   fprintf(stderr, " sr=%04X pc=%06X hash=%016lX ram=", (unsigned)runtime.sr, (unsigned)runtime.pc, h); for (i = 0xFC00U; i < 0xFC30U; ++i) fprintf(stderr, "%02X", runtime.work_ram[i]);
   fprintf(stderr, " log="); for (i = 0x0300U; i < 0x0340U; ++i) fprintf(stderr, "%02X", runtime.work_ram[i]); fprintf(stderr, " hi="); for (i = 0xFC30U; i < 0xFC40U; ++i) fprintf(stderr, "%02X", runtime.work_ram[i]); fprintf(stderr, "\n"); }
'''
        observe = observe.replace("0xFC30U", "0x%XU" % state_end).replace("0xFC40U", "0x%XU" % (state_end + 16))
        anchor = re.search(r"\} while \([^;]*\);", gen); assert anchor
        (self.work / "t.c").write_text(gen[:anchor.end()] + observe + gen[anchor.end():])
        env = os.environ.copy()
        if not env.get("SDKROOT") and shutil.which("xcrun"):
            env["SDKROOT"] = subprocess.run(["xcrun", "--show-sdk-path"], text=True, capture_output=True, check=True).stdout.strip()
        b = subprocess.run([self.cc, "-std=gnu11", "-w", "-I", str(self.sdk / "genesis/runtime"), str(self.work / "t.c"), str(self.sdk / "genesis/runtime/runtime.c"), "-o", str(self.work / "t")], capture_output=True, text=True, env=env)
        assert b.returncode == 0, b.stderr[:1500]

    def run(self, where, regs=None, ram=None, ccr=0):
        ram = {**(ram or {}), 0x334: struct.pack(">H", ccr)}
        env = dict(os.environ, T_PC="%x" % self.entries[where], T_REGS=",".join("%s=%x" % kv for kv in {"a7": 0x01000000, **(regs or {})}.items()),
                   T_RAM=",".join("%x=%s" % (a, v.hex() if isinstance(v, (bytes, bytearray)) else v) for a, v in ram.items()))
        r = subprocess.run([str(self.work / "t"), "--instruction-budget", "20000"], capture_output=True, text=True, env=env, timeout=120)
        m = re.search(r"OUT (.*)", r.stderr); assert m, r.stderr[-500:] + r.stdout[-300:]
        d = dict(kv.split("=") for kv in m.group(1).split())
        out = {k: int(v, 16) for k, v in d.items() if k[0] in "da" and len(k) == 2 or k in ("pc", "hash", "sr")}
        out["state"] = bytes.fromhex(d["ram"]); out["log"] = bytes.fromhex(d["log"])
        out["above"] = bytes.fromhex(d["hi"]); out["ccr"] = struct.unpack(">H", out["log"][0x38:0x3A])[0] & 0x1F; return out
