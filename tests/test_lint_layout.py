"""Positive and negative fixtures for scripts/lint_layout.py (no commercial data)."""
import copy, json, pathlib, shutil, sys, tempfile, unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import lint_layout

GOOD = {"release_format": 1, "platform": "genesis", "source_identity_kind": "cartridge-image-sha256", "bios_requirement": "none",
        "game": "Synthetic", "release": "v1.0.0",
        "packages": [{"id": "synthetic-demo", "version": "1.0.0", "schema_version": 1, "package_file": "synthetic-demo.segapatch"},
                     {"id": "synthetic-native", "version": "1.2.0-rc.1", "schema_version": 2, "native_abi": 1,
                      "capabilities": ["frame.vdp"], "package_file": "synthetic-native.segapatch"}]}


class Layout(unittest.TestCase):
    def project(self, platform="genesis", game="synthetic", release=None):
        """A generated, fabricated project tree; the fixtures are built, never copied from a game."""
        root = pathlib.Path(tempfile.mkdtemp()); self.addCleanup(shutil.rmtree, root)
        d = root / "patches" / platform / game; (d / "source").mkdir(parents=True)
        (d / "README.md").write_text("# Synthetic\n"); rel = copy.deepcopy(release or GOOD)
        (d / "release.json").write_text(json.dumps(rel))
        for n in ("synthetic-demo.bps", "synthetic-demo.manifest.json", "synthetic-native.bps", "synthetic-native.manifest.json", "provider.c"):
            (d / "source" / n).write_text("x")
        return root, d

    def errs(self, root):
        e = []; lint_layout.lint(root, e); return e

    def test_positive_generated_project(self): self.assertEqual(self.errs(self.project()[0]), [])
    def test_positive_repository(self): self.assertEqual(self.errs(ROOT), [])

    def expect(self, root, fragment):
        e = self.errs(root); self.assertTrue(any(fragment in x for x in e), (fragment, e))

    def test_unknown_platform(self): self.expect(self.project(platform="dreamcast")[0], "unknown platform")
    def test_bad_slug(self): self.expect(self.project(game="Bad_Name")[0], "lowercase slug")
    def test_stray_project_file(self):
        r, d = self.project(); (d / "notes.txt").write_text("x"); self.expect(r, "unexpected entry")
    def test_missing_readme(self):
        r, d = self.project(); (d / "README.md").unlink(); self.expect(r, "missing README.md")
    def test_missing_release_json(self):
        r, d = self.project(); (d / "release.json").unlink(); self.expect(r, "missing release.json")
    def test_missing_source(self):
        r, d = self.project(); shutil.rmtree(d / "source"); self.expect(r, "missing source")
    def test_mod_toml_reserved(self):
        r, d = self.project(); (d / "mod.toml").write_text("x"); self.expect(r, "reserved for schema 3")
    def test_undeclared_source_file(self):
        r, d = self.project(); (d / "source" / "extra.bin.txt").write_text("x"); self.expect(r, "not a declared package file")
    def test_provider_without_native_package(self):
        rel = copy.deepcopy(GOOD); rel["packages"] = rel["packages"][:1]; r, d = self.project(release=rel)
        (d / "source" / "synthetic-native.bps").unlink(); (d / "source" / "synthetic-native.manifest.json").unlink()
        self.expect(r, "provider.c")
    def test_non_semver(self):
        rel = copy.deepcopy(GOOD); rel["packages"][0]["version"] = "1.0"; self.expect(self.project(release=rel)[0], "not SemVer")
    def test_leading_zero_semver(self):
        rel = copy.deepcopy(GOOD); rel["packages"][0]["version"] = "01.0.0"; self.expect(self.project(release=rel)[0], "not SemVer")
    def test_unsupported_abi(self):
        rel = copy.deepcopy(GOOD); rel["packages"][1]["native_abi"] = 2; self.expect(self.project(release=rel)[0], "supported SDK ABI")
    def test_schema_3_not_accepted(self):
        rel = copy.deepcopy(GOOD); rel["packages"][0]["schema_version"] = 3; self.expect(self.project(release=rel)[0], "unsupported schema_version")
    def test_platform_mismatch(self):
        rel = copy.deepcopy(GOOD); rel["platform"] = "game-gear"; self.expect(self.project(release=rel)[0], "differs from directory")
    def test_package_file_name(self):
        rel = copy.deepcopy(GOOD); rel["packages"][0]["package_file"] = "other.segapatch"; self.expect(self.project(release=rel)[0], "package_file must be")
    def test_bad_collection_release(self):
        rel = copy.deepcopy(GOOD); rel["release"] = "1.0"; self.expect(self.project(release=rel)[0], "release must look like")
    def test_stray_test_file(self):
        r, d = self.project(); (d / "tests").mkdir(); (d / "tests/blob.bin.dat").write_bytes(b"x"); self.expect(r, "only synthetic")
    def test_invalid_json(self):
        r, d = self.project(); (d / "release.json").write_text("{"); self.expect(r, "not valid JSON")


if __name__ == "__main__":
    unittest.main()
