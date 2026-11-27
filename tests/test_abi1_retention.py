"""Native ABI 1 retention (docs/abi1-retention.md): no new ABI 1 package, retained digests unchanged, and the catalog's derived deprecation field."""
import copy, json, pathlib, sys, types, unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import build_catalog, check_repo, release_meta, validate_catalog


def catalog(): return json.loads((ROOT / "catalog/index.json").read_text())


def abi1_errors(mutate):
    errs, found = [], False
    for pt in release_meta.patches(ROOT):
        if pt.is_mod or pt.path != "patches/genesis/sonic-1/native-widescreen": continue
        fake = types.SimpleNamespace(rel=pt.rel, meta=copy.deepcopy(pt.meta)); mutate(fake.meta["packages"]); check_repo.check_abi1_frozen(ROOT, fake, errs); found = True
    assert found
    return errs


class Retention(unittest.TestCase):
    def test_existing_packages_accepted(self):
        errs = []
        for pt in release_meta.patches(ROOT):
            if not pt.is_mod: check_repo.check_abi1_frozen(ROOT, pt, errs)
        self.assertEqual(errs, [])

    def test_retained_set_is_exactly_the_published_abi1_entries(self):
        self.assertEqual({f"{p['id']}@{p['version']}": p["package_sha256"] for p in catalog()["packages"] if p.get("native_abi") == 1}, check_repo.ABI1_RETAINED)

    def test_new_package_id_rejected(self):
        e = abi1_errors(lambda ps: ps.append(dict(ps[0], id="another-native-widescreen")))
        self.assertTrue(any("new native ABI 1" in x for x in e), e)

    def test_new_version_of_a_retained_id_rejected(self):
        e = abi1_errors(lambda ps: ps.append(dict(ps[0], version="2.0.2")))
        self.assertTrue(any("new native ABI 1" in x for x in e), e)

    def test_schema2_without_native_abi_field_rejected(self):
        def mutate(ps): extra = dict(ps[0], id="sneaky"); extra.pop("native_abi"); ps.append(extra)
        self.assertTrue(any("new native ABI 1" in x for x in abi1_errors(mutate)))

    def test_changed_digest_rejected(self):
        e = abi1_errors(lambda ps: ps[0].update(package_sha256="1" * 64))
        self.assertTrue(any("keeps its published digest" in x for x in e), e)

    def test_catalog_marks_exactly_the_abi1_entries(self):
        doc = json.loads(build_catalog.build(ROOT))
        for p in doc["packages"]:
            self.assertEqual(p.get("abi_status"), "deprecated" if p.get("native_abi") == 1 else None, p["id"])
        self.assertEqual(validate_catalog.validate_catalog(doc), [])

    def test_catalog_rejects_the_field_elsewhere_and_other_values(self):
        for pick, value in (((lambda p: p.get("native_abi") is None), "deprecated"), ((lambda p: p.get("native_abi") == 1), "removed"), ((lambda p: p.get("native_abi") == 2), "deprecated")):
            doc = catalog(); next(p for p in doc["packages"] if pick(p))["abi_status"] = value
            self.assertNotEqual(validate_catalog.validate_catalog(doc), [])

    def test_field_is_additive_over_the_catalog_without_it(self):
        old = catalog()
        for p in old["packages"]: p.pop("abi_status", None)
        self.assertEqual(validate_catalog.immutability_errors(old, catalog()), [])


if __name__ == "__main__":
    unittest.main()
