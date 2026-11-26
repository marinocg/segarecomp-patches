"""Explicit publication eligibility, explicit per-release selection, schema 3 publication and bounded release work (no commercial data, no network).

Synthetic cases run against a throw-away repository with a fake deterministic writer and a fake product CLI (tests/synth_repo.py); the cases that need the
real product CLI (SEGARECOMP_CLI) or the pinned writer (SEGAPATCH) are skipped with that reason, never silently passed.
"""
import hashlib, json, os, pathlib, shutil, subprocess, sys, tempfile, unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests")); sys.path.insert(0, str(ROOT / "scripts"))
from synth_repo import PRODUCT_REF, S, Synthetic, git, run
import check_repo, check_source_review, release_meta

CLI, SDK, CC, SEGAPATCH = os.environ.get("SEGARECOMP_CLI"), os.environ.get("SEGARECOMP_SDK_DIR"), os.environ.get("SEGARECOMP_CC", "cc"), os.environ.get("SEGAPATCH")
# the product tool built at the revision the historical Castle package records (its build record is history: it is neither rewritten nor claimed for another revision)
HCLI, HSDK = os.environ.get("SEGARECOMP_CASTLE_CLI"), os.environ.get("SEGARECOMP_CASTLE_SDK_DIR")


def castle_like(test):
    """One game, six independent patches in the three-level layout: one candidate, one eligible, one internal tool, ..."""
    s = Synthetic(test)
    s.mod_patch("castle", "widescreen", "castle-widescreen", state="candidate")
    s.mod_patch("castle", "activation-a", "castle-activation-a", state="candidate")
    s.mod_patch("castle", "debug-fly", "castle-debug-fly", state="internal")
    s.mod_patch("castle", "recorder", "castle-recorder", state="internal")
    s.mod_log.unlink(missing_ok=True)   # forget the pinning calls: the tests count only what a release step builds
    return s


class Eligibility(unittest.TestCase):
    def prep(self):
        s = castle_like(self); s.state("genesis/castle/widescreen", "eligible"); s.commit("approve widescreen"); return s

    def test_default_is_not_publishable(self):
        s = Synthetic(self); s.mod_patch("g", "p", "g-p", state="internal"); (s.d / "publication.json").write_text(json.dumps({"publication_format": 1, "patches": {}}))
        self.assertEqual(release_meta.state_of(s.d, "genesis/g/p"), "internal")
        r = s.begin("v0.2.0", "g-p@0.1.0", check=False); self.assertNotEqual(r.returncode, 0); self.assertIn("not eligible", r.stderr + r.stdout)

    def test_internal_candidate_and_unknown_selections_are_refused(self):
        s = self.prep()
        for ref, why in (("castle-debug-fly@0.1.0", "is internal"), ("castle-recorder@0.1.0", "is internal"), ("castle-activation-a@0.1.0", "is candidate"), ("ghost@1.0.0", "unknown package")):
            r = s.begin("v0.2.0", ref, check=False); self.assertNotEqual(r.returncode, 0, ref); self.assertIn(why, r.stderr + r.stdout, ref)
            self.assertFalse((s.d / "releases/v0.2.0.json").exists(), "a refused selection leaves nothing behind")

    def test_a_wrong_version_is_an_unknown_selection(self):
        s = self.prep(); r = s.begin("v0.2.0", "castle-widescreen@9.9.9", check=False); self.assertNotEqual(r.returncode, 0); self.assertIn("unknown package", r.stderr + r.stdout)

    def test_duplicate_selection_is_refused(self):
        s = self.prep(); r = s.begin("v0.2.0", "castle-widescreen@0.1.0", "castle-widescreen@0.1.0", check=False)
        self.assertNotEqual(r.returncode, 0); self.assertIn("duplicate package selection", r.stderr + r.stdout)

    def test_a_hand_edited_release_cannot_smuggle_an_internal_patch_in(self):
        s = self.prep(); s.begin("v0.2.0", "castle-widescreen@0.1.0")
        f = s.d / "releases/v0.2.0.json"; doc = json.loads(f.read_text()); doc["packages"] = sorted(doc["packages"] + ["castle-debug-fly@0.1.0"]); f.write_text(json.dumps(doc))
        r = run(S / "validate_catalog.py", "--root", s.d); self.assertEqual(r.returncode, 1); self.assertIn("castle-debug-fly@0.1.0: patch genesis/castle/debug-fly is internal", r.stderr)
        r = run(S / "release_guard.py", "--root", s.d, "--tag", "v0.2.0", "--release-state", "none"); self.assertEqual(r.returncode, 1)

    def test_unsorted_or_duplicate_membership_in_the_record_is_refused(self):
        s = self.prep(); s.state("genesis/castle/activation-a", "eligible"); s.begin("v0.2.0", "castle-widescreen@0.1.0", "castle-activation-a@0.1.0")
        f = s.d / "releases/v0.2.0.json"; doc = json.loads(f.read_text()); doc["packages"].reverse(); f.write_text(json.dumps(doc))
        r = run(S / "validate_catalog.py", "--root", s.d); self.assertIn("must be sorted", r.stderr)

    def test_eligibility_alone_never_releases_anything(self):
        s = self.prep(); s.catalog(); s.commit("x")
        self.assertEqual(s.catalog_entries(), []); self.assertFalse(list((s.d / "releases").glob("*.json")))
        r = run(S / "rebuild_release.py", "--root", s.d, "--prepared", "--work", s.tmp / "w", env=s.env); self.assertEqual(r.returncode, 0); self.assertIn("nothing to rebuild", r.stdout)
        self.assertEqual(s.mod_calls(), [], "no release was selected: nothing is built")
        for r in s.checks(): self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_eligible_but_unselected_patches_stay_out(self):
        s = self.prep(); s.state("genesis/castle/activation-a", "eligible")
        s.begin("v0.2.0", "castle-widescreen@0.1.0"); s.notes("v0.2.0"); s.catalog(); s.commit("prepare")
        out = s.tmp / "out"; r = s.build("v0.2.0", out); self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(sorted(p.name for p in out.iterdir()), ["SHA256SUMS", "castle-widescreen.segapatch"])
        self.assertEqual(len((out / "SHA256SUMS").read_text().splitlines()), 1)
        built = " ".join(s.mod_calls()); self.assertIn("castle/widescreen", built)
        for other in ("activation-a", "debug-fly", "recorder"): self.assertNotIn(other, built)
        self.assertEqual(s.assets("v0.2.0", out, cli=True).returncode, 0)
        s.publish("v0.2.0")
        self.assertEqual([p["id"] for p in s.catalog_entries()], ["castle-widescreen"], "only the selected, published package is cataloged")
        for r in s.checks(): self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_a_prepared_package_has_no_public_download_url(self):
        s = self.prep(); s.begin("v0.2.0", "castle-widescreen@0.1.0"); s.catalog()
        self.assertNotIn("releases/download", (s.d / "catalog/index.json").read_text()); self.assertEqual(s.catalog_entries(), [])

    def test_publication_file_rules(self):
        s = self.prep(); f = s.d / "publication.json"
        for mutate, needle in ((lambda d: d["patches"].__setitem__("genesis/castle/widescreen", {"state": "eligible"}), "records its publication review"),
                               (lambda d: d["patches"].__setitem__("genesis/castle/widescreen", {"state": "approved"}), "state must be one of"),
                               (lambda d: d["patches"].__setitem__("genesis/castle/not-a-patch", {"state": "internal"}), "is not a patch directory")):
            doc = json.loads(f.read_text()); mutate(doc); f.write_text(json.dumps(doc))
            r = run(S / "validate_catalog.py", "--root", s.d); self.assertEqual(r.returncode, 1, needle); self.assertIn(needle, r.stderr)
            f.write_text(json.dumps({"publication_format": 1, "patches": s.pub}))

    def test_an_eligible_patch_needs_its_source_review_records(self):
        s = self.prep(); (s.d / "docs/source-review.json").write_text(json.dumps({"record_format": 1, "files": [], "excluded": [{"item": "x", "reason": "y"}]}))
        e = []; check_source_review.check(s.d, e)
        self.assertTrue(any("no review record" in x for x in e), e)   # eligible, but nobody recorded the per-file review
        check_source_review.write(s.d); e = []; check_source_review.check(s.d, e); self.assertEqual(e, [])
        rec = json.loads((s.d / "docs/source-review.json").read_text()); self.assertEqual({r["path"] for r in rec["files"]}, {"patches/genesis/castle/widescreen/mod.toml", "patches/genesis/castle/widescreen/src/provider.c"},
                                                                                         "only the eligible patch's files are in the review record")
        (s.patch("castle", "widescreen") / "src/provider.c").write_text("/* changed after review */\n"); e = []; check_source_review.check(s.d, e)
        self.assertTrue(any("sha256 differs" in x for x in e), "changed source needs a fresh review")


class SchemaThree(unittest.TestCase):
    def published(self):
        s = castle_like(self); s.state("genesis/castle/widescreen", "eligible"); s.begin("v0.2.0", "castle-widescreen@0.1.0"); s.notes("v0.2.0"); s.catalog(); s.commit("prepare")
        out = s.tmp / "out"; self.assertEqual(s.build("v0.2.0", out).returncode, 0); s.publish("v0.2.0"); return s, out

    def test_the_catalog_entry_is_truthful_about_a_source_based_mod(self):
        s, _ = self.published(); e = s.catalog_entries()[0]
        self.assertEqual((e["schema_version"], e["native_abi"], e["trust"], e["executable_code"]), (3, 2, "trusted-native-source", True))
        self.assertEqual(e["images"], [{"label": "fixture", "sha256": hashlib.sha256(b"castle-widescreen").hexdigest()}])
        self.assertFalse({"bps_sha256", "patched_image_sha256", "source_image_sha256", "native_source_sha256", "bps", "revision", "region"} & set(e), "no fabricated BPS/ROM fields")
        self.assertNotIn("0" * 64, json.dumps(e), "no zero or placeholder digests")
        self.assertEqual(e["source_path"], "patches/genesis/castle/widescreen"); self.assertEqual(e["game_path"], "patches/genesis/castle")
        self.assertEqual(e["build"], {"writer": "segarecomp mod pack", "writer_ref": PRODUCT_REF, "deterministic": True})
        self.assertEqual(e["asset"]["url"], f"https://github.com/marinocg/segarecomp-patches/releases/download/v0.2.0/castle-widescreen.segapatch")
        self.assertEqual(json.loads((s.d / "catalog/index.json").read_text())["catalog_format"], 2)
        for r in s.checks(): self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_pack_and_build_are_the_same_bytes(self):
        s = castle_like(self); d = s.patch("castle", "widescreen")
        ok1, i1, b1 = check_repo.pack_mod_project(str(s.cli), d, s.tmp / "a.segapatch", []); ok2, i2, b2 = check_repo.pack_mod_project(str(s.cli), d, s.tmp / "b.segapatch", ["--cc", "cc", "--sdk-dir", "x"])
        self.assertTrue(ok1 and ok2); self.assertEqual((b1, i1["package_identity"]), (b2, i2["package_identity"]))

    def test_changed_source_after_pinning_fails_the_selected_build(self):
        s = castle_like(self); s.state("genesis/castle/widescreen", "eligible"); s.begin("v0.2.0", "castle-widescreen@0.1.0")
        (s.patch("castle", "widescreen") / "src/provider.c").write_text("/* modified but not re-pinned */\n")
        r = s.build("v0.2.0", s.tmp / "out"); self.assertEqual(r.returncode, 1); self.assertIn("FAIL", r.stdout)
        e = []; check_repo.check_mod_projects(s.d, str(s.cli), e); self.assertTrue(any("differs from package.json" in x for x in e), e)

    def test_a_recorded_version_is_never_rewritten(self):
        s = castle_like(self); (s.patch("castle", "widescreen") / "src/provider.c").write_text("/* new bytes, same version */\n")
        r = s.pin(s.patch("castle", "widescreen"), check=False); self.assertNotEqual(r.returncode, 0); self.assertIn("bump `version`", r.stderr + r.stdout)

    def test_a_new_version_is_recorded_beside_the_old_one(self):
        s = castle_like(self); d = s.patch("castle", "widescreen"); (d / "mod.toml").write_text((d / "mod.toml").read_text().replace('version = "0.1.0"', 'version = "0.2.0"'))
        self.assertEqual(s.pin(d, check=False).returncode, 0)
        self.assertEqual([p["version"] for p in json.loads((d / "package.json").read_text())["packages"]], ["0.1.0", "0.2.0"])

    def test_wrong_abi_missing_capabilities_and_wrong_digest_are_rejected(self):
        s = castle_like(self); pj = s.patch("castle", "widescreen") / "package.json"; good = json.loads(pj.read_text())
        for mutate, needle in ((lambda p: p.update(native_abi=1), "native_abi"), (lambda p: p.pop("capabilities"), "capabilities"), (lambda p: p.update(package_sha256="12"), "package_sha256"),
                               (lambda p: p.update(bps_sha256="0" * 64), "unknown field"), (lambda p: p.update(trust="data-only"), "not one of")):
            doc = json.loads(json.dumps(good)); mutate(doc["packages"][0]); pj.write_text(json.dumps(doc))
            r = run(S / "validate_catalog.py", "--root", s.d); self.assertEqual(r.returncode, 1, needle); self.assertIn(needle, r.stderr)
        doc = json.loads(json.dumps(good)); doc["packages"][0]["capabilities"] = ["frame.work_ram"]; pj.write_text(json.dumps(doc))   # mod.toml is the authority for what the project declares
        e = []; check_repo.check(s.d, e); self.assertTrue(any("capabilities" in x and "disagrees with mod.toml" in x for x in e), e)

    def test_the_selected_package_is_pinned_to_the_product_revision(self):
        s = castle_like(self); s.state("genesis/castle/widescreen", "eligible"); s.begin("v0.2.0", "castle-widescreen@0.1.0")
        (s.d / "scripts/PRODUCT_REF").write_text("e" * 40 + "\n"); e = []; check_repo.check(s.d, e)
        self.assertTrue(any("is not the pinned product revision" in x for x in e), e)   # the toolchain moved: the package must be re-pinned before it can ship
        (s.d / "scripts/PRODUCT_REF").write_text(PRODUCT_REF + "\n")
        r = run(S / "build_packages.py", "--root", s.d, "--release", "v0.2.0", "--out", s.tmp / "o", "--segarecomp", s.cli, "--segarecomp-ref", "f" * 40, env=s.env)
        self.assertNotEqual(r.returncode, 0); self.assertIn("build the product at the pinned revision", r.stderr)
        r = run(S / "build_packages.py", "--root", s.d, "--release", "v0.2.0", "--print-product-ref"); self.assertEqual(r.stdout.strip(), PRODUCT_REF)

    def test_a_schema_3_release_needs_the_product_cli(self):
        s = castle_like(self); s.state("genesis/castle/widescreen", "eligible"); s.begin("v0.2.0", "castle-widescreen@0.1.0")
        r = run(S / "rebuild_release.py", "--root", s.d, "--release", "v0.2.0", "--work", s.tmp / "w"); self.assertNotEqual(r.returncode, 0); self.assertIn("pass --segarecomp", r.stderr)

    def test_legacy_and_schema_3_packages_share_one_release(self):
        s = castle_like(self); s.state("genesis/castle/widescreen", "eligible"); s.legacy_patch("old", "data", "old-data", "1.0.0", "k", tag="v0.2.0")
        s.begin("v0.2.0", "castle-widescreen@0.1.0", "old-data@1.0.0"); s.notes("v0.2.0"); s.catalog(); s.commit("prepare")
        out = s.tmp / "out"; self.assertEqual(s.build("v0.2.0", out).returncode, 0); self.assertEqual(len((out / "SHA256SUMS").read_text().splitlines()), 2)
        self.assertEqual(s.assets("v0.2.0", out, cli=True).returncode, 0)
        s.publish("v0.2.0"); self.assertEqual([(p["id"], p["schema_version"]) for p in s.catalog_entries()], [("castle-widescreen", 3), ("old-data", 1)])
        for r in s.checks(): self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


class Scalability(unittest.TestCase):
    """Many historical packages, two new selected ones: only the two are built; the historical ones are metadata."""
    HIST = 60

    def fixture(self):
        s = Synthetic(self)
        for i in range(self.HIST): s.legacy_patch(f"hist-{i:03d}", "main", f"hist-{i:03d}", "1.0.0", f"h{i}", tag="v1.0.0")
        s.begin("v1.0.0", *[f"hist-{i:03d}@1.0.0" for i in range(self.HIST)]); s.notes("v1.0.0"); s.catalog(); s.commit("history"); s.publish("v1.0.0")
        s.legacy_patch("new", "legacy", "new-legacy", "1.0.0", "n1", tag="v1.1.0")
        s.mod_patch("new", "mod", "new-mod", state="eligible"); s.mod_patch("new", "candidate", "new-candidate", state="candidate"); s.mod_patch("new", "tool", "new-tool", state="internal")
        s.begin("v1.1.0", "new-legacy@1.0.0", "new-mod@0.1.0"); s.notes("v1.1.0"); s.catalog(); s.commit("prepare v1.1.0")
        for f in (s.mod_log, s.writer_log): f.unlink(missing_ok=True)    # forget the pinning calls: count only what the release steps do
        return s

    def rebuild(self, s, *mode):
        return run(S / "rebuild_release.py", "--root", s.d, *mode, "--work", s.tmp / "w", "--writer-url", s.writer.as_uri(), "--segarecomp", s.cli, "--segarecomp-ref", PRODUCT_REF, env=s.env)

    def test_routine_release_preparation_builds_exactly_the_selected_packages(self):
        s = self.fixture()
        r = self.rebuild(s, "--release", "v1.1.0"); self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(s.writer_calls(), ["new-legacy.segapatch"], "package generation ran once for the one selected legacy package")
        built = [l for l in s.mod_calls() if l.startswith(("mod pack", "mod build"))]; self.assertEqual(len(built), 1, built); self.assertIn("new/mod", built[0])
        for never in ("hist-", "new/candidate", "new/tool", "new-tool", "new-candidate"): self.assertFalse(any(never in l for l in s.writer_calls() + s.mod_calls()), never)
        self.assertEqual(sorted(p.name for p in (s.tmp / "w/v1.1.0").iterdir()), ["SHA256SUMS", "new-legacy.segapatch", "new-mod.segapatch"])

    def test_pull_request_rebuild_covers_only_prepared_releases(self):
        s = self.fixture(); r = self.rebuild(s, "--prepared"); self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(s.writer_calls(), ["new-legacy.segapatch"]); self.assertEqual(len([l for l in s.mod_calls() if l.startswith("mod pack")]), 1)
        self.assertFalse((s.tmp / "w/v1.0.0").exists(), "no historical release is reconstructed during routine preparation")

    def test_repository_wide_checks_are_metadata_only_even_with_many_packages(self):
        s = self.fixture()
        for r in s.checks(): self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(s.writer_calls(), []); self.assertEqual(s.mod_calls(), [], "check_repo/validate_catalog/verify_provenance never invoke a package builder")

    def test_changed_path_detection_checks_only_what_the_pull_request_touched(self):
        s = self.fixture(); base = git(s.d, "rev-parse", "HEAD")
        (s.patch("new", "tool") / "README.md").write_text("# touched\n"); s.commit("touch the internal tool")
        for f in (s.mod_log,): f.unlink(missing_ok=True)
        r = run(S / "check_repo.py", "--root", s.d, "--segarecomp", s.cli, "--changed-from", base, env=s.env); self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        touched = {l.split()[2] for l in s.mod_calls() if l.startswith("mod check")}
        self.assertEqual({pathlib.Path(t).relative_to(s.d).as_posix() for t in touched}, {"patches/genesis/new/tool"},
                         "only the changed project: the pending release v1.1.0 is not affected by a README change in an unrelated internal patch; nothing historical")

    def test_full_audit_still_rebuilds_everything(self):
        s = self.fixture(); r = self.rebuild(s, "--all"); self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(len(s.writer_calls()), self.HIST + 1); self.assertTrue((s.tmp / "w/v1.0.0/SHA256SUMS").is_file() and (s.tmp / "w/v1.1.0/SHA256SUMS").is_file())
        self.assertIn(f"2 release(s): ok", r.stdout)

    def test_a_new_package_does_not_touch_or_version_any_historical_one(self):
        s = castle_like(self); s.legacy_patch("old", "data", "old-data", "1.0.0", "k", tag="v1.0.0"); s.begin("v1.0.0", "old-data@1.0.0"); s.notes("v1.0.0"); s.catalog(); s.commit("A"); s.publish("v1.0.0")
        before = {p.relative_to(s.d).as_posix(): p.read_bytes() for p in list((s.d / "patches/genesis/old").rglob("*")) + [s.d / "releases/v1.0.0.json"] if p.is_file()}
        s.state("genesis/castle/widescreen", "eligible"); s.begin("v1.1.0", "castle-widescreen@0.1.0"); s.notes("v1.1.0"); s.catalog(); s.commit("B")
        self.assertEqual(before, {k: (s.d / k).read_bytes() for k in before}, "release B did not rewrite a byte of what release A recorded")
        self.assertEqual(run(S / "release_guard.py", "--root", s.d, "--tag", "v1.1.0", "--release-state", "none").returncode, 0)

    def test_a_rebuild_of_an_old_release_after_the_sources_moved_still_matches(self):
        """The v0.1.0 situation: the release was built when sources lived under patches/<platform>/<game>/source/; later commits moved them into the per-patch layout."""
        s = Synthetic(self); s.legacy_patch("game", "demo", "old-style", "1.0.0", "o", tag="v1.0.0"); s.begin("v1.0.0", "old-style@1.0.0"); s.notes("v1.0.0")
        rj = s.d / "releases/v1.0.0.json"; doc = json.loads(rj.read_text()); doc["source_layout"] = "game-dir"; rj.write_text(json.dumps(doc))
        s.catalog(); git(s.d, "add", "-A"); git(s.d, "commit", "-qm", "metadata")
        git(s.d, "mv", "patches/genesis/game/demo/source", "patches/genesis/game/source"); old_layout = s.commit("old layout at the release commit")
        git(s.d, "mv", "patches/genesis/game/source", "patches/genesis/game/demo/source"); s.commit("move into the per-patch layout")
        git(s.d, "tag", "v1.0.0", old_layout); run(S / "prepare_release.py", "--root", s.d, "publish", "--tag", "v1.0.0", "--commit", old_layout, check=True); s.catalog(); s.commit("record")
        self.assertFalse((s.d / "patches/genesis/game/source").exists())
        r = s.build("v1.0.0", s.tmp / "out"); self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(run(S / "verify_provenance.py", "--root", s.d).returncode, 0)


class AffectedReleases(unittest.TestCase):
    """PR CI rebuilds only the prepared releases a change affects. Counts of package builds (not timings) show the bound."""
    def fixture(self):
        s = Synthetic(self)
        for i in range(3): s.legacy_patch(f"old{i}", "main", f"old{i}", "1.0.0", f"o{i}", tag="v1.0.0")
        s.begin("v1.0.0", *[f"old{i}@1.0.0" for i in range(3)]); s.notes("v1.0.0"); s.catalog(); s.commit("history"); s.publish("v1.0.0")
        s.legacy_patch("a", "main", "pa", "1.0.0", "a", tag="v2.0.0"); s.mod_patch("b", "main", "pb", state="eligible"); s.mod_patch("c", "main", "pc", state="eligible")
        s.mod_patch("tool", "main", "ptool", state="internal")
        s.begin("v2.0.0", "pa@1.0.0", "pb@0.1.0"); s.begin("v3.0.0", "pc@0.1.0"); s.notes("v2.0.0"); s.notes("v3.0.0"); s.catalog(); s.commit("prepare")
        return s, git(s.d, "rev-parse", "HEAD")

    def run_affected(self, s, base):
        for f in (s.mod_log, s.writer_log): f.unlink(missing_ok=True)
        r = run(S / "rebuild_release.py", "--root", s.d, "--affected-from", base, "--work", s.tmp / "w", "--writer-url", s.writer.as_uri(), "--segarecomp", s.cli, "--segarecomp-ref", PRODUCT_REF, env=s.env)
        return r, len(s.writer_calls()) + len([l for l in s.mod_calls() if l.startswith(("mod pack", "mod build"))]), sorted(p.name for p in (s.tmp / "w").glob("v*")) if (s.tmp / "w").exists() else []

    def change(self, s, base, msg, edit):
        edit(); s.commit(msg); return self.run_affected(s, base)

    def test_documentation_and_site_changes_build_nothing(self):
        s, base = self.fixture(); (s.d / "site").mkdir(); (s.d / "site/x.css").write_text("a{}"); (s.d / "docs/x.md").write_text("x")
        s.commit("docs"); r, n, tags = self.run_affected(s, base)
        self.assertEqual((r.returncode, n, tags), (0, 0, [])); self.assertIn("nothing to rebuild", r.stdout)

    def test_a_changed_patch_rebuilds_only_the_releases_that_contain_it(self):
        s, base = self.fixture(); r, n, tags = self.change(s, base, "touch pa", lambda: (s.patch("a", "main") / "README.md").write_text("# changed\n"))
        self.assertEqual((r.returncode, tags, n), (0, ["v2.0.0"], 2), r.stdout + r.stderr)   # v2.0.0 = pa (legacy) + pb (mod): 2 builds; v3.0.0 and the published v1.0.0 untouched
        self.assertNotIn("pc.segapatch", " ".join(s.mod_calls())); self.assertFalse(any(l.startswith("old") for l in s.writer_calls()))

    def test_a_patch_in_two_prepared_releases_rebuilds_both(self):
        s, base = self.fixture(); s.legacy_patch("a", "main", "pa2", "1.0.0", "a2", tag="v3.0.0")   # a second package of the SAME patch directory
        (s.d / "releases/v3.0.0.json").unlink(); s.begin("v3.0.0", "pc@0.1.0", "pa2@1.0.0"); s.commit("pa2 in v3"); base = git(s.d, "rev-parse", "HEAD")
        r, n, tags = self.change(s, base, "touch patch a", lambda: (s.patch("a", "main") / "README.md").write_text("# changed\n"))
        self.assertEqual((r.returncode, tags), (0, ["v2.0.0", "v3.0.0"]), r.stdout + r.stderr); self.assertEqual(n, 2 + 2)   # v2.0.0: pa + pb, v3.0.0: pc + pa2

    def test_a_shared_tool_or_schema_change_rebuilds_every_prepared_release_but_no_published_one(self):
        for path in ("scripts/PRODUCT_REF", "catalog/schema/package-1.schema.json"):
            s, base = self.fixture(); f = s.d / path; r, n, tags = self.change(s, base, "shared", lambda: f.write_text(f.read_text() + "\n"))
            self.assertEqual((r.returncode, tags, n), (0, ["v2.0.0", "v3.0.0"], 3), (path, r.stdout, r.stderr))
            self.assertFalse((s.tmp / "w/v1.0.0").exists(), "the published release is not part of routine work")

    def test_an_internal_patch_change_builds_no_release_asset(self):
        s, base = self.fixture(); r, n, tags = self.change(s, base, "touch internal", lambda: (s.patch("tool", "main") / "README.md").write_text("# changed\n"))
        self.assertEqual((r.returncode, n, tags), (0, 0, [])); self.assertFalse(any("tool" in l for l in s.mod_calls() if l.startswith("mod pack")))
        r2 = run(S / "check_repo.py", "--root", s.d, "--segarecomp", s.cli, "--changed-from", base, env=s.env)   # the project check still covers the changed internal patch
        self.assertEqual(r2.returncode, 0); self.assertTrue(any("ptool" not in l and "tool/main" in l for l in s.mod_calls() if l.startswith("mod check")))

    def test_a_new_release_manifest_builds_its_packages(self):
        s, base = self.fixture(); s.legacy_patch("d", "main", "pd", "1.0.0", "d", tag="v4.0.0"); s.commit("patch d"); base = git(s.d, "rev-parse", "HEAD")
        r, n, tags = self.change(s, base, "begin v4", lambda: s.begin("v4.0.0", "pd@1.0.0"))
        self.assertEqual((r.returncode, tags, n), (0, ["v4.0.0"], 1), r.stdout + r.stderr)

    def test_a_publication_state_change_affects_the_releases_of_that_patch(self):
        s, base = self.fixture(); r, n, tags = self.change(s, base, "flip", lambda: s.state("genesis/c/main", "eligible") or (s.d / "publication.json").write_text((s.d / "publication.json").read_text()))
        self.assertEqual(tags, [], "an unchanged state affects nothing")
        s2, base2 = self.fixture(); s2.pub["genesis/c/main"]["review"] = "re-reviewed"; s2.write_publication(); s2.commit("re-review")
        r, n, tags = self.run_affected(s2, base2); self.assertEqual((tags, n), (["v3.0.0"], 1))

    def test_a_renamed_patch_directory_is_detected_through_its_old_path(self):
        s, base = self.fixture(); (s.d / "patches/genesis/a/main/README.md").write_text("# edit\n"); git(s.d, "mv", "patches/genesis/a/main/README.md", "patches/genesis/a/main/README2.md"); s.commit("rename a file")
        r, n, tags = self.run_affected(s, base); self.assertEqual((tags, n), (["v2.0.0"], 2))

    def test_missing_or_invalid_base_fails_closed(self):
        s, _ = self.fixture()
        for f in (s.mod_log, s.writer_log): f.unlink(missing_ok=True)
        for bad in ("no-such-ref", "0" * 40, ""):
            r = run(S / "rebuild_release.py", "--root", s.d, "--affected-from", bad, "--work", s.tmp / "w", env=s.env)
            self.assertNotEqual(r.returncode, 0, bad); self.assertEqual(s.mod_calls() + s.writer_calls(), [], "nothing was built on an untrusted comparison")

    def test_all_still_audits_every_release_and_prepared_never_touches_published(self):
        s, base = self.fixture()
        for f in (s.mod_log, s.writer_log): f.unlink(missing_ok=True)
        r = run(S / "rebuild_release.py", "--root", s.d, "--all", "--work", s.tmp / "w", "--writer-url", s.writer.as_uri(), "--segarecomp", s.cli, "--segarecomp-ref", PRODUCT_REF, env=s.env)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr); self.assertEqual(len(s.writer_calls()) + len([l for l in s.mod_calls() if l.startswith("mod build") or l.startswith("mod pack")]), 3 + 2 + 1)
        for f in (s.mod_log, s.writer_log): f.unlink(missing_ok=True)
        r = run(S / "rebuild_release.py", "--root", s.d, "--prepared", "--work", s.tmp / "w2", "--writer-url", s.writer.as_uri(), "--segarecomp", s.cli, "--segarecomp-ref", PRODUCT_REF, env=s.env)
        self.assertEqual(r.returncode, 0); self.assertFalse(any(l.startswith("old") for l in s.writer_calls())); self.assertEqual(len(s.writer_calls()), 1)


class Schema3Scope(unittest.TestCase):
    """`check_repo.py --segarecomp ... --changed-from BASE` validates the changed schema 3 projects plus those of the prepared releases the change AFFECTS (same selection as
    rebuild_release.py --affected-from), counted in real product-tool invocations. Unrelated pending releases and published ones are never touched."""
    run_affected = AffectedReleases.run_affected   # the same selection, driven through rebuild_release.py

    def fixture(self):
        s, base = AffectedReleases.fixture(self)
        s.mod_patch("hist", "main", "phist", state="eligible"); s.begin("v0.9.0", "phist@0.1.0"); s.notes("v0.9.0"); s.catalog(); s.commit("hist release"); s.publish("v0.9.0")
        return s, git(s.d, "rev-parse", "HEAD")

    def validated(self, s, base):
        for f in (s.mod_log, s.writer_log): f.unlink(missing_ok=True)
        r = run(S / "check_repo.py", "--root", s.d, "--segarecomp", s.cli, "--changed-from", base, env=s.env)
        dirs = {pathlib.Path(l.split()[2]).relative_to(s.d).as_posix().replace("patches/genesis/", "") for l in s.mod_calls() if l.startswith("mod check")}
        packs = len([l for l in s.mod_calls() if l.startswith(("mod pack", "mod build"))])
        return r, dirs, packs

    def edit(self, s, rel, msg="change"): (s.d / rel).write_text(f"# {msg}\n" if rel.endswith(".md") else (s.d / rel).read_text() + "\n"); s.commit(msg)

    def test_documentation_and_site_changes_invoke_no_schema_3_build(self):
        s, base = self.fixture(); (s.d / "site").mkdir(); (s.d / "site/x.css").write_text("a{}"); (s.d / "docs/x.md").write_text("x"); s.commit("docs")
        r, dirs, packs = self.validated(s, base); self.assertEqual((r.returncode, dirs, packs, s.mod_calls()), (0, set(), 0, []), r.stderr)

    def test_a_changed_internal_tool_is_validated_but_is_never_a_release_asset(self):
        s, base = self.fixture(); self.edit(s, "patches/genesis/tool/main/README.md")
        r, dirs, packs = self.validated(s, base); self.assertEqual((r.returncode, dirs, packs), (0, {"tool/main"}, 2), r.stderr)   # one project: check + pack twice for determinism
        self.assertFalse((s.tmp / "w").exists())

    def test_a_changed_patch_validates_itself_and_its_release_only(self):
        s, base = self.fixture(); self.edit(s, "patches/genesis/b/main/README.md")   # pb is in v2.0.0 (with legacy pa); v3.0.0 (pc) is unrelated
        r, dirs, packs = self.validated(s, base); self.assertEqual((r.returncode, dirs, packs), (0, {"b/main"}, 2), r.stderr)
        self.assertNotIn("c/main", dirs); self.assertNotIn("hist/main", dirs)

    def test_a_new_release_manifest_validates_exactly_its_packages(self):
        s, base = self.fixture(); s.mod_patch("e", "main", "pe", state="eligible"); s.commit("patch e"); base = git(s.d, "rev-parse", "HEAD")
        s.begin("v4.0.0", "pe@0.1.0"); s.commit("begin v4")
        r, dirs, packs = self.validated(s, base); self.assertEqual((r.returncode, dirs, packs), (0, {"e/main"}, 2), r.stderr)

    def test_only_the_affected_release_projects_are_validated(self):
        s, base = self.fixture(); f = s.d / "releases/v3.0.0.json"; d = json.loads(f.read_text()); f.write_text(json.dumps(d, indent=4)); s.commit("touch v3 record")
        r, dirs, packs = self.validated(s, base); self.assertEqual((r.returncode, dirs), (0, {"c/main"}), r.stderr)   # v3.0.0 = pc; v2.0.0 (pb) untouched
        self.assertEqual(packs, 2)

    def test_a_shared_tool_change_validates_every_prepared_release_project(self):
        s, base = self.fixture(); self.edit(s, "scripts/PRODUCT_REF")
        r, dirs, packs = self.validated(s, base)
        self.assertEqual((r.returncode, dirs, packs), (0, {"b/main", "c/main"}, 4), r.stderr)   # both prepared releases' schema 3 packages, still not the internal tool or the published hist
        self.assertNotIn("hist/main", dirs); self.assertNotIn("tool/main", dirs)

    def test_an_unresolvable_base_fails_closed_without_skipping(self):
        s, _ = self.fixture()
        for f in (s.mod_log, s.writer_log): f.unlink(missing_ok=True)
        for bad in ("no-such-ref", "0" * 40):
            r = run(S / "check_repo.py", "--root", s.d, "--segarecomp", s.cli, "--changed-from", bad, env=s.env)
            self.assertNotEqual(r.returncode, 0, bad); self.assertIn("cannot be trusted", r.stderr + r.stdout)
        self.assertEqual(s.mod_calls(), [])

    def test_without_a_base_every_project_is_validated_and_nothing_is_published(self):
        s, base = self.fixture()
        for f in (s.mod_log, s.writer_log): f.unlink(missing_ok=True)
        r = run(S / "check_repo.py", "--root", s.d, "--segarecomp", s.cli, env=s.env); self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual({pathlib.Path(l.split()[2]).name for l in s.mod_calls() if l.startswith("mod check")} , {"main"}); self.assertEqual(len([l for l in s.mod_calls() if l.startswith("mod check")]), 4)   # pb, pc, ptool, phist: the explicit full check

    def test_no_published_historical_package_is_rebuilt_by_routine_validation(self):
        s, base = self.fixture(); self.edit(s, "scripts/PRODUCT_REF"); self.validated(s, base)
        self.assertFalse(any("hist" in l for l in s.mod_calls()))
        r, n, tags = self.run_affected(s, base); self.assertEqual(tags, ["v2.0.0", "v3.0.0"]); self.assertFalse(any("hist" in l or l.startswith("old") for l in s.mod_calls() + s.writer_calls()))


@unittest.skipUnless(SEGAPATCH, "set SEGAPATCH to the pinned product tools/segapatch.py to reconstruct the v0.1.0 packages")
class HistoricalIntegrity(unittest.TestCase):
    def test_v010_is_reconstructed_from_its_pinned_commit_with_its_original_digests(self):
        out = pathlib.Path(tempfile.mkdtemp()); self.addCleanup(shutil.rmtree, out)
        r = run(S / "build_packages.py", "--release", "v0.1.0", "--segapatch", SEGAPATCH, "--out", out); self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        cat = {p["id"]: p for p in json.loads((ROOT / "catalog/index.json").read_text())["packages"] if p["release"] == "v0.1.0"}   # later releases (v0.2.0) are verified by their own rebuild
        self.assertEqual(len(cat), 5)
        sums = dict(l.split("  ")[::-1] for l in (out / "SHA256SUMS").read_text().splitlines())
        for pid, p in cat.items():
            self.assertEqual(hashlib.sha256((out / f"{pid}.segapatch").read_bytes()).hexdigest(), p["package_sha256"], pid)
            self.assertEqual(sums[f"{pid}.segapatch"], p["package_sha256"])
        self.assertEqual(check_repo_assets(out), [])

    def test_v010_catalog_entries_equal_the_originally_published_ones(self):
        first = subprocess.run(["git", "show", "2f6bdb7:catalog/index.json"], cwd=ROOT, capture_output=True, text=True)
        if first.returncode: self.skipTest("the W02 commit is not in this checkout")
        old, new = json.loads(first.stdout)["packages"], json.loads((ROOT / "catalog/index.json").read_text())["packages"]
        by_id = {p["id"]: p for p in new}   # the catalog is sorted by id, so a later release's entry may precede the originals: compare each original entry by its id
        self.assertEqual([by_id.get(p["id"]) for p in old], old, "every published entry is byte-for-byte the same value")


def check_repo_assets(out):
    e = []; check_repo.check_assets(ROOT, out, None, e, "v0.1.0"); return e


@unittest.skipUnless(CLI and SDK, "set SEGARECOMP_CLI and SEGARECOMP_SDK_DIR to run against the product's mod tools")
class Sonic3kAbi2(unittest.TestCase):
    """SEG-152-T011: the Sonic 3 & Knuckles ABI 2 candidate is validated by the exec job with the pinned product CLI (mod check, deterministic mod pack, recorded identity / SHA-256 / size)."""
    D = "patches/genesis/sonic-3-and-knuckles/native-widescreen-abi2"
    def test_recorded_pinned_and_reproducible(self):
        rec = next(pk for pk in release_meta.packages(ROOT) if pk.id == "sonic3k-native-widescreen-abi2")
        self.assertEqual((rec.version, rec.p["schema_version"], rec.p["native_abi"]), ("0.1.0", 3, 2))
        self.assertEqual(rec.build.get("writer_ref"), (ROOT / "scripts/PRODUCT_REF").read_text().strip())
        e = []; check_repo.check_mod_projects(ROOT, CLI, e, ["--cc", CC, "--sdk-dir", SDK], only={self.D}); self.assertEqual(e, [])
    def test_the_bps_delta_is_the_published_abi1_delta(self):
        a = (ROOT / self.D / "bps/game.bps").read_bytes(); b = (ROOT / "patches/genesis/sonic-3-and-knuckles/native-widescreen/source/sonic3k-native-widescreen.bps").read_bytes()
        self.assertEqual(a, b)
    def test_it_is_a_candidate_and_the_abi1_package_stays_eligible(self):
        self.assertEqual(release_meta.state_of(ROOT, "genesis/sonic-3-and-knuckles/native-widescreen-abi2"), "candidate")
        self.assertEqual(release_meta.state_of(ROOT, "genesis/sonic-3-and-knuckles/native-widescreen"), "eligible")


@unittest.skipUnless(CLI and SDK, "set SEGARECOMP_CLI and SEGARECOMP_SDK_DIR to run against the product's mod tools")
class CastleIntegration(unittest.TestCase):
    """The real Castle projects, real product CLI: a dry-run release that selects only castle-of-illusion-widescreen-practice."""
    PID = "castle-of-illusion-widescreen-practice"

    def copy(self):
        d = pathlib.Path(tempfile.mkdtemp()); self.addCleanup(shutil.rmtree, d)
        for p in ("patches", "releases", "catalog", "docs"): shutil.copytree(ROOT / p, d / p, ignore=shutil.ignore_patterns("__pycache__"))
        for f in ("publication.json", "scripts/PRODUCT_REF", "scripts/SEGAPATCH_REF"): (d / f).parent.mkdir(exist_ok=True); shutil.copy(ROOT / f, d / f)
        return d

    def test_classification_in_the_repository(self):
        st = lambda n: release_meta.state_of(ROOT, f"genesis/castle-of-illusion/{n}")
        self.assertEqual(st("widescreen-practice"), "candidate"); self.assertEqual([st(f"activation-{v}") for v in ("16x9", "21x9", "32x9")], ["eligible"] * 3)
        self.assertEqual((st("debug-fly"), st("input-recorder")), ("internal", "internal"))

    def test_the_castle_package_is_recorded_and_reproducible(self):
        rec = next(pk for pk in release_meta.packages(ROOT) if pk.id == self.PID); self.assertEqual((rec.version, rec.p["schema_version"], rec.p["native_abi"]), ("0.1.0", 3, 2))
        e = []; check_repo.check_mod_projects(ROOT, CLI, e, ["--cc", CC, "--sdk-dir", SDK], only={"patches/genesis/castle-of-illusion/widescreen-practice"}); self.assertEqual(e, [])

    @unittest.skipUnless(HCLI and HSDK, "set SEGARECOMP_CASTLE_CLI and SEGARECOMP_CASTLE_SDK_DIR (the product built at the Castle package's recorded revision)")
    def test_dry_run_selects_only_the_widescreen_practice_package(self):
        d = self.copy(); st = json.loads((d / "publication.json").read_text())
        for f in ("releases/v0.2.0.json", "docs/release-notes/v0.2.0.md"): (d / f).unlink(missing_ok=True)   # the dry run models the FIRST selection of the Castle package, whatever release the repository has prepared since
        st["patches"]["genesis/castle-of-illusion/widescreen-practice"] = {"state": "eligible", "review": "dry run only (test fixture)"}; (d / "publication.json").write_text(json.dumps(st))
        run(S / "prepare_release.py", "--root", d, "begin", "--tag", "v0.2.0", "--package", f"{self.PID}@0.1.0", check=True)
        self.assertEqual(json.loads((d / "releases/v0.2.0.json").read_text())["packages"], [f"{self.PID}@0.1.0"])
        out = d / "dry-run"; ref = json.loads((d / "patches/genesis/castle-of-illusion/widescreen-practice/package.json").read_text())["packages"][0]["build"]["writer_ref"]   # the package's own recorded revision, which is not the global pin the newer Sonic packages use
        r = run(S / "build_packages.py", "--root", d, "--release", "v0.2.0", "--out", out, "--segarecomp", HCLI, "--segarecomp-ref", ref, "--cc", CC, "--sdk-dir", HSDK); self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(sorted(p.name for p in out.iterdir()), ["SHA256SUMS", f"{self.PID}.segapatch"])
        self.assertEqual((out / "SHA256SUMS").read_text().split(), [json.loads((d / "patches/genesis/castle-of-illusion/widescreen-practice/package.json").read_text())["packages"][0]["package_sha256"], f"{self.PID}.segapatch"])
        e = []; check_repo.check_assets(d, out, HCLI, e, "v0.2.0"); self.assertEqual(e, [], "the product's `mod inspect` agrees with the recorded identity, ABI and capabilities")
        for tool in ("debug-fly", "input-recorder"): self.assertFalse(any(tool in p.name for p in out.iterdir()))
        for internal in ("castle-of-illusion-debug-fly", "castle-of-illusion-input-recorder"):
            r = run(S / "prepare_release.py", "--root", d, "begin", "--tag", "v0.3.0", "--package", f"{internal}@0.1.0"); self.assertNotEqual(r.returncode, 0)

    def test_pack_and_build_produce_the_same_distributable_archive(self):
        p = ROOT / "patches/genesis/castle-of-illusion/widescreen-practice"; t = pathlib.Path(tempfile.mkdtemp()); self.addCleanup(shutil.rmtree, t)
        ok1, i1, b1 = check_repo.pack_mod_project(CLI, p, t / "a.segapatch", []); ok2, i2, b2 = check_repo.pack_mod_project(CLI, p, t / "b.segapatch", ["--cc", CC, "--sdk-dir", SDK])
        self.assertTrue(ok1 and ok2); self.assertEqual(b1, b2)


if __name__ == "__main__":
    unittest.main()
