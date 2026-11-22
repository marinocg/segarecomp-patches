"""Release lifecycle with SYNTHETIC packages, driven through the same scripts the workflows run (no commercial data, no network).

Release A (v1.0.0) is prepared and published, release B (v1.1.0) is prepared after it with a higher version of the same package id and a new package;
both stay represented and independently verifiable, the published A is immutable, and unpublished packages never reach the catalog.
"""
import json, pathlib, sys, unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from synth_repo import S, REPO, Synthetic, git, run, state_file


class Lifecycle(unittest.TestCase):
    def release_a(self):
        s = Synthetic(self); s.legacy_patch("game", "demo", "synth-demo", "1.0.0", "a", tag="v1.0.0")
        s.begin("v1.0.0", "synth-demo@1.0.0"); s.notes("v1.0.0"); s.catalog(); s.commit("prepare A"); return s

    def release_b(self, s):
        s.legacy_patch("game", "demo", "synth-demo", "1.1.0", "b", tag="v1.1.0"); s.legacy_patch("game", "other", "synth-other", "1.0.0", "c", tag="v1.1.0")
        s.begin("v1.1.0", "synth-demo@1.1.0", "synth-other@1.0.0"); s.notes("v1.1.0"); s.catalog(); s.commit("prepare B")

    def test_a_prepared_is_not_advertised_then_published(self):
        s = self.release_a()
        self.assertEqual(s.catalog_entries(), [], "a prepared release must not appear in the catalog")
        self.assertEqual(run(S / "release_guard.py", "--root", s.d, "--tag", "v1.0.0", "--release-state", "none").returncode, 0)
        for r in s.checks(): self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        out = s.tmp / "outA"; r = s.build("v1.0.0", out); self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        r = s.assets("v1.0.0", out); self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        s.publish("v1.0.0")
        self.assertEqual([(p["id"], p["version"], p["release"]) for p in s.catalog_entries()], [("synth-demo", "1.0.0", "v1.0.0")])
        for r in s.checks(): self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_b_after_a_keeps_both_and_supersedes_additively(self):
        s = self.release_a(); s.publish("v1.0.0"); baseline = json.loads((s.d / "catalog/index.json").read_text()); a_before = (s.d / "releases/v1.0.0.json").read_text()
        self.release_b(s)
        self.assertEqual((s.d / "releases/v1.0.0.json").read_text(), a_before, "preparing B never touches the published release record of A")
        g = run(S / "release_guard.py", "--root", s.d, "--tag", "v1.1.0", "--release-state", "none"); self.assertEqual(g.returncode, 0, g.stderr)
        self.assertIn("synth-demo@1.1.0 supersedes published synth-demo@1.0.0", g.stdout)
        self.assertEqual([p["version"] for p in s.catalog_entries()], ["1.0.0"], "B is prepared: not advertised yet")
        for r in s.checks(): self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        outb = s.tmp / "outB"; self.assertEqual(s.build("v1.1.0", outb).returncode, 0)
        self.assertEqual(s.assets("v1.1.0", outb).returncode, 0, "B's assets verify without A's")
        outa = s.tmp / "outA2"; r = s.build("v1.0.0", outa); self.assertEqual(r.returncode, 0, "A is rebuilt from Git at its pinned commit although B replaced the working-tree sources: " + r.stdout + r.stderr)
        r = s.assets("v1.0.0", outa); self.assertEqual(r.returncode, 0, "A's assets verify without B's: " + r.stdout + r.stderr)
        s.publish("v1.1.0"); run(S / "prepare_release.py", "--root", s.d, "supersede", "--old", "synth-demo@1.0.0", "--new", "synth-demo@1.1.0", check=True); s.catalog(); s.commit("supersede")
        cat = s.catalog_entries(); ids = [(p["id"], p["version"], p["release"]) for p in cat]
        self.assertEqual(ids, [("synth-demo", "1.0.0", "v1.0.0"), ("synth-demo", "1.1.0", "v1.1.0"), ("synth-other", "1.0.0", "v1.1.0")])
        old = [p for p in cat if p["version"] == "1.0.0"][0]; was = baseline["packages"][0]
        self.assertEqual({k: v for k, v in old.items() if k != "superseded_by"}, was, "the historical entry is unchanged except the additive pointer")
        self.assertEqual(old["superseded_by"], "synth-demo@1.1.0")
        base = s.tmp / "base.json"; base.write_text(json.dumps(baseline))
        r = run(S / "validate_catalog.py", "--root", s.d, "--baseline", base); self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        for r in s.checks(): self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_published_release_cannot_be_rerun_or_replaced(self):
        s = self.release_a(); s.publish("v1.0.0")
        r = run(S / "release_guard.py", "--root", s.d, "--tag", "v1.0.0", "--release-state", state_file(False)); self.assertEqual(r.returncode, 1); self.assertIn("immutable", r.stderr)
        r = run(S / "release_guard.py", "--root", s.d, "--tag", "v1.0.0", "--release-state", "none"); self.assertEqual(r.returncode, 1); self.assertIn("deleted or inconsistent", r.stderr)
        r = run(S / "release_guard.py", "--root", s.d, "--tag", "v1.0.0", "--release-state", state_file(True)); self.assertEqual(r.returncode, 1); self.assertIn("inconsistent", r.stderr)

    def test_changing_a_published_digest_is_rejected(self):
        s = self.release_a(); s.publish("v1.0.0"); baseline = (s.d / "catalog/index.json").read_text()
        pj = s.patch("game", "demo") / "package.json"; meta = json.loads(pj.read_text()); meta["packages"][0]["package_sha256"] = "9" * 64; pj.write_text(json.dumps(meta)); s.catalog()
        (s.tmp / "base.json").write_text(baseline)
        r = run(S / "validate_catalog.py", "--root", s.d, "--baseline", s.tmp / "base.json"); self.assertEqual(r.returncode, 1); self.assertIn("package_sha256", r.stderr)

    def test_published_version_cannot_be_released_again_or_lowered(self):
        s = self.release_a(); s.publish("v1.0.0")
        s.legacy_patch("game", "demo", "synth-demo", "0.9.0", "z", tag="v1.1.0")        # an older version of a published id
        r = s.begin("v1.1.0", "synth-demo@0.9.0", check=False)
        self.assertNotEqual(r.returncode, 0); self.assertIn("must be higher", r.stderr + r.stdout)
        r = s.begin("v1.1.0", "synth-demo@1.0.0", check=False)
        self.assertNotEqual(r.returncode, 0); self.assertIn("selected by v1.0.0 and v1.1.0", r.stderr + r.stdout)
        self.assertFalse((s.d / "releases/v1.1.0.json").exists(), "a refused selection leaves no release record behind")

    def test_draft_requires_deliberate_maintainer_action(self):
        s = self.release_a()
        r = run(S / "release_guard.py", "--root", s.d, "--tag", "v1.0.0", "--release-state", state_file(True)); self.assertEqual(r.returncode, 1); self.assertIn("delete it deliberately", r.stderr)
        r = run(S / "release_guard.py", "--root", s.d, "--tag", "v1.0.0", "--release-state", state_file(False)); self.assertEqual(r.returncode, 1); self.assertIn("scripts/prepare_release.py publish", r.stderr)

    def test_unknown_tag_has_no_metadata(self):
        s = self.release_a(); r = run(S / "release_guard.py", "--root", s.d, "--tag", "v9.9.9", "--release-state", "none"); self.assertEqual(r.returncode, 1); self.assertIn("no release record", r.stderr)

    def test_wrong_digest_and_missing_asset_fail(self):
        s = self.release_a(); out = s.tmp / "out"; s.build("v1.0.0", out)
        (out / "synth-demo.segapatch").write_bytes(b"tampered")
        r = s.assets("v1.0.0", out); self.assertEqual(r.returncode, 1); self.assertIn("asset SHA-256 differs", r.stderr)
        (out / "synth-demo.segapatch").unlink(); r = s.assets("v1.0.0", out); self.assertEqual(r.returncode, 1); self.assertIn("asset not found", r.stderr)

    def test_assets_of_another_release_are_not_a_false_failure_but_a_stray_file_is(self):
        s = self.release_a(); s.publish("v1.0.0"); self.release_b(s)
        outa = s.tmp / "outA"; s.build("v1.0.0", outa); self.assertEqual(s.assets("v1.0.0", outa).returncode, 0, "B's packages in the metadata do not fail A's verification")
        (outa / "synth-other.segapatch").write_bytes(b"x")
        r = s.assets("v1.0.0", outa); self.assertEqual(r.returncode, 1); self.assertIn("unexpected release assets", r.stderr)
        r = run(S / "check_repo.py", "--root", s.d, "--assets", outa); self.assertEqual(r.returncode, 1); self.assertIn("pass --release", r.stderr)

    def test_two_versions_of_one_id_pass_the_repository_checks(self):
        s = self.release_a(); s.publish("v1.0.0"); self.release_b(s)
        r = run(S / "check_repo.py", "--root", s.d); self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_rebuild_release_script_verifies_each_release_with_its_writer(self):
        s = self.release_a(); s.publish("v1.0.0"); self.release_b(s); url = s.writer.as_uri()
        r = run(S / "rebuild_release.py", "--root", s.d, "--all", "--work", s.tmp / "w", "--writer-url", url); self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual((s.tmp / "w/v1.0.0/SHA256SUMS").read_text().count("segapatch"), 1); self.assertEqual((s.tmp / "w/v1.1.0/SHA256SUMS").read_text().count("segapatch"), 2)
        r = run(S / "rebuild_release.py", "--root", s.d, "--release", "v9.9.9", "--work", s.tmp / "w2", "--writer-url", url); self.assertNotEqual(r.returncode, 0)

    def test_writer_ref_is_recorded_per_release(self):
        s = self.release_a(); r = run(S / "build_packages.py", "--root", s.d, "--release", "v1.0.0", "--print-writer-ref"); self.assertEqual(r.stdout.strip(), (ROOT / "scripts/SEGAPATCH_REF").read_text().strip())


class RepositoryModel(unittest.TestCase):
    def test_the_published_v010_identities_are_unchanged(self):
        cat = json.loads((ROOT / "catalog/index.json").read_text())["packages"]
        v010 = [p for p in cat if p["release"] == "v0.1.0"]
        self.assertEqual({(p["id"], p["version"], p["release"]) for p in v010}, {("sonic1-native-widescreen", "2.0.1", "v0.1.0"), ("sonic2-native-widescreen", "3.0.1", "v0.1.0"),
            ("sonic2-native-widescreen-rev01", "3.0.1", "v0.1.0"), ("sonic3k-native-widescreen", "1.0.1", "v0.1.0"), ("sor2-widescreen", "1.0.0", "v0.1.0")})
        self.assertIn("636342c8a44516cc86bed4325c7f75d5721f0b38de8e852e2964a015566a5921", {p["package_sha256"] for p in v010})
        self.assertEqual({(p["id"], p["version"]) for p in cat if p["release"] != "v0.1.0"}, {(f"castle-of-illusion-activation-{a}", "0.1.0") for a in ("16x9", "21x9", "32x9")}, "the only later packages are the three of v0.3.0")
        self.assertTrue(all(p["asset"]["url"].startswith(f"{REPO}/releases/download/{p['release']}/") for p in cat), "every asset is served by its own release")

if __name__ == "__main__": unittest.main()
