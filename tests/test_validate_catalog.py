"""Accept/reject fixtures for scripts/validate_catalog.py and the catalog schemas (no commercial data)."""
import copy, json, pathlib, shutil, subprocess, sys, tempfile, unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import validate_catalog as vc

EXAMPLE = json.loads((ROOT / "catalog/examples/valid-catalog.json").read_text())
REAL = json.loads((ROOT / "catalog/index.json").read_text())


def mutated(fn, doc=EXAMPLE):
    d = copy.deepcopy(doc); fn(d); return d


class Accepts(unittest.TestCase):
    def test_example(self): self.assertEqual(vc.validate_catalog(EXAMPLE), [])
    def test_published_catalog(self): self.assertEqual(vc.validate_catalog(REAL), [])
    def test_repository(self):
        e = []; vc.validate_repository(ROOT, e); self.assertEqual(e, [])
    def test_schema_uses_only_implemented_keywords(self):
        for n in ("catalog", "release"):
            def walk(s):
                self.assertFalse(set(s) - vc.SUPPORTED, set(s) - vc.SUPPORTED)
                for v in s.get("properties", {}).values(): walk(v)
                if "items" in s: walk(s["items"])
            walk(vc.load_schema(n))


class Rejects(unittest.TestCase):
    def bad(self, fn, needle, doc=EXAMPLE):
        e = vc.validate_catalog(mutated(fn, doc)); self.assertTrue(any(needle in x for x in e), (needle, e))

    def test_missing_digest(self): self.bad(lambda d: d["packages"][0].pop("package_sha256"), "missing required 'package_sha256'")
    def test_short_digest(self): self.bad(lambda d: d["packages"][0].update(package_sha256="0" * 10), "package_sha256")
    def test_unknown_trust(self): self.bad(lambda d: d["packages"][0].update(trust="trusted-by-vibes"), "not one of")
    def test_non_https(self): self.bad(lambda d: d["packages"][0]["asset"].update(url="http://github.com/x/y/releases/download/v1.0.0/synthetic-demo.segapatch"), "asset")
    def test_latest_url(self):
        self.bad(lambda d: d["packages"][0]["asset"].update(url="https://github.com/marinocg/segarecomp-patches/releases/latest/download/synthetic-demo.segapatch"), "version-pinned")
    def test_unknown_field(self): self.bad(lambda d: d["packages"][0].update(sneaky=1), "unknown field")
    def test_unknown_tier(self): self.bad(lambda d: d["packages"][0].update(evidence_tier="trust-me"), "not one of")
    def test_duplicate_version(self): self.bad(lambda d: d["packages"].append(copy.deepcopy(d["packages"][0])), "duplicate")
    def test_missing_provenance(self): self.bad(lambda d: d["packages"][0].pop("source_revision"), "source_revision")
    def test_short_commit(self): self.bad(lambda d: d["packages"][0]["source_revision"].update(commit="abc1234"), "commit")
    def test_catalog_format(self): self.bad(lambda d: d.update(catalog_format=2), "catalog_format")
    def test_native_inconsistent(self): self.bad(lambda d: d["packages"][0].update(trust="trusted-native-source"), "disagree")
    def test_supersession_dangling(self): self.bad(lambda d: d["packages"][0].update(superseded_by="nothing@9.9.9"), "not in this catalog")
    def test_supersession_cycle(self):
        def f(d): d["packages"][1]["superseded_by"] = "synthetic-demo@1.0.0"
        self.bad(f, "cycle")
    def test_unimplemented_keyword_is_an_error(self):
        e = vc.schema_errors("x", {"type": "string", "format": "uri"}); self.assertTrue(any("not implemented" in x for x in e))


class Immutability(unittest.TestCase):
    def test_additive_supersession_is_allowed(self):
        old = mutated(lambda d: d["packages"][0].pop("superseded_by"))
        self.assertEqual(vc.immutability_errors(old, EXAMPLE), [])

    def test_new_entry_is_allowed(self): self.assertEqual(vc.immutability_errors(mutated(lambda d: d["packages"].pop()), EXAMPLE), [])

    def test_digest_change_is_rejected(self):
        new = mutated(lambda d: d["packages"][0].update(package_sha256="9" * 64))
        self.assertTrue(any("package_sha256" in x for x in vc.immutability_errors(EXAMPLE, new)))

    def test_new_optional_field_is_allowed(self):
        old = mutated(lambda d: d["packages"][0].pop("region")); self.assertEqual(vc.immutability_errors(old, EXAMPLE), [])

    def test_field_removal_is_rejected(self):
        new = mutated(lambda d: d["packages"][0].pop("region")); self.assertTrue(any("'region' was removed" in x for x in vc.immutability_errors(EXAMPLE, new)))

    def test_removal_is_rejected(self):
        self.assertTrue(any("removed" in x for x in vc.immutability_errors(EXAMPLE, mutated(lambda d: d["packages"].pop(0)))))

    def test_supersession_cannot_be_rewritten(self):
        new = mutated(lambda d: d["packages"][0].update(superseded_by="synthetic-demo-2@1.0.1", name="renamed"))
        self.assertTrue(any("'name' changed" in x for x in vc.immutability_errors(EXAMPLE, new)))

    def test_published_entry_fields_are_pinned(self):
        for k in ("asset", "source_revision", "evidence_tier", "package_identity"):
            new = copy.deepcopy(REAL); new["packages"][0][k] = "tampered"
            self.assertTrue(any(repr(k) in x for x in vc.immutability_errors(REAL, new)), k)

    def test_git_baseline_round_trip(self):
        d = pathlib.Path(tempfile.mkdtemp()); self.addCleanup(shutil.rmtree, d)
        run = lambda *a: subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], cwd=d, check=True, capture_output=True)
        run("init", "-q"); (d / "catalog").mkdir(); (d / "catalog/index.json").write_text(json.dumps(EXAMPLE)); run("add", "."); run("commit", "-qm", "x")
        self.assertEqual(vc.baseline_from_ref(d, "HEAD"), EXAMPLE); self.assertIsNone(vc.baseline_from_ref(d, "no-such-ref"))


class Repository(unittest.TestCase):
    def copy(self):
        d = pathlib.Path(tempfile.mkdtemp()); self.addCleanup(shutil.rmtree, d)
        for p in ("catalog", "patches"): shutil.copytree(ROOT / p, d / p)
        return d

    def test_release_json_without_provenance_fails(self):
        d = self.copy(); f = d / "patches/genesis/sonic-1/release.json"; j = json.loads(f.read_text()); del j["source_revision"]; f.write_text(json.dumps(j))
        e = []; vc.validate_repository(d, e); self.assertTrue(any("source_revision" in x for x in e), e)

    def test_mutated_published_digest_fails_against_baseline(self):
        d = self.copy(); f = d / "catalog/index.json"; j = json.loads(f.read_text()); j["packages"][0]["package_sha256"] = "7" * 64; f.write_text(json.dumps(j))
        e = []; vc.validate_repository(d, e, REAL); self.assertTrue(any("package_sha256" in x for x in e), e)


if __name__ == "__main__": unittest.main()
