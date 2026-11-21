"""Release pipeline, immutability, provenance, source-review, accessibility and workflow-safety tests (no commercial data, no network)."""
import hashlib, json, pathlib, re, shutil, subprocess, sys, tempfile, unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import artifact_budget, check_repo, check_site_a11y, check_source_review, release_guard, verify_provenance

WF = {p.name: p.read_text() for p in (ROOT / ".github/workflows").glob("*.yml")}


def tmp(t):
    d = pathlib.Path(tempfile.mkdtemp()); t.addCleanup(shutil.rmtree, d); return d


class Guard(unittest.TestCase):
    def test_published_release_is_immutable(self):
        e = release_guard.guard("v0.1.0", {"tagName": "v0.1.0", "isDraft": False})
        self.assertTrue(any("immutable" in x for x in e), e)

    def test_draft_is_never_overwritten(self):
        e = release_guard.guard("v0.1.0", {"tagName": "v0.1.0", "isDraft": True}); self.assertTrue(any("never overwrites" in x for x in e), e)

    def test_catalogued_tag_without_release_is_refused(self):
        e = release_guard.guard("v0.1.0", None); self.assertTrue(any("already lists" in x for x in e), e)

    def test_new_tag_needs_release_notes(self):
        self.assertTrue(any("release-notes" in x for x in release_guard.guard("v9.9.9", None)))

    def test_new_tag_with_notes_passes(self):
        d = tmp(self); (d / "catalog").mkdir(); (d / "docs/release-notes").mkdir(parents=True)
        (d / "catalog/index.json").write_text(json.dumps({"catalog_format": 1, "packages": []})); (d / "docs/release-notes/v1.2.3.md").write_text("n")
        self.assertEqual(release_guard.guard("v1.2.3", None, d), [])

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
    def assets(self, t):
        d = tmp(t); lines = []
        for rj in sorted((ROOT / "patches").glob("*/*/release.json")):
            for p in json.loads(rj.read_text())["packages"]:
                data = b"synthetic-" + p["id"].encode(); (d / p["package_file"]).write_bytes(data); lines.append(f"{p['package_sha256']}  {p['package_file']}")
        (d / "SHA256SUMS").write_text("\n".join(lines) + "\n"); return d

    def test_wrong_digest_fails(self):
        e = []; check_repo.check_assets(ROOT, self.assets(self), None, e)
        self.assertTrue(any("asset SHA-256 differs" in x for x in e), e)

    def test_missing_sums_fails(self):
        d = self.assets(self); (d / "SHA256SUMS").unlink(); e = []; check_repo.check_assets(ROOT, d, None, e)
        self.assertTrue(any("SHA256SUMS" in x for x in e))

    def test_correct_digests_pass(self):
        d = tmp(self); lines = []
        root = tmp(self)
        for rj in sorted((ROOT / "patches").glob("*/*/release.json")):
            target = root / rj.relative_to(ROOT); target.parent.mkdir(parents=True, exist_ok=True); rel = json.loads(rj.read_text())
            for p in rel["packages"]:
                data = b"synthetic-" + p["id"].encode(); (d / p["package_file"]).write_bytes(data)
                p["package_sha256"] = hashlib.sha256(data).hexdigest(); p["package_size"] = len(data); lines.append(f"{p['package_sha256']}  {p['package_file']}")
            target.write_text(json.dumps(rel))
        (d / "SHA256SUMS").write_text("\n".join(lines) + "\n"); e = []; check_repo.check_assets(root, d, None, e); self.assertEqual(e, [])


def git(d, *a): return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], cwd=d, check=True, capture_output=True, text=True).stdout.strip()


class Provenance(unittest.TestCase):
    def repo(self):
        d = tmp(self); git(d, "init", "-q", "-b", "main"); g = d / "patches/genesis/synth"; (g / "source").mkdir(parents=True)
        bps = b"BPS1"; (g / "source/p.bps").write_bytes(bps); prov = b"int x;"; (g / "source/provider.c").write_bytes(prov)
        manifest = {"id": "p", "version": "1.0.0", "payloads": {"rom": {"sha256": hashlib.sha256(bps).hexdigest()}}}; (g / "source/p.manifest.json").write_text(json.dumps(manifest))
        git(d, "add", "."); git(d, "commit", "-qm", "sources"); c = git(d, "rev-parse", "HEAD")
        rel = {"source_revision": {"repository": "https://github.com/o/r", "commit": c}, "packages": [{"id": "p", "version": "1.0.0", "bps_sha256": hashlib.sha256(bps).hexdigest(),
               "bps": {"path": "source/p.bps", "sha256": hashlib.sha256(bps).hexdigest()}, "source": {"path": "source/provider.c", "sha256": hashlib.sha256(prov).hexdigest()}}]}
        (g / "release.json").write_text(json.dumps(rel)); git(d, "add", "."); git(d, "commit", "-qm", "release"); return d, g, rel, c

    def errs(self, d, head="HEAD"):
        e = []; verify_provenance.verify(d, e, head); return e

    def test_reachable_commit_with_matching_digests(self):
        d, *_ = self.repo(); self.assertEqual(self.errs(d), [])

    def test_unreachable_commit_is_refused(self):
        d, g, rel, c = self.repo(); git(d, "checkout", "-q", "-b", "side", c); (d / "x.txt").write_text("x"); git(d, "add", "."); git(d, "commit", "-qm", "side")
        git(d, "checkout", "-q", "main"); git(d, "checkout", "-q", "--detach", "HEAD~1")
        rel["source_revision"]["commit"] = git(d, "rev-parse", "side"); git(d, "checkout", "-q", "main"); (g / "release.json").write_text(json.dumps(rel))
        e = self.errs(d); self.assertTrue(any("not an ancestor" in x for x in e), e)

    def test_digest_drift_at_commit_is_refused(self):
        d, g, rel, c = self.repo(); rel["packages"][0]["source"]["sha256"] = "0" * 64; (g / "release.json").write_text(json.dumps(rel))
        self.assertTrue(any("differs from release.json" in x for x in self.errs(d)))

    def test_missing_commit(self):
        d, g, rel, c = self.repo(); rel["source_revision"]["commit"] = "1" * 40; (g / "release.json").write_text(json.dumps(rel))
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
        return d

    def test_changed_file_needs_rereview(self):
        d = self.copy(); (d / "patches/genesis/sonic-1/source/provider.c").write_text("changed"); e = []; check_source_review.check(d, e)
        self.assertTrue(any("sha256 differs" in x for x in e), e)

    def test_new_file_needs_a_record(self):
        d = self.copy(); (d / "patches/genesis/sonic-1/source/new.c").write_text("int y;"); e = []; check_source_review.check(d, e)
        self.assertTrue(any("no review record" in x for x in e), e)

    def test_embedded_table_is_refused(self):
        d = self.copy(); f = d / "patches/genesis/sonic-1/source/provider.c"; f.write_text("static const unsigned char t[] = {" + ",".join(f"0x{i:02X}" for i in range(32)) + "};")
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

    def test_secrets_only_in_deploy_jobs(self):
        t = WF["cloudflare-pages.yml"]; build = t[t.index("  build:"):t.index("  preview:")]
        self.assertNotIn("secrets.", build); self.assertNotIn("CLOUDFLARE_API_TOKEN", build)

    def test_fork_pull_requests_cannot_reach_deploy(self):
        t = WF["cloudflare-pages.yml"]; self.assertIn("github.event.pull_request.head.repo.full_name == github.repository", t)
        self.assertIn("github.event_name != 'pull_request'", t)

    def test_least_privilege(self):
        for n, t in WF.items(): self.assertRegex(t, r"(?m)^permissions:", n)
        t = WF["cloudflare-pages.yml"]; self.assertNotIn("contents: write", t); self.assertNotIn("id-token", t)
        self.assertEqual(len(re.findall(r"CLOUDFLARE_API_TOKEN: \$\{\{ secrets\.CLOUDFLARE_API_TOKEN \}\}", t)), 2)

    def test_deploy_jobs_use_environments(self):
        t = WF["cloudflare-pages.yml"]; self.assertIn("environment: cloudflare-preview", t); self.assertIn("name: cloudflare-production", t)

    def test_check_workflow_has_full_history_and_catalog_gates(self):
        t = WF["check.yml"]; self.assertIn("fetch-depth: 0", t)
        for s in ("validate_catalog.py", "verify_provenance.py", "check_source_review.py"): self.assertIn(s, t)

    def test_cloudflare_setup_is_documented(self):
        t = (ROOT / "docs/cloudflare-pages.md").read_text()
        for s in ("CLOUDFLARE_API_TOKEN", "cloudflare-production", "Cloudflare Pages: Edit", "fork"): self.assertIn(s, t)


if __name__ == "__main__": unittest.main()
