#!/usr/bin/env python3
"""Repository checks that need no commercial data.

  check_repo.py                       structure, metadata, links, forbidden content, source digests, catalog freshness (metadata only: builds nothing)
  check_repo.py --assets DIR --release TAG [--segarecomp BIN]
                                      also compare the downloaded assets of ONE release with its metadata (and, with the product CLI, `patch inspect` /
                                      `mod inspect`). Uses the product tooling; it is not a second package parser.
  check_repo.py --segarecomp BIN [--cc CC --sdk-dir DIR] [--changed-from REF]
                                      check/pack the schema 3 projects with the product tool: all of them, or only those changed since REF.
"""
import argparse, hashlib, json, pathlib, re, subprocess, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import build_catalog, lint_layout, release_meta, validate_catalog

HEX = re.compile(r"^[0-9a-f]{64}$")
FORBIDDEN_EXT = {".bin", ".gen", ".smd", ".sms", ".gg", ".iso", ".cue", ".img", ".rom", ".sfc", ".nes", ".z64", ".ips",
                 ".segapatch", ".zip", ".7z", ".rar", ".gz", ".tar", ".png.raw", ".vram", ".dump", ".sav", ".srm",
                 ".exe", ".dll", ".so", ".dylib", ".o", ".a", ".nsp", ".xci", ".pk3", ".wad"}
FORBIDDEN_TEXT = ["private-corpus", ".worktrees", "segarecomp-harness", "/root/dev"]
TEXT_EXT = {".md", ".json", ".py", ".yml", ".yaml", ".txt", ".toml", ".mjs", ".js", ".ts", ".astro", ".mdx", ".css", ".c", ".h", ".sh", ".cfg"}
MAX_BYTES = 512 * 1024
LOCKFILE_MAX_BYTES = 2 * 1024 * 1024   # the only larger tracked file: the site's npm lockfile (text, integrity hashes)
LOCKFILES = {"site/package-lock.json"}
# Credential-shaped strings. A tripwire for accidents; a leaked credential must still be revoked.
SECRET_PATTERNS = [
    ("private key block", re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP |ENCRYPTED )?PRIVATE KEY")),
    ("GitHub token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b|\bgithub_pat_[A-Za-z0-9_]{22,}\b")),
    ("npm token", re.compile(r"\bnpm_[A-Za-z0-9]{36}\b")),
    ("Slack token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}")),
    ("AWS access key id", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("Google API key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("credential assignment", re.compile(r"(?i)\b(?:password|passwd|secret|api[_-]?key|access[_-]?token|auth[_-]?token|cloudflare_api_token)\b\s*[:=]\s*[\"'][^\"'\s$<{]{16,}[\"']")),
]
REQUIRED_CHECKS = ("check / repository", "check / exec", "site / build", "site / samples")
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


def _latest(entries):
    """The newest version of each package id: the only one whose sources must still be in the working tree (older ones are verified at their pinned commit)."""
    best = {}
    for p in entries:
        if p.get("id") not in best or release_meta.semver(p.get("version")) > release_meta.semver(best[p["id"]].get("version")): best[p.get("id")] = p
    return list(best.values())


def check_legacy_patch(root, pt, errs):
    """A schema 1/2 patch: package.json agrees with the manifest, BPS and provider kept next to it (no game image is needed)."""
    d, rel = pt.dir, pt.meta
    if not (d / "README.md").is_file(): errs.append(f"{pt.rel}: README.md missing")
    if not isinstance(rel, dict): return
    for k in ("package_format", "platform", "source_identity_kind", "bios_requirement", "game", "packages"):
        if k not in rel: errs.append(f"{pt.rel}: package.json lacks {k}")
    for p in rel.get("packages", []):
        n = f"{pt.rel}/{p.get('id')}"
        for k in REQ_PKG:
            if k not in p: errs.append(f"{n}: lacks {k}")
        for k in ("package_sha256", "package_identity", "source_image_sha256", "patched_image_sha256", "bps_sha256"):
            if not HEX.match(str(p.get(k, ""))): errs.append(f"{n}: {k} is not a SHA-256")
        if p.get("trust") not in TRUST: errs.append(f"{n}: unknown trust class")
        if p.get("evidence_tier") not in TIERS: errs.append(f"{n}: unknown evidence tier")
        if not str(p.get("asset", {}).get("url", "")).startswith("https://"): errs.append(f"{n}: asset URL must be HTTPS")
        if p.get("asset", {}).get("name") != p.get("package_file"): errs.append(f"{n}: asset name differs from package_file")
        native = p.get("trust") == "trusted-native-source"
        lic_file = {"MIT": "LICENSES/MIT.txt", "MPL-2.0": "LICENSE"}.get(p.get("license"))
        if native and (not lic_file or not (root / lic_file).is_file()): errs.append(f"{n}: native provider needs an established license (MIT or MPL-2.0) with its text in the repository")
        if native != (p.get("schema_version") == 2) or native != bool(p.get("executable_code")):
            errs.append(f"{n}: schema/trust/executable_code inconsistent")
    for p in _latest(rel.get("packages", [])):   # older versions live at their pinned commit and are verified there (scripts/verify_provenance.py)
        n = f"{pt.rel}/{p.get('id')}"; native = p.get("trust") == "trusted-native-source"
        mp = d / "source" / f"{p.get('id')}.manifest.json"
        if not mp.is_file(): errs.append(f"{n}: source manifest missing")
        else:
            m = json.loads(mp.read_text()); pl = m.get("payloads", {})
            if (m.get("id"), m.get("version"), m.get("source_sha256"), pl.get("rom", {}).get("sha256"), pl.get("rom", {}).get("target_sha256")) != (
                    p.get("id"), p.get("version"), p.get("source_image_sha256"), p.get("bps_sha256"), p.get("patched_image_sha256")):
                errs.append(f"{n}: source manifest disagrees with package.json")
            pd = m.get("presentation_defaults", {})
            if (pd.get("widescreen"), pd.get("side_style")) != (p.get("default_widescreen"), p.get("default_side_style")): errs.append(f"{n}: manifest presentation defaults disagree with package.json")
            if pl.get("native", {}).get("sha256") != p.get("native_source_sha256"): errs.append(f"{n}: manifest native digest disagrees")
        bp = p.get("bps"); src = p.get("source")
        if not bp or not (d / bp["path"]).is_file(): errs.append(f"{n}: BPS file missing")
        elif sha(d / bp["path"]) != bp["sha256"] or bp["sha256"] != p.get("bps_sha256"): errs.append(f"{n}: BPS digest mismatch")
        elif (d / bp["path"]).stat().st_size > 4096: errs.append(f"{n}: BPS unexpectedly large")
        if native:
            if not src: errs.append(f"{n}: native package without source"); continue
            sp = d / src["path"]
            if not sp.is_file(): errs.append(f"{n}: missing {src['path']}")
            elif sha(sp) != src["sha256"] or src["sha256"] != p.get("native_source_sha256"): errs.append(f"{n}: source digest mismatch")
        elif src or (d / "source" / "provider.c").exists(): errs.append(f"{n}: data-only package must not carry source")


def check_mod_facts(root, pt, errs):
    """A schema 3 patch: its recorded package versions agree with mod.toml (the authority for what it declares) and with the optional tests/package.json pin.
    The package bytes themselves are the product tool's (check_mod_projects); nothing here rebuilds anything."""
    meta = pt.meta
    if meta is None: return
    mod = pt.mod
    if mod is None: errs.append(f"{pt.rel}: Python 3.11+ is required to read mod.toml"); return
    for k in ("package_format", "platform", "source_identity_kind", "bios_requirement", "game", "packages"):
        if k not in meta: errs.append(f"{pt.rel}: package.json lacks {k}")
    m = mod.get("mod", {}); revs = [{"label": r.get("label"), "sha256": r.get("sha256")} for r in (mod.get("target") or {}).get("revision", [])]
    for p in meta.get("packages", []):
        n = f"{pt.rel}/{p.get('id')}"
        for k in ("package_sha256", "package_identity"):
            if not HEX.match(str(p.get(k, ""))): errs.append(f"{n}: {k} is not a SHA-256")
        if "asset" in p or "package_file" in p and p["package_file"] != f"{p.get('id')}.segapatch": errs.append(f"{n}: asset and package_file are derived from the release, not stored")
        if p.get("evidence_tier") not in TIERS: errs.append(f"{n}: unknown evidence tier")
        if p.get("version") != m.get("version"): continue    # an older version: its sources are at its pinned commit (verified by verify_provenance.py / on-demand audit)
        for k, want in (("id", m.get("id")), ("name", m.get("name")), ("license", m.get("license")), ("native_abi", (mod.get("abi") or {}).get("native")),
                        ("capabilities", (mod.get("capabilities") or {}).get("required")), ("images", revs)):
            if p.get(k) != want: errs.append(f"{n}: {k} {p.get(k)!r} disagrees with mod.toml ({want!r})")
        if not p.get("build", {}).get("writer_ref"): errs.append(f"{n}: build.writer_ref missing")
        pin = pt.dir / "tests" / "package.json"
        if pin.is_file():
            want = json.loads(pin.read_text())
            if any(want.get(k) not in (None, p.get(k)) for k in ("package_identity", "package_sha256")): errs.append(f"{n}: package.json disagrees with tests/package.json (one source of the pin must win: update both from `prepare_release.py pin`)")


def check_selected(root, errs):
    """Reduced-scope guards for every release that is NOT yet published: its sources must still be the pinned, reviewed ones."""
    product = (root / "scripts" / "PRODUCT_REF").read_text().strip() if (root / "scripts" / "PRODUCT_REF").is_file() else ""
    for tag, rel in release_meta.releases(root).items():
        if rel["status"] == "published": continue
        for pk in rel["packages"]:
            if pk.is_mod and pk.build.get("writer_ref") != product:
                errs.append(f"{pk.ref}: build.writer_ref {pk.build.get('writer_ref')!r} is not the pinned product revision scripts/PRODUCT_REF ({product[:12]}): re-pin the package (prepare_release.py pin)")


def check(root, errs):
    for f in ("README.md", "LICENSE", "CONTRIBUTING.md", "SECURITY.md", "CODE_OF_CONDUCT.md", ".github/CODEOWNERS",
              ".github/PULL_REQUEST_TEMPLATE.md", ".github/ISSUE_TEMPLATE/config.yml", ".github/workflows/check.yml",
              "docs/installation.md", "docs/compatibility.md", "docs/creating-patches.md", "docs/releases.md", "docs/policy.md",
              "docs/repository-settings.md", "docs/publication-restrictions.md", "docs/layout-and-versioning.md", "catalog/index.json",
              "catalog/schema/catalog-1.schema.json", "catalog/schema/release-1.schema.json", "catalog/schema/catalog-2.schema.json",
              "catalog/schema/release-2.schema.json", "catalog/schema/package-1.schema.json", "publication.json",
              "docs/catalog-format.md", "docs/artifact-hosting.md",
              "docs/source-review.md", "docs/source-review.json", "docs/analytics-and-privacy.md", "docs/seo.md"):
        if not (root / f).is_file(): errs.append(f"missing {f}")
    for p in tracked(root):
        if not p.is_file(): continue
        rel = p.relative_to(root).as_posix()
        if rel.startswith(".github/") and p.suffix not in {".yml", ".yaml"}: pass
        too_big = p.stat().st_size > (LOCKFILE_MAX_BYTES if rel in LOCKFILES else MAX_BYTES)
        if p.suffix.lower() in FORBIDDEN_EXT or too_big or (p.suffix == ".bps" and not re.fullmatch(r"patches/[^/]+/[^/]+/[^/]+/(source/[a-z0-9-]+|bps/[a-z0-9-]+)\.bps", rel)):
            errs.append(f"forbidden file type or size: {rel}")
        if p.suffix in TEXT_EXT and rel not in ("scripts/check_repo.py", "tests/test_check_repo.py"):
            t = p.read_text(errors="replace")
            for m in FORBIDDEN_TEXT:
                if m in t: errs.append(f"private/harness marker {m!r} in {rel}")
            for what, rx in SECRET_PATTERNS:
                if rx.search(t): errs.append(f"possible secret ({what}) in {rel}")
            if p.suffix == ".md":
                for target in re.findall(r"\]\(([^)\s]+)\)", t):
                    if target.startswith(("http://",)): errs.append(f"non-HTTPS link in {rel}: {target}")
                    if target.startswith(("https://", "#", "mailto:")): continue
                    # Site-root routes (/security/) are validated against the built site by scripts/check_site_links.py.
                    if target.startswith("/") and rel.startswith("site/src/content/docs/"): continue
                    if not (p.parent / target.split("#")[0]).exists(): errs.append(f"broken link in {rel}: {target}")
    settings = root / "docs/repository-settings.md"
    if settings.is_file():
        for name in REQUIRED_CHECKS:
            if name not in settings.read_text(): errs.append(f"docs/repository-settings.md does not name required check {name!r}")
    lint_layout.lint(root, errs)
    for pt in release_meta.patches(root):
        if not pt.is_mod: check_legacy_patch(root, pt, errs)
        else: check_mod_facts(root, pt, errs)
    check_selected(root, errs)
    try: validate_catalog.validate_repository(root, errs)
    except Exception as e: errs.append(f"catalog schema: {e}")
    try:
        if (root / "catalog/index.json").read_text() != build_catalog.build(root): errs.append("catalog/index.json is stale")
    except Exception as e: errs.append(f"catalog: {e}")


def _cli(cli, *args):
    r = subprocess.run([cli, *map(str, args)], capture_output=True, text=True)
    try: return r.returncode, json.loads(r.stdout)
    except ValueError: return r.returncode, {"ok": False, "error": (r.stdout + r.stderr)[:200]}


def pack_mod_project(cli, d, out, extra=()):
    """The product's own `segarecomp mod build` (with a compiler and the SDK dir) or `mod pack` is the only package builder: returns (ok, info, bytes)."""
    rc, doc = _cli(cli, "mod", "build" if extra else "pack", d, "--out", out, *extra)   # `mod build` = check + the host-compiled native units (strict flags) + pack; `mod pack` needs no compiler
    return rc == 0 and doc.get("ok") is True, doc, (pathlib.Path(out).read_bytes() if pathlib.Path(out).is_file() else b"")


def changed_patches(root, ref):
    """Patch directories (patches/<platform>/<game>/<patch>) touched between `ref` and the working tree: the only projects a routine pull request must rebuild."""
    return sorted({"/".join(l.split("/")[:4]) for l in release_meta.changed_paths(root, ref) if l.startswith("patches/") and l.count("/") >= 3})


def projects_to_validate(root, ref):
    """Schema 3 project directories a pull request must check and pack: those it changed, plus those of the prepared releases it AFFECTS (the same selection
    rebuild_release.py --affected-from uses: release_meta.affected_tags, which expands to every prepared release when shared build/validation code changed).
    Unaffected prepared releases and published ones contribute nothing."""
    tags = release_meta.affected_tags(root, ref); rels = release_meta.releases(root)
    return set(changed_patches(root, ref)) | {pk.patch.path for t in tags for pk in rels[t]["packages"] if pk.is_mod}


def check_mod_projects(root, cli, errs, extra=(), only=None):
    """Schema 3 projects against the product tool: `mod check` accepts them, `mod pack` is deterministic, and the recorded pin (package.json entry of the
    mod.toml version, else tests/package.json) matches, so a changed source byte fails. `only` restricts the work to those patch directories (the changed ones
    in a pull request); nothing else is rebuilt. Nothing here is a release: no asset, no catalog entry, no SHA256SUMS line."""
    import tempfile
    for d in lint_layout.mod_projects(root):
        n = d.relative_to(root).as_posix()
        if only is not None and n not in only: continue
        rc, doc = _cli(cli, "mod", "check", d, *extra)
        if rc != 0 or doc.get("ok") is not True: errs.append(f"{n}: segarecomp mod check refused the project: {doc.get('error', doc)}"); continue
        with tempfile.TemporaryDirectory() as t:
            ok1, i1, b1 = pack_mod_project(cli, d, pathlib.Path(t) / "a.segapatch", extra)
            ok2, i2, b2 = pack_mod_project(cli, d, pathlib.Path(t) / "b.segapatch", extra)
        if not (ok1 and ok2): errs.append(f"{n}: the product build failed: {i1.get('error', i2.get('error', ''))}"); continue
        if b1 != b2 or i1.get("package_identity") != i2.get("package_identity"): errs.append(f"{n}: package rebuild is not deterministic")
        pins = []
        pt = release_meta.Patch(root, d)
        version = (pt.mod or {}).get("mod", {}).get("version")
        for p in (pt.meta or {}).get("packages", []):
            if p.get("version") == version: pins.append(("package.json", p))
        if (d / "tests" / "package.json").is_file(): pins.append(("tests/package.json", json.loads((d / "tests" / "package.json").read_text())))
        for src, want in pins:
            if want.get("package_identity") != i1.get("package_identity"): errs.append(f"{n}: package identity differs from {src} (the sources changed)")
            if want.get("package_sha256") and want["package_sha256"] != hashlib.sha256(b1).hexdigest(): errs.append(f"{n}: package SHA-256 differs from {src}")
            if src == "package.json" and want.get("package_size") != len(b1): errs.append(f"{n}: package size differs from package.json")


def select_release(root, release, errs):
    """The packages of ONE collection release. Without --release this is only unambiguous while a single release exists."""
    rels = release_meta.releases(root)
    if release is None:
        if len(rels) != 1: errs.append(f"{len(rels)} releases are recorded ({', '.join(sorted(rels))}): pass --release TAG"); return None
        release = next(iter(rels))
    if release not in rels: errs.append(f"no packages are recorded for release {release}"); return None
    return rels[release]["packages"]


def check_assets(root, assets, cli, errs, release=None):
    """Verify the assets of one release against its own metadata. Other releases' packages are neither required nor allowed in this directory:
    their integrity is checked when THEY are verified (--release their tag), so a historical package can never be silently skipped or confused."""
    root = pathlib.Path(root); assets = pathlib.Path(assets)
    pkgs = select_release(root, release, errs)
    if pkgs is None: return
    sums = {}
    sf = assets / "SHA256SUMS"
    if not sf.is_file(): errs.append("SHA256SUMS is missing from the release assets")
    else:
        for l in sf.read_text().splitlines():
            h, _, name = l.partition("  "); sums[name.strip()] = h
    expected = set()
    for pk in pkgs:
        p = pk.p
        f = assets / pk.package_file; n = p["id"]; expected.add(pk.package_file)
        if not f.is_file(): errs.append(f"{n}: asset not found"); continue
        if sha(f) != p["package_sha256"]: errs.append(f"{n}: asset SHA-256 differs from package.json")
        if f.stat().st_size != p["package_size"]: errs.append(f"{n}: asset size differs")
        if sums.get(pk.package_file) != p["package_sha256"]: errs.append(f"{n}: SHA256SUMS missing or differs")
        if cli and pk.is_mod:   # a schema 3 archive is inspected with the product's `mod inspect` (the shipped `patch inspect` predates schema 3 and refuses it)
            r = subprocess.run([cli, "mod", "inspect", "--json", str(f)], capture_output=True, text=True)
            try: i = json.loads(r.stdout)
            except Exception: errs.append(f"{n}: mod inspect failed"); continue
            want = {"ok": True, "id": p["id"], "version": p["version"], "package_identity": p["package_identity"], "abi_native": p["native_abi"], "capabilities": p["capabilities"]}
            for k, v in want.items():
                if i.get(k) != v: errs.append(f"{n}: inspect {k} differs")
        elif cli:
            r = subprocess.run([cli, "patch", "inspect", str(f)], capture_output=True, text=True)
            try: i = json.loads(r.stdout)
            except Exception: errs.append(f"{n}: inspect failed"); continue
            want = {"ok": True, "id": p["id"], "version": p["version"], "schema_version": p["schema_version"],
                    "package_identity": p["package_identity"], "source_sha256": p["source_image_sha256"],
                    "target_sha256": p["patched_image_sha256"], "payload_sha256": p["bps_sha256"],
                    "executable_code": p["executable_code"], "native_source_sha256": p.get("native_source_sha256") or ""}
            for k, v in want.items():
                if i.get(k) != v: errs.append(f"{n}: inspect {k} differs")

    if sf.is_file() and set(sums) != expected: errs.append("SHA256SUMS does not list exactly the packages of this release")
    extra = {x.name for x in assets.iterdir()} - expected - {"SHA256SUMS"}
    if extra: errs.append(f"unexpected release assets: {sorted(extra)}")


def main(argv=None):
    ap = argparse.ArgumentParser(); ap.add_argument("--assets"); ap.add_argument("--release", help="collection release tag the --assets directory belongs to"); ap.add_argument("--segarecomp"); ap.add_argument("--sdk-dir"); ap.add_argument("--cc"); ap.add_argument("--root", default=str(build_catalog.ROOT))
    ap.add_argument("--changed-from", metavar="REF", help="only check/pack the schema 3 projects changed since REF (a pull request's base)")
    a = ap.parse_args(argv); root = pathlib.Path(a.root); errs = []
    check(root, errs)
    if a.assets: check_assets(root, pathlib.Path(a.assets), a.segarecomp, errs, a.release)
    if a.segarecomp and lint_layout.mod_projects(root):   # schema 3 projects need the shipped product tool (mod check / mod pack), compiled with its own host-owned flags
        only = projects_to_validate(root, a.changed_from) if a.changed_from else None   # None = every project (explicit audit, or a first push without a base)
        check_mod_projects(root, a.segarecomp, errs, [x for k, v in (("--cc", a.cc), ("--sdk-dir", a.sdk_dir)) if v for x in (k, v)], only)
    for e in errs: print("FAIL:", e, file=sys.stderr)
    print("ok" if not errs else f"{len(errs)} problem(s)")
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
