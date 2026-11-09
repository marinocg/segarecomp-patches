#!/usr/bin/env python3
"""ROM-free synthetic validation (docs/layout-and-versioning.md).

  synthetic_fixture.py --segapatch PATH [--provider provider.c] [--update]
  synthetic_fixture.py --write-images DIR

Fabricates a tiny image and a modified target (deterministic bytes, no relation to any title), builds a schema 1 package and, when
--provider is given, a native-only schema 2 package with the product's pinned segapatch.py, applies both with its reference reader and
checks every digest against tests/synthetic/expected.json. Writes nothing outside a temporary directory unless --update rewrites the
expectations (a deliberate, reviewed act).
"""
import argparse, hashlib, json, pathlib, subprocess, sys, tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
EXPECTED = ROOT / "tests/synthetic/expected.json"


def sha(b): return hashlib.sha256(b).hexdigest()


def fabricate():
    """Deterministic 8 KiB image: SHA-256 hash chain, with a Genesis-style header marker. Not derived from any game."""
    out = bytearray(); h = b"segarecomp-patches synthetic fixture v1"
    while len(out) < 8192: h = hashlib.sha256(h).digest(); out += h
    out = bytearray(out[:8192]); out[0x100:0x110] = b"SEGA MEGA DRIVE "
    tgt = bytearray(out); tgt[0x400:0x420] = bytes(range(32)); tgt[0x1000:0x1004] = b"\xde\xad\xbe\xef"
    return bytes(out), bytes(tgt)


def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode: raise SystemExit(f"command failed: {' '.join(map(str, cmd))}\n{r.stdout}{r.stderr}")
    return r


def build(segapatch, provider):
    src, tgt = fabricate(); got = {"source_sha256": sha(src), "target_sha256": sha(tgt)}
    with tempfile.TemporaryDirectory() as tmp:
        t = pathlib.Path(tmp); (t / "s.bin").write_bytes(src); (t / "t.bin").write_bytes(tgt)
        py = [sys.executable, str(segapatch)]
        run(py + ["create", "--source", t / "s.bin", "--target", t / "t.bin", "--id", "synthetic-demo", "--name", "Synthetic demo",
                  "--version", "1.0.0", "--out", t / "d.segapatch"])
        run(py + ["apply", t / "d.segapatch", "--source", t / "s.bin", "--out", t / "o.bin"])
        if (t / "o.bin").read_bytes() != tgt: raise SystemExit("schema 1 round trip does not reproduce the target")
        got["schema1_package_sha256"] = sha((t / "d.segapatch").read_bytes())
        got["schema1_bps_roundtrip_sha256"] = sha((t / "o.bin").read_bytes())
        again = t / "d2.segapatch"
        run(py + ["create", "--source", t / "s.bin", "--target", t / "t.bin", "--id", "synthetic-demo", "--name", "Synthetic demo",
                  "--version", "1.0.0", "--out", again])
        if again.read_bytes() != (t / "d.segapatch").read_bytes(): raise SystemExit("package build is not deterministic")
        if provider:
            run(py + ["create", "--source", t / "s.bin", "--id", "synthetic-native", "--name", "Synthetic native", "--version", "1.0.0",
                      "--native-source", provider, "--native-caps", "frame.work_ram,frame.vdp,scenery.words,overlay.rgba",
                      "--author", "segarecomp-patches", "--license", "MIT", "--out", t / "n.segapatch"])
            run(py + ["apply", t / "n.segapatch", "--source", t / "s.bin", "--out", t / "n.bin"])
            if (t / "n.bin").read_bytes() != src: raise SystemExit("native-only package must leave the image unchanged")
            got["schema2_package_sha256"] = sha((t / "n.segapatch").read_bytes())
            got["provider_sha256"] = sha(pathlib.Path(provider).read_bytes())
        bad = bytearray(src); bad[7] ^= 1; (t / "bad.bin").write_bytes(bad)
        r = subprocess.run(py + ["apply", t / "d.segapatch", "--source", t / "bad.bin", "--out", t / "x.bin"], capture_output=True, text=True)
        if r.returncode == 0 or (t / "x.bin").exists(): raise SystemExit("a wrong image must be refused and leave no output")
        got["wrong_image_refused"] = True
    return got


def main(argv=None):
    ap = argparse.ArgumentParser(); ap.add_argument("--segapatch"); ap.add_argument("--provider"); ap.add_argument("--update", action="store_true")
    ap.add_argument("--write-images", metavar="DIR", help="write synthetic.bin and synthetic-target.bin to DIR and exit (used by the getting-started guide)")
    a = ap.parse_args(argv)
    if a.write_images:
        d = pathlib.Path(a.write_images); d.mkdir(parents=True, exist_ok=True); src, tgt = fabricate()
        (d / "synthetic.bin").write_bytes(src); (d / "synthetic-target.bin").write_bytes(tgt); print("wrote", d / "synthetic.bin", d / "synthetic-target.bin"); return 0
    if not a.segapatch: ap.error("--segapatch is required")
    got = build(pathlib.Path(a.segapatch), a.provider)
    if a.update:
        EXPECTED.parent.mkdir(parents=True, exist_ok=True); EXPECTED.write_text(json.dumps(got, indent=2, sort_keys=True) + "\n"); print("updated", EXPECTED); return 0
    want = json.loads(EXPECTED.read_text()); bad = [k for k in sorted(got) if want.get(k) != got[k]] + [k for k in want if k not in got]
    for k in bad: print(f"FAIL: {k}: expected {want.get(k)!r}, got {got.get(k)!r}", file=sys.stderr)
    print("ok" if not bad else f"{len(bad)} problem(s)"); return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
