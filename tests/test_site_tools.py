"""Tests for the documentation-site tools: link checker, import/drift rule, sample runner, claim lint (no network, no product checkout)."""
import copy, json, pathlib, shutil, sys, tempfile, unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import check_site_content, check_site_links, import_product_docs as ipd, run_guide_samples as rgs

PIN = {"pin_format": 1, "repository": "o/r", "pinned_commit": "a" * 40, "minimum_commit": "a" * 40,
       "files": [{"source": "docs/product/a.md", "page": "product/a"}, {"source": "docs/product/b.md", "page": "product/b"}]}


def tmp(test):
    d = pathlib.Path(tempfile.mkdtemp()); test.addCleanup(shutil.rmtree, d); return d


class Links(unittest.TestCase):
    def setUp(self):
        self._base = check_site_links.BASE; check_site_links.BASE = ""; self.addCleanup(setattr, check_site_links, "BASE", self._base)

    def test_base_path_enforced(self):
        d = tmp(self) / "dist"; (d / "a").mkdir(parents=True); (d / "404.html").write_text("x")
        (d / "index.html").write_text('<a href="/site/a/">ok</a><a href="/a/">unprefixed</a>'); (d / "a/index.html").write_text("<p>a</p>")
        check_site_links.BASE = "/site"; e = check_site_links.check(d)
        self.assertEqual(len(e), 1); self.assertIn("outside the base path", e[0])

    def site(self, extra=""):
        d = tmp(self) / "dist"; (d / "a").mkdir(parents=True)
        (d / "index.html").write_text('<a href="/a/">a</a><img src="/logo.svg"><a href="https://example.com/x">ext</a>' + extra)
        (d / "a/index.html").write_text('<h2 id="top">t</h2><a href="../index.html">home</a><a href="#top">self</a>')
        (d / "404.html").write_text("<p>no</p>"); (d / "logo.svg").write_text("<svg/>"); return d

    def test_clean(self): self.assertEqual(check_site_links.check(self.site()), [])
    def test_missing_target(self): self.assertTrue(any("target not found" in e for e in check_site_links.check(self.site('<a href="/nope/">x</a>'))))
    def test_missing_anchor(self): self.assertTrue(any("no such anchor" in e for e in check_site_links.check(self.site('<a href="/a/#zzz">x</a>'))))
    def test_missing_asset(self): self.assertTrue(any("favicon" in e for e in check_site_links.check(self.site('<link rel="icon" href="/favicon.svg">'))))
    def test_escape(self): self.assertTrue(any("escapes" in e for e in check_site_links.check(self.site('<a href="../../etc/passwd">x</a>'))))
    def test_needs_404(self):
        d = self.site(); (d / "404.html").unlink(); self.assertTrue(any("404" in e for e in check_site_links.check(d)))
    def test_css_url_checked(self):
        d = self.site(); (d / "a.css").write_text("@font-face{src:url(/fonts/x.ttf)} .b{background:url('data:image/png;base64,AA')}")
        self.assertTrue(any("x.ttf" in e for e in check_site_links.check(d)))
        (d / "fonts").mkdir(); (d / "fonts/x.ttf").write_text("f"); self.assertEqual(check_site_links.check(d), [])

    def test_unbuilt(self): self.assertTrue(check_site_links.check(tmp(self)))


class Import(unittest.TestCase):
    def test_link_rewriting(self):
        t = "[b](b.md#x) [c](../../platforms/c.md) [self](#s) [web](https://x.y/z) ![img](shots/i.png) [up](../../../outside.md)"
        out = ipd.rewrite_links(t, "docs/product/a.md", PIN)
        self.assertIn("[b](/product/b/#x)", out); self.assertIn("[c](https://github.com/o/r/blob/" + "a" * 40 + "/platforms/c.md)", out)
        self.assertIn("[self](#s)", out); self.assertIn("[web](https://x.y/z)", out)
        self.assertIn("![img](https://raw.githubusercontent.com/o/r/" + "a" * 40 + "/docs/product/shots/i.png)", out); self.assertIn(" up ", out + " ") 

    def test_render_requires_title_and_adds_notice(self):
        with self.assertRaises(SystemExit): ipd.render(PIN, PIN["files"][0], "no title\n")
        page = ipd.render(PIN, PIN["files"][0], "# T \"q\"\n\nbody\n")
        self.assertIn('title: "T \\"q\\""', page); self.assertIn("Imported product documentation", page); self.assertTrue(page.endswith("body\n"))

    def test_title_has_no_markdown_backticks(self):
        self.assertIn('title: "Patch packages (.segapatch)"', ipd.render(PIN, PIN["files"][0], "# Patch packages (`.segapatch`)\n\nx\n"))

    def test_committed_pages_match_fresh_render_structure(self):
        pin = ipd.load_pin()
        for f in pin["files"]:
            t = (ROOT / "site/src/content/docs" / (f["page"] + ".md")).read_text()
            self.assertIn(pin["pinned_commit"][:12], t); self.assertIn(f["source"], t)

    def test_drift(self):
        pin = copy.deepcopy(PIN); self.assertIsNone(ipd.drift(pin))
        pin["minimum_commit"] = "b" * 40
        self.assertIsNone(ipd.drift(pin, compare=lambda lo, hi: "ahead"))
        self.assertIn("not at or after", ipd.drift(pin, compare=lambda lo, hi: "behind"))
        self.assertIn("diverged", ipd.drift(pin, compare=lambda lo, hi: "diverged"))

    def test_pin_validation(self):
        d = tmp(self); bad = copy.deepcopy(PIN); bad["pinned_commit"] = "main"; (d / "p.json").write_text(json.dumps(bad))
        with self.assertRaises(SystemExit): ipd.load_pin(d / "p.json")
        real = ipd.load_pin(); self.assertEqual(real["pinned_commit"], real["minimum_commit"])


class Samples(unittest.TestCase):
    def test_guide_is_fully_marked(self):
        blocks, errs = rgs.parse(rgs.DEFAULT_PAGE.read_text()); self.assertEqual(errs, []); self.assertGreaterEqual(len(blocks), 6)
        self.assertTrue(any(b[1] == "exec" for b in blocks) and any(b[1] == "exec-cli" for b in blocks))

    def test_unmarked_block_rejected(self): self.assertTrue(rgs.parse("text\n```sh\necho hi\n```\n")[1])
    def test_orphan_marker_rejected(self): self.assertTrue(rgs.parse("<!-- sample: exec -->\n\nprose\n```sh\nx\n```\n")[1])
    def test_unknown_marker_rejected(self): self.assertTrue(rgs.parse("<!-- sample: maybe -->\n```sh\nx\n```\n")[1])
    def test_reason_required(self): self.assertTrue(rgs.parse("<!-- sample: non-executable -->\n```sh\nx\n```\n")[1])
    def test_unterminated(self): self.assertTrue(rgs.parse("<!-- sample: exec -->\n```sh\nx\n")[1])

    def test_execution_results(self):
        env = {"WORK": "w", "SEGAPATCH": "s", "SDK_INCLUDE": "i", "PATH": "/usr/bin:/bin"}
        ok, e = rgs.parse("<!-- sample: exec -->\n```sh\ntrue\n```\n<!-- sample: non-executable: demo -->\n```sh\nfalse\n```\n"); self.assertEqual((e, rgs.run(ok, env)), ([], []))
        bad, _ = rgs.parse("<!-- sample: exec -->\n```sh\nfalse\n```\n"); self.assertTrue(rgs.run(bad, env))
        cli, _ = rgs.parse("<!-- sample: exec-cli -->\n```sh\ntrue\n```\n"); self.assertTrue(any("SEGARECOMP" in x for x in rgs.run(cli, env)))
        self.assertEqual(rgs.run(cli, dict(env, SEGARECOMP="x")), [])
        pipe, _ = rgs.parse("<!-- sample: exec -->\n```sh\nfalse | cat\n```\n"); self.assertTrue(rgs.run(pipe, env))


class Content(unittest.TestCase):
    def site(self, text):
        d = tmp(self); docs = d / "site/src/content/docs"; (docs / "product").mkdir(parents=True); (d / "docs").mkdir()
        shutil.copy(ROOT / "docs/product-docs.pin.json", d / "docs/product-docs.pin.json")
        shutil.copy(ROOT / "site/src/content/docs/support.md", docs / "support.md")
        (docs / "page.md").write_text(text); return d

    def test_repo_clean(self): self.assertEqual(check_site_content.check(ROOT), [])
    def test_blanket_claim(self): self.assertTrue(any("blanket" in e for e in check_site_content.check(self.site("Works with all games.\n"))))
    def test_guarantee(self): self.assertTrue(any("blanket" in e for e in check_site_content.check(self.site("We guarantee it.\n"))))
    def test_future_feature(self): self.assertTrue(any("not clearly negated" in e for e in check_site_content.check(self.site("Use Luau scripts today.\n"))))
    def test_future_feature_negated(self): self.assertEqual(check_site_content.check(self.site("Luau is reserved and not available.\n")), [])
    def test_support_must_pin_ledger(self):
        d = self.site("ok\n"); s = d / "site/src/content/docs/support.md"; s.write_text(s.read_text().replace("8fa9f66f839bbd750fb9171ac0d67016ca2b08d4", "main"))
        self.assertTrue(any("pinned revision" in e for e in check_site_content.check(d)))
    def test_import_needs_notice(self):
        d = self.site("ok\n"); (d / "site/src/content/docs/product/x.md").write_text("# x\n"); self.assertTrue(any("provenance" in e for e in check_site_content.check(d)))


if __name__ == "__main__":
    unittest.main()
