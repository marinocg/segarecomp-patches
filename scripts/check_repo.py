#!/usr/bin/env python3
"""Repository checks that need no commercial data.

  check_repo.py                       structure, metadata, links, forbidden content, source digests, catalog freshness
  check_repo.py --assets DIR [--segarecomp BIN]
                                      also compare downloaded release assets with release.json (and, with the shipped CLI,
                                      `segarecomp patch inspect`). Uses the shipped tooling; it is not a second package parser.
"""
import argparse, hashlib, json, pathlib, re, subprocess, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import build_catalog

HEX = re.compile(r"^[0-9a-f]{64}$")
FORBIDDEN_EXT = {".bin", ".gen", ".smd", ".sms", ".gg", ".iso", ".cue", ".img", ".rom", ".sfc", ".nes", ".z64", ".bps", ".ips",
                 ".segapatch", ".zip", ".7z", ".rar", ".gz", ".tar", ".png.raw", ".vram", ".dump", ".sav", ".srm"}
FORBIDDEN_TEXT = ["private-corpus", ".worktrees", "segarecomp-harness", "/root/dev"]
TEXT_EXT = {".md", ".json", ".py", ".yml", ".yaml", ".txt"}
MAX_BYTES = 512 * 1024
REQ_PKG = ["id", "version", "revision", "region", "package_file", "package_sha256", "package_size", "package_identity", "schema_version",
           "trust", "executable_code", "source_image_sha256", "patched_image_sha256", "bps_sha256", "license", "evidence_tier",
           "supported_scope", "limitations", "gameplay", "asset"]
TRUST = {"data-only", "trusted-native-source"}
TIERS = {"synthetic-only", "maintainer-attested", "automated"}


def sha(p): return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()


def tracked(root):
    out = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard"], cwd=root, capture_output=True, text=True)
    if out.returncode == 0 and out.stdout.strip():
        return [root / l for l in out.stdout.splitlines()]
    return [p for p in root.rglob("*") if p.is_file() and ".git" not in p.parts]


def check(root, errs):
    for f in ("README.md", "LICENSE", "CONTRIBUTING.md", "SECURITY.md", "docs/installation.md", "docs/compatibility.md",
              "docs/creating-patches.md", "docs/releases.md", "catalog/index.json"):
        if not (root / f).is_file(): errs.append(f"missing {f}")
    for p in tracked(root):
        if not p.is_file(): continue
        rel = p.relative_to(root).as_posix()
        if rel.startswith(".github/") and p.suffix not in {".yml", ".yaml"}: pass
        if p.suffix.lower() in FORBIDDEN_EXT or p.stat().st_size > MAX_BYTES:
            errs.append(f"forbidden file type or size: {rel}")
        if p.suffix in TEXT_EXT and rel not in ("scripts/check_repo.py", "tests/test_check_repo.py"):
            t = p.read_text(errors="replace")
            for m in FORBIDDEN_TEXT:
                if m in t: errs.append(f"private/harness marker {m!r} in {rel}")
            if p.suffix == ".md":
                for target in re.findall(r"\]\(([^)\s]+)\)", t):
                    if target.startswith(("http://",)): errs.append(f"non-HTTPS link in {rel}: {target}")
                    if target.startswith(("https://", "#", "mailto:")): continue
                    if not (p.parent / target.split("#")[0]).exists(): errs.append(f"broken link in {rel}: {target}")
    seen = set()
    for rj in sorted((root / "patches").glob("*/*/release.json")):
        d = rj.parent; rel = json.loads(rj.read_text())
        if not (d / "README.md").is_file(): errs.append(f"{d.name}: README.md missing")
        for k in ("release_format", "platform", "source_identity_kind", "bios_requirement", "game", "release", "packages"):
            if k not in rel: errs.append(f"{d.name}: release.json lacks {k}")
        for p in rel.get("packages", []):
            n = f"{d.name}/{p.get('id')}"
            for k in REQ_PKG:
                if k not in p: errs.append(f"{n}: lacks {k}")
            if p.get("id") in seen: errs.append(f"{n}: duplicate id")
            seen.add(p.get("id"))
            for k in ("package_sha256", "package_identity", "source_image_sha256", "patched_image_sha256", "bps_sha256"):
                if not HEX.match(str(p.get(k, ""))): errs.append(f"{n}: {k} is not a SHA-256")
            if p.get("trust") not in TRUST: errs.append(f"{n}: unknown trust class")
            if p.get("evidence_tier") not in TIERS: errs.append(f"{n}: unknown evidence tier")
            if not str(p.get("asset", {}).get("url", "")).startswith("https://"): errs.append(f"{n}: asset URL must be HTTPS")
            if p.get("asset", {}).get("name") != p.get("package_file"): errs.append(f"{n}: asset name differs from package_file")
            native = p.get("trust") == "trusted-native-source"
            if native != (p.get("schema_version") == 2) or native != bool(p.get("executable_code")):
                errs.append(f"{n}: schema/trust/executable_code inconsistent")
            src = p.get("source")
            if native:
                if not src: errs.append(f"{n}: native package without source"); continue
                sp = d / src["path"]
                if not sp.is_file(): errs.append(f"{n}: missing {src['path']}")
                elif sha(sp) != src["sha256"] or src["sha256"] != p.get("native_source_sha256"): errs.append(f"{n}: source digest mismatch")
            elif src or (d / "source").exists(): errs.append(f"{n}: data-only package must not carry source")
    try:
        if (root / "catalog/index.json").read_text() != build_catalog.build(root): errs.append("catalog/index.json is stale")
    except Exception as e: errs.append(f"catalog: {e}")


def check_assets(root, assets, cli, errs):
    sums = {}
    sf = assets / "SHA256SUMS"
    if sf.is_file():
        for l in sf.read_text().splitlines():
            h, _, name = l.partition("  "); sums[name.strip()] = h
    for rj in sorted((root / "patches").glob("*/*/release.json")):
        for p in json.loads(rj.read_text())["packages"]:
            f = assets / p["package_file"]; n = p["id"]
            if not f.is_file(): errs.append(f"{n}: asset not found"); continue
            if sha(f) != p["package_sha256"]: errs.append(f"{n}: asset SHA-256 differs from release.json")
            if f.stat().st_size != p["package_size"]: errs.append(f"{n}: asset size differs")
            if sums and sums.get(p["package_file"]) != p["package_sha256"]: errs.append(f"{n}: SHA256SUMS differs")
            if cli:
                r = subprocess.run([cli, "patch", "inspect", str(f)], capture_output=True, text=True)
                try: i = json.loads(r.stdout)
                except Exception: errs.append(f"{n}: inspect failed"); continue
                want = {"ok": True, "id": p["id"], "version": p["version"], "schema_version": p["schema_version"],
                        "package_identity": p["package_identity"], "source_sha256": p["source_image_sha256"],
                        "target_sha256": p["patched_image_sha256"], "payload_sha256": p["bps_sha256"],
                        "executable_code": p["executable_code"], "native_source_sha256": p.get("native_source_sha256") or ""}
                for k, v in want.items():
                    if i.get(k) != v: errs.append(f"{n}: inspect {k} differs")


def main(argv=None):
    ap = argparse.ArgumentParser(); ap.add_argument("--assets"); ap.add_argument("--segarecomp"); ap.add_argument("--root", default=str(build_catalog.ROOT))
    a = ap.parse_args(argv); root = pathlib.Path(a.root); errs = []
    check(root, errs)
    if a.assets: check_assets(root, pathlib.Path(a.assets), a.segarecomp, errs)
    for e in errs: print("FAIL:", e, file=sys.stderr)
    print("ok" if not errs else f"{len(errs)} problem(s)")
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
