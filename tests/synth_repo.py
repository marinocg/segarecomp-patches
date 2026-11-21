"""A throw-away repository for the lifecycle, selection and scalability tests: the real schemas and scripts, fabricated patches, a fake deterministic writer
and a fake product CLI (tests/fake_product_cli.py). No commercial data, no network."""
import hashlib, importlib, json, pathlib, re, shutil, subprocess, sys, tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
S = ROOT / "scripts"
REPO = "https://github.com/marinocg/segarecomp-patches"
PRODUCT_REF = "d" * 40
FAKE_WRITER = '''import os, zipfile
def write_zip(path, files):
    if os.environ.get("FAKE_WRITER_LOG"):
        with open(os.environ["FAKE_WRITER_LOG"], "a") as f: f.write(os.path.basename(str(path)) + "\\n")
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for name, data in files:
            i = zipfile.ZipInfo(name, (2020, 1, 1, 0, 0, 0)); i.compress_type = zipfile.ZIP_DEFLATED; z.writestr(i, data)
'''
MOD = '''[mod]
id = "%(id)s"
version = "%(version)s"
name = "Synthetic %(id)s"
license = "MIT"

[target]
platform = "genesis"

[[target.revision]]
label = "fixture"
sha256 = "%(image)s"

[[source]]
kind = "native-c11"
path = "src/provider.c"

[abi]
native = 2

[capabilities]
required = ["frame.work_ram", "overlay.rgba"]
'''


def sha(b): return hashlib.sha256(b).hexdigest()


def run(*args, cwd=None, check=False, env=None):
    import os
    r = subprocess.run([sys.executable, *map(str, args)], cwd=cwd, capture_output=True, text=True, env={**os.environ, **(env or {})})
    if check and r.returncode: raise AssertionError(f"{args}: {r.stdout}{r.stderr}")
    return r


def git(d, *a):
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false", "-c", "tag.gpgsign=false", *a], cwd=d, check=True, capture_output=True, text=True).stdout.strip()


class Synthetic:
    def __init__(self, test):
        self.d = pathlib.Path(tempfile.mkdtemp()); test.addCleanup(shutil.rmtree, self.d)
        self.tmp = pathlib.Path(tempfile.mkdtemp()); test.addCleanup(shutil.rmtree, self.tmp)   # build outputs live outside the repository under test
        text = (S / "check_repo.py").read_text(); block = text[text.index('for f in ("README.md"'):text.index("    for p in tracked(root)")]
        for rel in re.findall(r'"([A-Za-z0-9_./-]+\.(?:md|json|yml|txt))"', block):   # stubs of every file check_repo requires
            f = self.d / rel; f.parent.mkdir(parents=True, exist_ok=True); f.write_text("stub\n")
        (self.d / ".github/CODEOWNERS").write_text("* @x\n"); (self.d / "docs/repository-settings.md").write_text("check / repository\nsite / build\nsite / samples\n")
        (self.d / "LICENSE").write_text("MPL stub\n"); (self.d / "LICENSES").mkdir(exist_ok=True); (self.d / "LICENSES/MIT.txt").write_text("MIT stub\n")
        shutil.rmtree(self.d / "catalog/schema"); shutil.copytree(ROOT / "catalog/schema", self.d / "catalog/schema")
        (self.d / "scripts").mkdir(exist_ok=True); shutil.copy(ROOT / "scripts/SEGAPATCH_REF", self.d / "scripts/SEGAPATCH_REF"); (self.d / "scripts/PRODUCT_REF").write_text(PRODUCT_REF + "\n")
        (self.d / "docs/release-notes").mkdir(parents=True, exist_ok=True); (self.d / "patches").mkdir(); (self.d / "releases").mkdir()
        (self.d / "writer.py").write_text(FAKE_WRITER); self.writer = self.d / "writer.py"
        self.cli = self.tmp / "segarecomp"; shutil.copy(ROOT / "tests/fake_product_cli.py", self.cli); self.cli.chmod(0o755)
        self.mod_log, self.writer_log = self.tmp / "mod.log", self.tmp / "writer.log"
        self.env = {"FAKE_PRODUCT_LOG": str(self.mod_log), "FAKE_WRITER_LOG": str(self.writer_log)}
        self.writer_ref = "a" * 40; self.pub = {}
        self.write_publication(); run(S / "build_catalog.py", "--root", self.d, check=True)   # an empty catalog: nothing is published yet
        git(self.d, "init", "-q", "-b", "main")

    # --- layout and metadata -----------------------------------------------------------------------------------------------------
    def patch(self, game, name, platform="genesis"): return self.d / "patches" / platform / game / name

    def write_publication(self): (self.d / "publication.json").write_text(json.dumps({"publication_format": 1, "patches": self.pub}, indent=2) + "\n")

    def state(self, rel, state):
        self.pub[rel] = {"state": state, **({"review": "synthetic review"} if state == "eligible" else {})}; self.write_publication()

    def legacy_patch(self, game, name, pid, version, seed, state="eligible", tag=None):
        """A schema 1 patch with its source files and package.json entry (digests computed with the fake writer)."""
        d = self.patch(game, name); (d / "source").mkdir(parents=True, exist_ok=True); (d / "README.md").write_text(f"# {pid}\n")
        bps = f"BPS-{pid}-{version}-{seed}".encode(); src = f"{seed}".encode()
        mf = {"id": pid, "version": version, "source_sha256": sha(b"src" + src), "payloads": {"rom": {"sha256": sha(bps), "target_sha256": sha(b"dst" + src)}}}
        mb = json.dumps(mf, sort_keys=True).encode()
        (d / "source" / f"{pid}.bps").write_bytes(bps); (d / "source" / f"{pid}.manifest.json").write_bytes(mb)
        out = self.tmp / "_x.segapatch"; sys.path.insert(0, str(self.d)); w = importlib.import_module("writer"); w.write_zip(out, [("manifest.json", mb), ("game.bps", bps)]); data = out.read_bytes(); out.unlink()
        entry = {"id": pid, "version": version, "name": f"Synthetic {pid} {version}", "revision": "SYN", "region": "none", "package_file": f"{pid}.segapatch",
                 "package_sha256": sha(data), "package_size": len(data), "package_identity": sha(mb), "schema_version": 1, "native_abi": None, "capabilities": [],
                 "trust": "data-only", "executable_code": False, "source_image_sha256": sha(b"src" + src), "patched_image_sha256": sha(b"dst" + src),
                 "bps_sha256": sha(bps), "native_source_sha256": None, "author": "synthetic", "license": "not applicable (data-only BPS)", "license_declared_in_package": False,
                 "source": None, "authoring_revision": "x", "evidence_tier": "synthetic-only", "gameplay": "unchanged", "supported_scope": "A fabricated package.",
                 "limitations": ["Synthetic."], "bps": {"path": f"source/{pid}.bps", "sha256": sha(bps)},
                 "asset": {"name": f"{pid}.segapatch", "url": f"{REPO}/releases/download/{tag or 'vX'}/{pid}.segapatch"}}
        pj = d / "package.json"
        meta = json.loads(pj.read_text()) if pj.is_file() else {"package_format": 1, "platform": platform_of(d), "source_identity_kind": "cartridge-image-sha256", "bios_requirement": "none", "game": f"Synthetic {game}", "packages": []}
        meta["packages"] = [p for p in meta["packages"] if (p["id"], p["version"]) != (pid, version)] + [entry]; pj.write_text(json.dumps(meta, indent=2) + "\n")
        self.state(f"genesis/{game}/{name}", state)
        return entry

    def mod_patch(self, game, name, pid, version="0.1.0", state="candidate", pin=True):
        """A schema 3 project; when `pin`, recorded with `prepare_release.py pin` through the fake product CLI."""
        d = self.patch(game, name); (d / "src").mkdir(parents=True, exist_ok=True); (d / "README.md").write_text(f"# {pid}\n")
        (d / "mod.toml").write_text(MOD % {"id": pid, "version": version, "image": sha(pid.encode())}); (d / "src/provider.c").write_text(f"/* {pid} {version} */\n")
        self.state(f"genesis/{game}/{name}", state)
        if pin: self.pin(d)

    def pin(self, d, check=True):
        return run(S / "prepare_release.py", "--root", self.d, "pin", d.relative_to(self.d), "--segarecomp", self.cli, "--game", "Synthetic Game", "--gameplay", "unchanged",
                   "--scope", "A fabricated mod.", "--limitation", "Synthetic.", check=check, env=self.env)

    # --- lifecycle ---------------------------------------------------------------------------------------------------------------
    def begin(self, tag, *refs, check=True):
        args = [S / "prepare_release.py", "--root", self.d, "begin", "--tag", tag]
        for r in refs: args += ["--package", r]
        return run(*args, check=check)

    def notes(self, tag): (self.d / f"docs/release-notes/{tag}.md").write_text(f"Synthetic {tag}\n")
    def catalog(self): run(S / "build_catalog.py", "--root", self.d, check=True)
    def commit(self, msg): git(self.d, "add", "-A"); git(self.d, "commit", "-qm", msg, "--allow-empty"); return git(self.d, "rev-parse", "HEAD")

    def publish(self, tag):
        commit = git(self.d, "rev-parse", "HEAD"); git(self.d, "tag", tag, commit)
        run(S / "prepare_release.py", "--root", self.d, "publish", "--tag", tag, "--commit", commit, check=True); self.catalog(); self.commit(f"publish {tag}"); return commit

    def build(self, tag, out):
        return run(S / "build_packages.py", "--root", self.d, "--segapatch", self.writer, "--segarecomp", self.cli, "--segarecomp-ref", PRODUCT_REF, "--release", tag, "--out", out, env=self.env)

    def assets(self, tag, directory, cli=False):
        return run(S / "check_repo.py", "--root", self.d, "--assets", directory, "--release", tag, *(["--segarecomp", self.cli] if cli else []), env=self.env)

    def checks(self):
        return [run(S / n, "--root", self.d) for n in ("check_repo.py", "validate_catalog.py", "verify_provenance.py")] + [run(S / "build_catalog.py", "--root", self.d, "--check")]

    def catalog_entries(self): return json.loads((self.d / "catalog/index.json").read_text())["packages"]
    def mod_calls(self): return self.mod_log.read_text().splitlines() if self.mod_log.is_file() else []
    def writer_calls(self): return self.writer_log.read_text().splitlines() if self.writer_log.is_file() else []


def platform_of(d): return d.parent.parent.name


def state_file(is_draft):
    p = pathlib.Path(tempfile.mkdtemp()) / "state.json"; p.write_text(json.dumps({"tagName": "x", "isDraft": is_draft})); return p
