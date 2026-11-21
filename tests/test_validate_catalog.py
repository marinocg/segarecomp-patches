"""Accept/reject fixtures for scripts/validate_catalog.py and the catalog schemas (no commercial data)."""
import copy, json, pathlib, shutil, subprocess, sys, tempfile, unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import validate_catalog as vc

EXAMPLE = json.loads((ROOT / "catalog/examples/valid-catalog.json").read_text())
EXAMPLE_1 = json.loads((ROOT / "catalog/examples/valid-catalog-1.json").read_text())   # catalog_format 1 stays valid for the documents published under it
REAL = json.loads((ROOT / "catalog/index.json").read_text())
MOD = 2   # index of the schema 3 entry in the example


def mutated(fn, doc=EXAMPLE):
    d = copy.deepcopy(doc); fn(d); return d


class Accepts(unittest.TestCase):
    def test_example(self): self.assertEqual(vc.validate_catalog(EXAMPLE), [])
    def test_format_1_example_still_validates(self): self.assertEqual(vc.validate_catalog(EXAMPLE_1), [])
    def test_format_2_keeps_every_format_1_entry_unchanged(self):
        self.assertEqual(EXAMPLE["packages"][:2], EXAMPLE_1["packages"], "catalog_format 2 only ADDS the schema 3 entry shape")
    def test_a_valid_schema_3_entry_has_no_bps_or_patched_image_fields(self):
        m = EXAMPLE["packages"][MOD]; self.assertEqual(m["schema_version"], 3)
        self.assertFalse({"bps_sha256", "patched_image_sha256", "source_image_sha256", "native_source_sha256", "bps", "revision", "region"} & set(m))
    def test_published_catalog(self): self.assertEqual(vc.validate_catalog(REAL), [])
    def test_repository(self):
        e = []; vc.validate_repository(ROOT, e); self.assertEqual(e, [])
    def test_schema_uses_only_implemented_keywords(self):
        for n, versions in (("catalog", (1, 2)), ("release", (1, 2)), ("package", (1,))):
            for v in versions:
                def walk(s):
                    self.assertFalse(set(s) - vc.SUPPORTED, set(s) - vc.SUPPORTED)
                    for x in s.get("properties", {}).values(): walk(x)
                    for x in s.get("oneOf", []): walk(x)
                    if "items" in s: walk(s["items"])
                walk(vc.load_schema(n, version=v))
    def test_every_served_schema_is_valid_json_with_its_own_id(self):
        for f in sorted((ROOT / "catalog/schema").glob("*.schema.json")):
            s = json.loads(f.read_text()); self.assertTrue(s["$id"].endswith(f"/schema/{f.name}"), f.name)


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
    def test_catalog_format(self): self.bad(lambda d: d.update(catalog_format=3), "catalog_format")
    def test_format_1_reader_contract_refuses_a_schema_3_entry(self):
        doc = copy.deepcopy(EXAMPLE); doc["catalog_format"] = 1
        e = vc.validate_catalog(doc); self.assertTrue(e, "a schema 3 entry must not validate as catalog_format 1")

    # schema 3 / ABI 2 mod entries
    def test_mod_wrong_abi(self): self.bad(lambda d: d["packages"][MOD].update(native_abi=1), "native_abi")
    def test_mod_missing_capabilities(self): self.bad(lambda d: d["packages"][MOD].pop("capabilities"), "capabilities")
    def test_mod_empty_capabilities(self): self.bad(lambda d: d["packages"][MOD].update(capabilities=[]), "fewer than 1")
    def test_mod_with_a_fabricated_bps_or_rom_field_is_rejected(self):
        for k, v in (("bps_sha256", "0" * 64), ("patched_image_sha256", "0" * 64), ("source_image_sha256", "0" * 64), ("native_source_sha256", "0" * 64)):
            self.bad(lambda d, k=k, v=v: d["packages"][MOD].update({k: v}), "unknown field")
    def test_mod_needs_its_images(self): self.bad(lambda d: d["packages"][MOD].pop("images"), "images")
    def test_mod_image_digest_must_be_a_sha256(self): self.bad(lambda d: d["packages"][MOD]["images"][0].update(sha256="0" * 10), "sha256")
    def test_mod_missing_digest(self): self.bad(lambda d: d["packages"][MOD].pop("package_sha256"), "package_sha256")
    def test_mod_wrong_digest_shape(self): self.bad(lambda d: d["packages"][MOD].update(package_identity="xyz"), "package_identity")
    def test_mod_must_be_executable_trusted_native(self):
        self.bad(lambda d: d["packages"][MOD].update(executable_code=False), "not one of")
        self.bad(lambda d: d["packages"][MOD].update(trust="data-only"), "not one of")
    def test_mod_needs_the_exact_asset_url_of_its_release(self):
        self.bad(lambda d: d["packages"][MOD]["asset"].update(url="https://github.com/marinocg/segarecomp-patches/releases/download/v9.9.9/synthetic-mod.segapatch"), "version-pinned")
    def test_mod_needs_its_source_path(self): self.bad(lambda d: d["packages"][MOD].pop("source_path"), "source_path")
    def test_unknown_schema_version(self): self.bad(lambda d: d["packages"][MOD].update(schema_version=4), "alternatives")
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
        for p in ("catalog", "patches", "releases"): shutil.copytree(ROOT / p, d / p)
        shutil.copy(ROOT / "publication.json", d / "publication.json")
        return d

    def test_published_release_without_provenance_fails(self):
        d = self.copy(); f = d / "releases/v0.1.0.json"; j = json.loads(f.read_text()); del j["source_revision"]["commit"]; f.write_text(json.dumps(j))
        e = []; vc.validate_repository(d, e); self.assertTrue(any("commit" in x for x in e), e)

    def test_a_release_cannot_list_a_package_nobody_defines(self):
        d = self.copy(); f = d / "releases/v0.1.0.json"; j = json.loads(f.read_text()); j["packages"] = sorted(j["packages"] + ["ghost@1.0.0"]); f.write_text(json.dumps(j))
        e = []; vc.validate_repository(d, e); self.assertTrue(any("unknown package ghost@1.0.0" in x for x in e), e)

    def test_removing_a_published_release_record_is_caught(self):
        import build_catalog, check_repo
        d = self.copy(); (d / "releases/v0.1.0.json").unlink()
        e = []; check_repo.check(d, e); self.assertTrue(any("catalog/index.json is stale" in x for x in e), "a stale catalog is caught by the repository check")
        (d / "catalog/index.json").write_text(build_catalog.build(d))   # even a regenerated catalog cannot drop a published entry
        e = []; vc.validate_repository(d, e, REAL); self.assertTrue(any("was removed" in x for x in e), e)

    def test_mutated_published_digest_fails_against_baseline(self):
        d = self.copy(); f = d / "catalog/index.json"; j = json.loads(f.read_text()); j["packages"][0]["package_sha256"] = "7" * 64; f.write_text(json.dumps(j))
        e = []; vc.validate_repository(d, e, REAL); self.assertTrue(any("package_sha256" in x for x in e), e)


if __name__ == "__main__": unittest.main()
