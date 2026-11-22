"""Release pipeline, immutability, provenance, source-review, accessibility and workflow-safety tests (no commercial data, no network)."""
import hashlib, json, pathlib, re, shutil, subprocess, sys, tempfile, unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import artifact_budget, check_repo, check_site_a11y, check_source_review, release_guard, release_meta, verify_provenance

WF = {p.name: p.read_text() for p in (ROOT / ".github/workflows").glob("*.yml")}


def tmp(t):
    d = pathlib.Path(tempfile.mkdtemp()); t.addCleanup(shutil.rmtree, d); return d


class Guard(unittest.TestCase):
    """The lifecycle cases are driven through the real scripts in tests/test_release_lifecycle.py; these pin the repository's own state."""
    def test_published_v010_is_immutable(self):
        e = release_guard.guard("v0.1.0", {"tagName": "v0.1.0", "isDraft": False}); self.assertTrue(any("immutable" in x for x in e), e)

    def test_published_v010_cannot_be_recreated(self):
        e = release_guard.guard("v0.1.0", None); self.assertTrue(any("deleted or inconsistent" in x for x in e), e)

    def test_bad_tag(self): self.assertTrue(any("v1.2.3" in x for x in release_guard.guard("latest", None)))

    def test_release_workflow_runs_the_guard_first(self):
        t = WF["release.yml"]; self.assertLess(t.index("release_guard.py"), t.index("gh release create"))
        self.assertIn("fetch-depth: 0", t)


class Budget(unittest.TestCase):
    def test_current_catalog_does_not_justify_r2(self):
        m = artifact_budget.measure(ROOT)
        for k in ("largest_package_bytes", "all_packages_bytes"): self.assertLess(m[k], artifact_budget.LIMITS[k])
        self.assertEqual(artifact_budget.main(["--root", str(ROOT)]), 0)

    def test_oversized_package_forces_the_decision(self):
        d = tmp(self); (d / "catalog").mkdir(); cat = json.loads((ROOT / "catalog/index.json").read_text()); cat["packages"][0]["package_size"] = 30 * 1024 * 1024
        (d / "catalog/index.json").write_text(json.dumps(cat)); self.assertEqual(artifact_budget.main(["--root", str(d)]), 1)

    def test_decision_document_records_the_numbers(self):
        t = (ROOT / "docs/artifact-hosting.md").read_text(); m = artifact_budget.measure(ROOT)
        self.assertIn(str(m["largest_package_bytes"]), t); self.assertIn(str(m["all_packages_bytes"]), t); self.assertIn("R2", t)


class Assets(unittest.TestCase):
    """A deliberately wrong digest must fail the pipeline (check_repo.py --assets is the pipeline's digest gate)."""
    def assets(self, t, root=ROOT):
        d = tmp(t); lines = []
        for pk in release_meta.packages(root):
            if pk.release != "v0.1.0": continue   # the assets of the historical v0.1.0 release (a later, prepared release has its own)
            data = b"synthetic-" + pk.id.encode(); (d / pk.package_file).write_bytes(data); lines.append(f"{pk.p['package_sha256']}  {pk.package_file}")
        (d / "SHA256SUMS").write_text("\n".join(lines) + "\n"); return d

    def test_wrong_digest_fails(self):
        e = []; check_repo.check_assets(ROOT, self.assets(self), None, e, "v0.1.0")
        self.assertTrue(any("asset SHA-256 differs" in x for x in e), e)

    def test_missing_sums_fails(self):
        d = self.assets(self); (d / "SHA256SUMS").unlink(); e = []; check_repo.check_assets(ROOT, d, None, e, "v0.1.0")
        self.assertTrue(any("SHA256SUMS" in x for x in e))

    def test_correct_digests_pass(self):
        d = tmp(self); lines = []; root = tmp(self)
        shutil.copytree(ROOT / "releases", root / "releases"); released = {pk.id for pk in release_meta.packages(ROOT) if pk.release == "v0.1.0"}
        for pj in sorted((ROOT / "patches").glob("*/*/*/package.json")):
            target = root / pj.relative_to(ROOT); target.parent.mkdir(parents=True, exist_ok=True); meta = json.loads(pj.read_text())
            for p in meta["packages"]:
                if p["id"] not in released: continue   # an unreleased package (the Castle candidate) is not part of any release's assets
                data = b"synthetic-" + p["id"].encode(); (d / p["package_file"]).write_bytes(data)
                p["package_sha256"] = hashlib.sha256(data).hexdigest(); p["package_size"] = len(data); lines.append(f"{p['package_sha256']}  {p['package_file']}")
            target.write_text(json.dumps(meta))
        (d / "SHA256SUMS").write_text("\n".join(lines) + "\n"); e = []; check_repo.check_assets(root, d, None, e, "v0.1.0"); self.assertEqual(e, [])


def git(d, *a): return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], cwd=d, check=True, capture_output=True, text=True).stdout.strip()


class Provenance(unittest.TestCase):
    """A one-patch repository whose release v1.0.0 is published at a real commit; `layout` says where the sources were at that commit."""
    def repo(self, layout="patch-dir"):
        d = tmp(self); git(d, "init", "-q", "-b", "main"); g = d / "patches/genesis/synth/p"
        base = g if layout == "patch-dir" else g.parent                       # game-dir: the v0.1.0 layout, sources directly under the game directory
        (base / "source").mkdir(parents=True)
        bps = b"BPS1"; (base / "source/p.bps").write_bytes(bps); prov = b"int x;"; (base / "source/provider.c").write_bytes(prov)
        manifest = {"id": "p", "version": "1.0.0", "payloads": {"rom": {"sha256": hashlib.sha256(bps).hexdigest()}}}; (base / "source/p.manifest.json").write_text(json.dumps(manifest))
        git(d, "add", "."); git(d, "commit", "-qm", "sources"); c = git(d, "rev-parse", "HEAD"); git(d, "tag", "v1.0.0", c)
        if layout == "game-dir":                                              # later commit: the files moved into the per-patch layout, bytes unchanged
            g.mkdir(parents=True); git(d, "mv", "patches/genesis/synth/source", "patches/genesis/synth/p/source")
        meta = {"package_format": 1, "platform": "genesis", "source_identity_kind": "cartridge-image-sha256", "bios_requirement": "none", "game": "Synth",
                "packages": [{"id": "p", "version": "1.0.0", "bps_sha256": hashlib.sha256(bps).hexdigest(), "bps": {"path": "source/p.bps", "sha256": hashlib.sha256(bps).hexdigest()},
                              "source": {"path": "source/provider.c", "sha256": hashlib.sha256(prov).hexdigest()}, "schema_version": 2, "trust": "trusted-native-source"}]}
        rel = {"release_format": 2, "release": "v1.0.0", "status": "published", "source_layout": layout, "build": {"writer": "w", "writer_ref": "b" * 40, "deterministic": True},
               "source_revision": {"repository": "https://github.com/o/r", "commit": c, "tag": "v1.0.0"}, "packages": ["p@1.0.0"]}
        (d / "releases").mkdir(); (g / "package.json").write_text(json.dumps(meta)); (d / "releases/v1.0.0.json").write_text(json.dumps(rel))
        git(d, "add", "."); git(d, "commit", "-qm", "release"); return d, g, rel, c

    def errs(self, d, head="HEAD"):
        e = []; verify_provenance.verify(d, e, head); return e

    def put(self, d, rel): (d / "releases/v1.0.0.json").write_text(json.dumps(rel))

    def test_reachable_commit_with_matching_digests_and_tag(self):
        d, *_ = self.repo(); self.assertEqual(self.errs(d), [])

    def test_a_release_whose_sources_were_later_moved_still_verifies_at_its_commit(self):
        d, g, rel, c = self.repo("game-dir"); self.assertFalse((d / "patches/genesis/synth/source").exists(), "the working tree uses the per-patch layout")
        self.assertEqual(self.errs(d), [])
        rel["source_layout"] = "patch-dir"; self.put(d, rel)   # claiming the wrong layout for that commit must fail: the files are not there
        self.assertTrue(any("not present" in x for x in self.errs(d)), self.errs(d))

    def test_missing_declared_tag_fails(self):
        d, *_ = self.repo(); git(d, "tag", "-d", "v1.0.0"); self.assertTrue(any("does not exist" in x for x in self.errs(d)), self.errs(d))

    def test_moved_tag_fails(self):
        d, g, rel, c = self.repo(); (d / "x.txt").write_text("x"); git(d, "add", "."); git(d, "commit", "-qm", "later"); git(d, "tag", "-f", "v1.0.0", "HEAD")
        self.assertTrue(any("not the source commit" in x for x in self.errs(d)), self.errs(d))

    def test_tag_for_another_release_fails(self):
        d, g, rel, c = self.repo(); git(d, "tag", "v2.0.0", c); rel["source_revision"]["tag"] = "v2.0.0"; self.put(d, rel)
        self.assertTrue(any("is not the release" in x for x in self.errs(d)), self.errs(d))

    def test_published_release_must_declare_its_tag(self):
        d, g, rel, c = self.repo(); del rel["source_revision"]["tag"]; self.put(d, rel); self.assertTrue(any("must declare its tag" in x for x in self.errs(d)))

    def test_tag_commit_without_tag_fails(self):
        d, g, rel, c = self.repo(); del rel["source_revision"]["tag"]; rel["source_revision"]["tag_commit"] = c; self.put(d, rel); self.assertTrue(any("tag_commit without a tag" in x for x in self.errs(d)))

    def test_historical_exception_pre_squash_tag_with_same_tree(self):
        d, g, rel, c = self.repo()   # tag on a side commit with the same tree as the source commit, not an ancestor of main
        git(d, "checkout", "-q", "--detach", c); git(d, "commit", "-q", "--allow-empty", "-m", "pre-squash head"); side = git(d, "rev-parse", "HEAD"); git(d, "tag", "-f", "v1.0.0", side); git(d, "checkout", "-q", "main")
        rel["source_revision"]["tag_commit"] = side; self.put(d, rel); self.assertEqual(self.errs(d), [])
        rel["source_revision"]["tag_commit"] = c; self.put(d, rel); self.assertTrue(any("not the recorded tag_commit" in x for x in self.errs(d)))

    def test_exception_with_a_different_tree_fails(self):
        d, g, rel, c = self.repo(); git(d, "checkout", "-q", "--detach", c); (d / "y.txt").write_text("y"); git(d, "add", "."); git(d, "commit", "-qm", "different tree"); side = git(d, "rev-parse", "HEAD")
        git(d, "tag", "-f", "v1.0.0", side); git(d, "checkout", "-q", "main"); rel["source_revision"]["tag_commit"] = side; self.put(d, rel)
        self.assertTrue(any("tree differs" in x for x in self.errs(d)), self.errs(d))

    def test_prepared_release_cannot_declare_a_tag(self):
        d, g, rel, c = self.repo(); rel["status"] = "prepared"; self.put(d, rel); self.assertTrue(any("cannot declare a tag" in x for x in self.errs(d)))

    def test_unreachable_commit_is_refused(self):
        d, g, rel, c = self.repo(); git(d, "checkout", "-q", "-b", "side", c); (d / "x.txt").write_text("x"); git(d, "add", "."); git(d, "commit", "-qm", "side")
        git(d, "checkout", "-q", "main"); git(d, "checkout", "-q", "--detach", "HEAD~1")
        rel["source_revision"]["commit"] = git(d, "rev-parse", "side"); git(d, "checkout", "-q", "main"); self.put(d, rel)
        e = self.errs(d); self.assertTrue(any("not an ancestor" in x for x in e), e)

    def test_digest_drift_at_commit_is_refused(self):
        d, g, rel, c = self.repo(); meta = json.loads((g / "package.json").read_text()); meta["packages"][0]["source"]["sha256"] = "0" * 64; (g / "package.json").write_text(json.dumps(meta))
        self.assertTrue(any("differs from package.json" in x for x in self.errs(d)))

    def test_missing_commit(self):
        d, g, rel, c = self.repo(); rel["source_revision"]["commit"] = "1" * 40; self.put(d, rel)
        self.assertTrue(any("does not exist" in x for x in self.errs(d)))

    def test_this_repository(self):
        e = []; verify_provenance.verify(ROOT, e)
        self.assertEqual([x for x in e if "shallow" not in x], [], e)


class SourceReview(unittest.TestCase):
    def test_repository_is_reviewed(self):
        e = []; check_source_review.check(ROOT, e); self.assertEqual(e, [])

    def copy(self):
        d = tmp(self)
        for p in ("patches", "docs"): shutil.copytree(ROOT / p, d / p)
        shutil.copy(ROOT / "publication.json", d / "publication.json")
        return d

    def test_changed_file_needs_rereview(self):
        d = self.copy(); (d / "patches/genesis/sonic-1/native-widescreen/source/provider.c").write_text("changed"); e = []; check_source_review.check(d, e)
        self.assertTrue(any("sha256 differs" in x for x in e), e)

    def test_new_file_needs_a_record(self):
        d = self.copy(); (d / "patches/genesis/sonic-1/native-widescreen/source/new.c").write_text("int y;"); e = []; check_source_review.check(d, e)
        self.assertTrue(any("no review record" in x for x in e), e)

    def test_embedded_table_is_refused(self):
        d = self.copy(); f = d / "patches/genesis/sonic-1/native-widescreen/source/provider.c"; f.write_text("static const unsigned char t[] = {" + ",".join(f"0x{i:02X}" for i in range(32)) + "};")
        check_source_review.main(["--root", str(d), "--write"]); e = []; check_source_review.check(d, e); self.assertTrue(any("embedded data" in x for x in e), e)

    def test_excluded_items_are_listed(self):
        d = self.copy(); r = json.loads((d / "docs/source-review.json").read_text()); r["excluded"] = []; (d / "docs/source-review.json").write_text(json.dumps(r))
        e = []; check_source_review.check(d, e); self.assertTrue(any("excluded" in x for x in e))


class A11y(unittest.TestCase):
    GOOD = '<html lang="en"><head><title>t</title></head><body><h1>a</h1><h2>b</h2><table><caption>c</caption><tr><th scope="col">x</th></tr></table><a href="/x">go</a></body></html>'

    def test_good(self): self.assertEqual(check_site_a11y.check_page(self.GOOD), [])
    def test_missing_lang(self): self.assertTrue(check_site_a11y.check_page(self.GOOD.replace(' lang="en"', "")))
    def test_two_h1(self): self.assertTrue(check_site_a11y.check_page(self.GOOD.replace("<h2>b</h2>", "<h1>b</h1>")))
    def test_heading_jump(self): self.assertTrue(check_site_a11y.check_page(self.GOOD.replace("<h2>b</h2>", "<h3>b</h3>")))
    def test_table_without_caption(self): self.assertTrue(check_site_a11y.check_page(self.GOOD.replace("<caption>c</caption>", "")))
    def test_header_without_scope(self): self.assertTrue(check_site_a11y.check_page(self.GOOD.replace(' scope="col"', "")))
    def test_empty_link(self): self.assertTrue(check_site_a11y.check_page(self.GOOD.replace(">go<", "><")))
    def test_image_without_alt(self): self.assertTrue(check_site_a11y.check_page(self.GOOD.replace("</body>", '<img src="a.png"></body>')))
    def test_imported_tables_are_out_of_scope(self): self.assertEqual(check_site_a11y.check_page(self.GOOD.replace("<caption>c</caption>", ""), tables=False), [])


class WorkflowSafety(unittest.TestCase):
    def test_no_pull_request_target_anywhere(self):
        for n, t in WF.items(): self.assertNotIn("pull_request_target", t, n)

    def test_no_third_party_deploy_or_secrets(self):
        for n, t in WF.items():
            self.assertNotIn("cloudflare", t.lower(), n); self.assertNotIn("secrets.", t, n)

    def test_least_privilege(self):
        for n, t in WF.items(): self.assertRegex(t, r"(?m)^permissions:", n)
        self.assertNotIn("contents: write", WF["pages.yml"])

    def test_pages_deploys_only_from_main_or_release(self):
        t = WF["pages.yml"]; self.assertNotIn("pull_request", t.split("jobs:")[0])
        self.assertIn("types: [published]", t); self.assertIn("branches: [main]", t)

    def test_pages_verifies_published_digests_before_deploying(self):
        t = WF["pages.yml"]; self.assertLess(t.index("check_repo.py --assets"), t.index("upload-pages-artifact"))
        for s in ("validate_catalog.py", "verify_provenance.py", "fetch-depth: 0"): self.assertIn(s, t)

    def test_release_event_never_deploys_the_tags_old_tree(self):
        for name in ("pages.yml", "verify-release.yml"):
            t = WF[name]; self.assertIn("github.event.repository.default_branch", t, name)
        self.assertIn("github.event_name == 'release' && github.event.repository.default_branch || github.ref", WF["pages.yml"])

    def test_every_asset_verification_is_scoped_to_a_release(self):
        for name, t in WF.items():
            for line in t.splitlines():
                if "check_repo.py --assets" in line: self.assertIn("--release", line, f"{name}: {line.strip()}")
        for name in ("check.yml", "release.yml"): self.assertIn("rebuild_release.py", WF[name])

    def test_routine_workflows_never_rebuild_every_historical_release(self):
        """The cost of a pull request or a release is proportional to what it publishes: only the full-audit workflow may use --all."""
        for name, t in WF.items():
            uses_all = [l for l in t.splitlines() if "rebuild_release.py" in l and "--all" in l]
            self.assertEqual(bool(uses_all), False, f"{name}: {uses_all}")
        self.assertIn("--affected-from", WF["check.yml"]); self.assertIn("--changed-from", WF["check.yml"])
        self.assertIn('rebuild_release.py --release "$TAG"', WF["release.yml"])
        self.assertIn("rebuild_release.py --release", WF["audit.yml"]); self.assertIn("--list", WF["audit.yml"])

    def test_the_audit_runs_only_on_demand_or_on_a_schedule(self):
        head = WF["audit.yml"].split("jobs:")[0]
        self.assertIn("workflow_dispatch", head); self.assertIn("schedule", head)
        for trigger in ("pull_request", "push:", "release:"): self.assertNotIn(trigger, head)

    def test_the_repository_job_builds_no_package(self):
        code = "\n".join(l for l in WF["check.yml"].split("  exec:")[0].splitlines() if not l.strip().startswith("#"))   # comments may name the scripts they deliberately do not run
        for s in ("rebuild_release.py", "build_packages.py", "mod pack", "--segarecomp"): self.assertNotIn(s, code, s)

    def test_the_product_is_built_only_at_a_full_pinned_revision(self):
        t = (ROOT / "scripts/build_product_cli.sh").read_text(); self.assertIn("[0-9a-f]{40}", t)
        for name in ("check.yml", "release.yml", "audit.yml"): self.assertNotIn("git clone", WF[name], name)

    def test_release_workflow_has_no_default_tag_and_uses_recorded_writer(self):
        t = WF["release.yml"]; self.assertNotIn("default: v0.1.0", t); self.assertNotIn("SEGAPATCH_REF", t)

    def test_check_workflow_has_full_history_and_catalog_gates(self):
        t = WF["check.yml"]; self.assertIn("fetch-depth: 0", t)
        for s in ("validate_catalog.py", "verify_provenance.py", "check_source_review.py"): self.assertIn(s, t)


if __name__ == "__main__": unittest.main()
