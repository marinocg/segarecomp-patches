"""Release lifecycle with SYNTHETIC packages, driven through the same scripts the workflows run (no commercial data, no network).

Release A (v1.0.0) is prepared and published, release B (v1.1.0) is prepared after it with a higher version of the same package id and a new
package; both stay represented and independently verifiable, the published A is immutable, and unpublished packages never reach the catalog.
"""
import hashlib, json, pathlib, re, shutil, subprocess, sys, tempfile, unittest, zipfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
S = ROOT / "scripts"
REPO = "https://github.com/marinocg/segarecomp-patches"
FAKE_WRITER = '''import zipfile
def write_zip(path, files):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for name, data in files:
            i = zipfile.ZipInfo(name, (2020, 1, 1, 0, 0, 0)); i.compress_type = zipfile.ZIP_DEFLATED; z.writestr(i, data)
'''


def sha(b): return hashlib.sha256(b).hexdigest()


def run(*args, cwd=None, check=False):
    r = subprocess.run([sys.executable, *map(str, args)], cwd=cwd, capture_output=True, text=True)
    if check and r.returncode: raise AssertionError(f"{args}: {r.stdout}{r.stderr}")
    return r


def git(d, *a): return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false", "-c", "tag.gpgsign=false", *a], cwd=d, check=True, capture_output=True, text=True).stdout.strip()


class Synthetic:
    """A throw-away repository: the real governance files and schemas, one fabricated game, a fake deterministic package writer."""
    GAME = "patches/genesis/synthetic-lifecycle"

    def __init__(self, test):
        self.d = pathlib.Path(tempfile.mkdtemp()); test.addCleanup(shutil.rmtree, self.d)
        self.tmp = pathlib.Path(tempfile.mkdtemp()); test.addCleanup(shutil.rmtree, self.tmp)   # build outputs live outside the repository under test
        # stubs of every file check_repo requires (no copied Markdown, so no links to files this throw-away repository lacks)
        text = (S / "check_repo.py").read_text(); block = text[text.index('for f in ("README.md"'):text.index("    for p in tracked(root)")]
        for rel in re.findall(r'"([A-Za-z0-9_./-]+\.(?:md|json|yml|txt))"', block):
            f = self.d / rel; f.parent.mkdir(parents=True, exist_ok=True); f.write_text("stub\n")
        (self.d / ".github").mkdir(exist_ok=True); (self.d / ".github/CODEOWNERS").write_text("* @x\n")
        (self.d / "docs/repository-settings.md").write_text("check / repository\nsite / build\nsite / samples\n")
        (self.d / "LICENSE").write_text("MPL stub\n"); (self.d / "LICENSES").mkdir(exist_ok=True); (self.d / "LICENSES/MIT.txt").write_text("MIT stub\n")
        shutil.copytree(ROOT / "catalog/schema", self.d / "catalog/schema", dirs_exist_ok=True); (self.d / "scripts").mkdir(exist_ok=True); shutil.copy(ROOT / "scripts/SEGAPATCH_REF", self.d / "scripts/SEGAPATCH_REF")
        (self.d / "docs/release-notes").mkdir(parents=True, exist_ok=True)
        (self.d / "catalog").mkdir(exist_ok=True); (self.d / "patches/genesis").mkdir(parents=True)
        (self.d / "writer.py").write_text(FAKE_WRITER)
        git(self.d, "init", "-q", "-b", "main")
        self.writer_ref = "a" * 40

    @property
    def game(self): return self.d / self.GAME

    def sources(self, pid, version, seed):
        (self.game / "source").mkdir(parents=True, exist_ok=True)
        bps = f"BPS-{pid}-{version}-{seed}".encode(); src = f"{seed}".encode()
        manifest = {"id": pid, "version": version, "source_sha256": sha(b"src" + src), "payloads": {"rom": {"sha256": sha(bps), "target_sha256": sha(b"dst" + src)}}}
        mb = json.dumps(manifest, sort_keys=True).encode()
        (self.game / "source" / f"{pid}.bps").write_bytes(bps); (self.game / "source" / f"{pid}.manifest.json").write_bytes(mb)
        out = self.d / "_tmp.segapatch"; sys.path.insert(0, str(self.d)); import importlib; w = importlib.import_module("writer"); w.write_zip(out, [("manifest.json", mb), ("game.bps", bps)])
        data = out.read_bytes(); out.unlink()
        return {"id": pid, "version": version, "name": f"Synthetic {pid} {version}", "revision": "SYN", "region": "none", "package_file": f"{pid}.segapatch",
                "package_sha256": sha(data), "package_size": len(data), "package_identity": sha(mb), "schema_version": 1, "native_abi": None, "capabilities": [],
                "trust": "data-only", "executable_code": False, "source_image_sha256": sha(b"src" + src), "patched_image_sha256": sha(b"dst" + src),
                "bps_sha256": sha(bps), "native_source_sha256": None, "author": "synthetic", "license": "not applicable (data-only BPS)", "license_declared_in_package": False,
                "source": None, "authoring_revision": "x", "evidence_tier": "synthetic-only", "gameplay": "unchanged", "supported_scope": "A fabricated package.",
                "limitations": ["Synthetic."], "bps": {"path": f"source/{pid}.bps", "sha256": sha(bps)}}

    def asset(self, p, tag): p["asset"] = {"name": p["package_file"], "url": f"{REPO}/releases/download/{tag}/{p['package_file']}"}; return p

    def write_release(self, doc):
        (self.game).mkdir(parents=True, exist_ok=True); (self.game / "README.md").write_text("# Synthetic\n")
        (self.game / "release.json").write_text(json.dumps(doc, indent=2) + "\n")

    def doc(self, tag, status, packages, commit=None):
        sr = {"repository": REPO}; 
        if commit: sr.update(commit=commit, tag=tag)
        return {"release_format": 1, "platform": "genesis", "source_identity_kind": "cartridge-image-sha256", "bios_requirement": "none", "game": "Synthetic Lifecycle",
                "release": tag, "status": status, "source_revision": sr, "build": {"writer": "segapatch.py write_zip", "writer_ref": self.writer_ref, "deterministic": True}, "packages": packages}

    def notes(self, tag): (self.d / f"docs/release-notes/{tag}.md").write_text(f"Synthetic {tag}\n")
    def catalog(self): run(S / "build_catalog.py", "--root", self.d, check=True)
    def commit(self, msg): git(self.d, "add", "-A"); git(self.d, "commit", "-qm", msg); return git(self.d, "rev-parse", "HEAD")
    def build(self, tag, out): return run(S / "build_packages.py", "--root", self.d, "--segapatch", self.d / "writer.py", "--release", tag, "--out", out)
    def assets(self, tag, directory): return run(S / "check_repo.py", "--root", self.d, "--assets", directory, "--release", tag)
    def checks(self):
        return [run(S / n, "--root", self.d) for n in ("check_repo.py", "validate_catalog.py", "verify_provenance.py")] + [run(S / "build_catalog.py", "--root", self.d, "--check")]


def state(is_draft): 
    p = pathlib.Path(tempfile.mkdtemp()) / "state.json"; p.write_text(json.dumps({"tagName": "x", "isDraft": is_draft})); return p


class Lifecycle(unittest.TestCase):
    def release_a(self):
        s = Synthetic(self); self.s = s
        pk = s.asset(s.sources("synth-demo", "1.0.0", "a"), "v1.0.0")
        s.write_release(s.doc("v1.0.0", "prepared", [pk])); s.notes("v1.0.0"); s.catalog(); s.commit("prepare A")
        return s, pk

    def publish_a(self, s):
        commit = git(s.d, "rev-parse", "HEAD"); git(s.d, "tag", "v1.0.0", commit)
        run(S / "prepare_release.py", "--root", s.d, "publish", "--tag", "v1.0.0", "--commit", commit, check=True)
        s.catalog(); s.commit("publish A"); return commit

    def release_b(self, s):
        run(S / "prepare_release.py", "--root", s.d, "begin", "--tag", "v1.1.0", "--game", s.GAME, check=True)
        doc = json.loads((s.game / "release.json").read_text())
        new = s.asset(s.sources("synth-demo", "1.1.0", "b"), "v1.1.0"); other = s.asset(s.sources("synth-other", "1.0.0", "c"), "v1.1.0")
        doc["packages"] += [new, other]; s.write_release(doc); s.notes("v1.1.0"); s.catalog(); s.commit("prepare B")

    # --- release A -------------------------------------------------------------------------------------------------------------
    def test_a_prepared_is_not_advertised_then_published(self):
        s, pk = self.release_a()
        self.assertEqual(json.loads((s.d / "catalog/index.json").read_text())["packages"], [], "a prepared release must not appear in the catalog")
        self.assertEqual(run(S / "release_guard.py", "--root", s.d, "--tag", "v1.0.0", "--release-state", "none").returncode, 0)
        for r in s.checks(): self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        out = s.tmp / "outA"; r = s.build("v1.0.0", out); self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        r = s.assets("v1.0.0", out); self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.publish_a(s)
        cat = json.loads((s.d / "catalog/index.json").read_text())["packages"]
        self.assertEqual([(p["id"], p["version"], p["release"]) for p in cat], [("synth-demo", "1.0.0", "v1.0.0")])
        for r in s.checks(): self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    # --- release B after A -----------------------------------------------------------------------------------------------------
    def test_b_after_a_keeps_both_and_supersedes_additively(self):
        s, _ = self.release_a(); self.publish_a(s); baseline = json.loads((s.d / "catalog/index.json").read_text())
        self.release_b(s)
        g = run(S / "release_guard.py", "--root", s.d, "--tag", "v1.1.0", "--release-state", "none"); self.assertEqual(g.returncode, 0, g.stderr)
        self.assertIn("synth-demo@1.1.0 supersedes published synth-demo@1.0.0", g.stdout)
        self.assertEqual([p["version"] for p in json.loads((s.d / "catalog/index.json").read_text())["packages"]], ["1.0.0"], "B is prepared: not advertised yet")
        for r in s.checks(): self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        outb = s.tmp / "outB"; self.assertEqual(s.build("v1.1.0", outb).returncode, 0)
        self.assertEqual(s.assets("v1.1.0", outb).returncode, 0, "B's assets verify without A's")
        # A is rebuilt from Git at its pinned commit although B replaced the working-tree sources
        outa = s.tmp / "outA2"; r = s.build("v1.0.0", outa); self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        r = s.assets("v1.0.0", outa); self.assertEqual(r.returncode, 0, "A's assets verify without B's: " + r.stdout + r.stderr)
        # publish B, record supersession additively
        commit = git(s.d, "rev-parse", "HEAD"); git(s.d, "tag", "v1.1.0", commit)
        run(S / "prepare_release.py", "--root", s.d, "publish", "--tag", "v1.1.0", "--commit", commit, check=True)
        run(S / "prepare_release.py", "--root", s.d, "supersede", "--old", "synth-demo@1.0.0", "--new", "synth-demo@1.1.0", check=True)
        s.catalog(); s.commit("publish B")
        cat = json.loads((s.d / "catalog/index.json").read_text()); ids = [(p["id"], p["version"], p["release"]) for p in cat["packages"]]
        self.assertEqual(ids, [("synth-demo", "1.0.0", "v1.0.0"), ("synth-demo", "1.1.0", "v1.1.0"), ("synth-other", "1.0.0", "v1.1.0")])
        old = [p for p in cat["packages"] if p["version"] == "1.0.0"][0]; was = [p for p in baseline["packages"]][0]
        self.assertEqual({k: v for k, v in old.items() if k != "superseded_by"}, was, "the historical entry is unchanged except the additive pointer")
        self.assertEqual(old["superseded_by"], "synth-demo@1.1.0")
        base = s.tmp / "base.json"; base.write_text(json.dumps(baseline))
        r = run(S / "validate_catalog.py", "--root", s.d, "--baseline", base); self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        for r in s.checks(): self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    # --- immutability and failures ---------------------------------------------------------------------------------------------
    def test_published_release_cannot_be_rerun_or_replaced(self):
        s, _ = self.release_a(); self.publish_a(s)
        r = run(S / "release_guard.py", "--root", s.d, "--tag", "v1.0.0", "--release-state", state(False)); self.assertEqual(r.returncode, 1); self.assertIn("immutable", r.stderr)
        r = run(S / "release_guard.py", "--root", s.d, "--tag", "v1.0.0", "--release-state", "none"); self.assertEqual(r.returncode, 1); self.assertIn("deleted or inconsistent", r.stderr)
        r = run(S / "release_guard.py", "--root", s.d, "--tag", "v1.0.0", "--release-state", state(True)); self.assertEqual(r.returncode, 1); self.assertIn("inconsistent", r.stderr)

    def test_changing_a_published_digest_is_rejected(self):
        s, _ = self.release_a(); self.publish_a(s); baseline = (s.d / "catalog/index.json").read_text()
        doc = json.loads((s.game / "release.json").read_text()); doc["packages"][0]["package_sha256"] = "9" * 64; s.write_release(doc); s.catalog()
        (s.tmp / "base.json").write_text(baseline)
        r = run(S / "validate_catalog.py", "--root", s.d, "--baseline", s.tmp / "base.json"); self.assertEqual(r.returncode, 1); self.assertIn("package_sha256", r.stderr)

    def test_published_version_cannot_be_released_again_or_lowered(self):
        s, _ = self.release_a(); self.publish_a(s)
        run(S / "prepare_release.py", "--root", s.d, "begin", "--tag", "v1.1.0", "--game", s.GAME, check=True)
        doc = json.loads((s.game / "release.json").read_text()); same = s.asset(s.sources("synth-demo", "1.0.0", "z"), "v1.1.0"); doc["packages"].append(same); s.write_release(doc); s.notes("v1.1.0")
        r = run(S / "release_guard.py", "--root", s.d, "--tag", "v1.1.0", "--release-state", "none"); self.assertEqual(r.returncode, 1); self.assertIn("does not supersede", r.stderr)
        self.assertEqual(run(S / "validate_catalog.py", "--root", s.d).returncode, 1, "the same (id, version) twice is a duplicate")

    def test_draft_requires_deliberate_maintainer_action(self):
        s, _ = self.release_a()
        r = run(S / "release_guard.py", "--root", s.d, "--tag", "v1.0.0", "--release-state", state(True)); self.assertEqual(r.returncode, 1); self.assertIn("delete it deliberately", r.stderr)
        r = run(S / "release_guard.py", "--root", s.d, "--tag", "v1.0.0", "--release-state", state(False)); self.assertEqual(r.returncode, 1); self.assertIn("scripts/prepare_release.py publish", r.stderr)

    def test_unknown_tag_has_no_metadata(self):
        s, _ = self.release_a(); r = run(S / "release_guard.py", "--root", s.d, "--tag", "v9.9.9", "--release-state", "none"); self.assertEqual(r.returncode, 1); self.assertIn("no packages are recorded", r.stderr)

    def test_wrong_digest_and_missing_asset_fail(self):
        s, _ = self.release_a(); out = s.tmp / "out"; s.build("v1.0.0", out)
        (out / "synth-demo.segapatch").write_bytes(b"tampered")
        r = s.assets("v1.0.0", out); self.assertEqual(r.returncode, 1); self.assertIn("asset SHA-256 differs", r.stderr)
        (out / "synth-demo.segapatch").unlink(); r = s.assets("v1.0.0", out); self.assertEqual(r.returncode, 1); self.assertIn("asset not found", r.stderr)

    def test_assets_of_another_release_are_not_a_false_failure_but_a_stray_file_is(self):
        s, _ = self.release_a(); self.publish_a(s); self.release_b(s)
        outa = s.tmp / "outA"; s.build("v1.0.0", outa); self.assertEqual(s.assets("v1.0.0", outa).returncode, 0, "B's packages in the metadata do not fail A's verification")
        (outa / "synth-other.segapatch").write_bytes(b"x")
        r = s.assets("v1.0.0", outa); self.assertEqual(r.returncode, 1); self.assertIn("unexpected release assets", r.stderr)
        r = run(S / "check_repo.py", "--root", s.d, "--assets", outa); self.assertEqual(r.returncode, 1); self.assertIn("pass --release", r.stderr)

    def test_two_versions_of_one_id_pass_the_repository_checks(self):
        s, _ = self.release_a(); self.publish_a(s); self.release_b(s)
        r = run(S / "check_repo.py", "--root", s.d); self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_rebuild_release_script_verifies_each_release_with_its_writer(self):
        s, _ = self.release_a(); self.publish_a(s); self.release_b(s); url = (s.d / "writer.py").as_uri().replace("writer.py", "writer.py")
        r = run(S / "rebuild_release.py", "--root", s.d, "--all", "--work", s.tmp / "w", "--writer-url", url); self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue((s.tmp / "w/v1.0.0/SHA256SUMS").is_file() and (s.tmp / "w/v1.1.0/SHA256SUMS").is_file())
        self.assertEqual((s.tmp / "w/v1.0.0/SHA256SUMS").read_text().count("segapatch"), 1); self.assertEqual((s.tmp / "w/v1.1.0/SHA256SUMS").read_text().count("segapatch"), 2)
        r = run(S / "rebuild_release.py", "--root", s.d, "--release", "v9.9.9", "--work", s.tmp / "w2", "--writer-url", url); self.assertNotEqual(r.returncode, 0)

    def test_writer_ref_is_recorded_per_release(self):
        s, _ = self.release_a(); r = run(S / "build_packages.py", "--root", s.d, "--release", "v1.0.0", "--print-writer-ref"); self.assertEqual(r.stdout.strip(), s.writer_ref)


class RepositoryModel(unittest.TestCase):
    def test_the_published_v010_identities_are_unchanged(self):
        cat = json.loads((ROOT / "catalog/index.json").read_text())["packages"]
        self.assertEqual({(p["id"], p["version"], p["release"]) for p in cat}, {("sonic1-native-widescreen", "2.0.1", "v0.1.0"), ("sonic2-native-widescreen", "3.0.1", "v0.1.0"),
            ("sonic2-native-widescreen-rev01", "3.0.1", "v0.1.0"), ("sonic3k-native-widescreen", "1.0.1", "v0.1.0"), ("sor2-widescreen", "1.0.0", "v0.1.0")})
        self.assertIn("package_sha256", cat[0]); self.assertIn("636342c8a44516cc86bed4325c7f75d5721f0b38de8e852e2964a015566a5921", {p["package_sha256"] for p in cat})
        self.assertTrue(all(p["asset"]["url"].startswith(f"{REPO}/releases/download/v0.1.0/") for p in cat))


if __name__ == "__main__": unittest.main()
