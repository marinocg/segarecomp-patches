"""Positive and negative fixtures for scripts/lint_layout.py: the platform/game/patch layout (no commercial data)."""
import copy, json, pathlib, shutil, sys, tempfile, unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import lint_layout

GOOD = {"package_format": 1, "platform": "genesis", "source_identity_kind": "cartridge-image-sha256", "bios_requirement": "none", "game": "Synthetic",
        "packages": [{"id": "synthetic-demo", "version": "1.0.0", "schema_version": 1, "package_file": "synthetic-demo.segapatch"},
                     {"id": "synthetic-native", "version": "1.2.0-rc.1", "schema_version": 2, "native_abi": 1,
                      "capabilities": ["frame.vdp"], "package_file": "synthetic-native.segapatch"}]}
MOD = '[mod]\nid = "%s"\nversion = "0.1.0"\nname = "Synthetic"\nlicense = "MIT"\n\n[target]\nplatform = "genesis"\n\n[[source]]\nkind = "native-c11"\npath = "src/provider.c"\n\n[abi]\nnative = 2\n'


class Layout(unittest.TestCase):
    def tree(self):
        root = pathlib.Path(tempfile.mkdtemp()); self.addCleanup(shutil.rmtree, root); (root / "patches").mkdir(); return root

    def legacy(self, root, platform="genesis", game="synthetic", patch="demo", release=None):
        """A generated, fabricated schema 1/2 patch; the fixtures are built, never copied from a game."""
        d = root / "patches" / platform / game / patch; (d / "source").mkdir(parents=True)
        (d / "README.md").write_text("# Synthetic\n"); (d / "package.json").write_text(json.dumps(copy.deepcopy(release or GOOD)))
        for n in ("synthetic-demo.bps", "synthetic-demo.manifest.json", "synthetic-native.bps", "synthetic-native.manifest.json", "provider.c"):
            (d / "source" / n).write_text("x")
        return d

    def mod(self, root, platform="genesis", game="synthetic", patch="mod-a", mid=None):
        d = root / "patches" / platform / game / patch; (d / "src").mkdir(parents=True)
        (d / "README.md").write_text("# Mod\n"); (d / "mod.toml").write_text(MOD % (mid or f"{game}-{patch}")); (d / "src/provider.c").write_text("/* x */\n")
        return d

    def project(self, **kw):
        root = self.tree(); return root, self.legacy(root, **kw)

    def errs(self, root):
        e = []; lint_layout.lint(root, e); return e

    def expect(self, root, fragment):
        e = self.errs(root); self.assertTrue(any(fragment in x for x in e), (fragment, e))

    # --- positive ---------------------------------------------------------------------------------------------------------------
    def test_positive_generated_project(self): self.assertEqual(self.errs(self.project()[0]), [])
    def test_positive_repository(self): self.assertEqual(self.errs(ROOT), [])

    def test_many_independent_patches_in_one_game_and_many_games(self):
        root = self.tree()
        self.mod(root, game="game-one", patch="alpha"); self.mod(root, game="game-one", patch="beta"); self.mod(root, game="game-one", patch="gamma")
        self.mod(root, game="game-two", patch="alpha")
        self.assertEqual(self.errs(root), [])

    def test_future_platform_uses_the_same_hierarchy(self):
        root = self.tree(); d = self.mod(root, platform="master-system", game="some-game", patch="widescreen", mid="sms-widescreen")
        (d / "mod.toml").write_text((d / "mod.toml").read_text().replace('platform = "genesis"', 'platform = "master-system"')); self.assertEqual(self.errs(root), [])

    # --- negative: structure ----------------------------------------------------------------------------------------------------
    def test_unknown_platform(self): self.expect(self.project(platform="dreamcast")[0], "unknown platform")
    def test_bad_game_slug(self): self.expect(self.project(game="Bad_Name")[0], "lowercase slug")
    def test_bad_patch_slug(self): self.expect(self.project(patch="Bad_Name")[0], "lowercase slug")
    def test_old_two_level_layout_is_rejected(self):
        root = self.tree(); g = root / "patches/genesis/old-style"; (g / "source").mkdir(parents=True); (g / "README.md").write_text("x"); (g / "package.json").write_text("{}")
        self.expect(root, "platform/game/patch")
    def test_old_two_level_mod_project_is_rejected(self):
        root = self.tree(); g = root / "patches/genesis/old-style"; g.mkdir(parents=True); (g / "mod.toml").write_text(MOD % "old-style"); self.expect(root, "platform/game/patch")
    def test_file_in_a_game_directory(self):
        root, d = self.project(); (d.parent / "notes.txt").write_text("x"); self.expect(root, "platform/game/patch")
    def test_file_beside_the_platform(self):
        root, d = self.project(); (root / "patches/genesis/stray.txt").write_text("x"); self.expect(root, "a game directory holds patch directories only")
    def test_nested_project_is_rejected(self):
        root = self.tree(); d = self.mod(root); inner = d / "src" / "deeper"; inner.mkdir(); (inner / "mod.toml").write_text("x")
        self.expect(root, "not a declared source file")
    def test_nested_legacy_project_is_rejected(self):
        root, d = self.project(); (d / "source" / "x").mkdir(); (d / "source" / "x" / "package.json").write_text("{}"); self.expect(root, "not a declared package file")
    def test_patch_dir_that_is_neither_legacy_nor_mod(self):
        root = self.tree(); (root / "patches/genesis/g/p").mkdir(parents=True); self.expect(root, "missing README.md")
    def test_release_json_is_retired(self):
        root, d = self.project(); (d / "release.json").write_text("{}"); self.expect(root, "release.json no longer exists")

    def test_duplicate_package_identity_across_patches(self):
        root = self.tree(); self.mod(root, game="g1", patch="a", mid="same-id"); self.mod(root, game="g2", patch="b", mid="same-id"); self.expect(root, "declared by both")
    def test_duplicate_identity_between_a_mod_and_a_legacy_package(self):
        root = self.tree(); self.legacy(root, patch="demo"); self.mod(root, game="synthetic", patch="other", mid="synthetic-demo"); self.expect(root, "declared by both")

    # --- negative: package.json -------------------------------------------------------------------------------------------------
    def test_stray_project_file(self):
        r, d = self.project(); (d / "notes.txt").write_text("x"); self.expect(r, "unexpected entry")
    def test_missing_readme(self):
        r, d = self.project(); (d / "README.md").unlink(); self.expect(r, "missing README.md")
    def test_missing_package_json(self):
        r, d = self.project(); (d / "package.json").unlink(); self.expect(r, "missing package.json")
    def test_missing_source(self):
        r, d = self.project(); shutil.rmtree(d / "source"); self.expect(r, "missing source")
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
    def test_schema_3_needs_a_mod_project(self):
        rel = copy.deepcopy(GOOD); rel["packages"][0]["schema_version"] = 3; self.expect(self.project(release=rel)[0], "schema 3 needs mod.toml")
    def test_platform_mismatch(self):
        rel = copy.deepcopy(GOOD); rel["platform"] = "game-gear"; self.expect(self.project(release=rel)[0], "differs from directory")
    def test_package_file_name(self):
        rel = copy.deepcopy(GOOD); rel["packages"][0]["package_file"] = "other.segapatch"; self.expect(self.project(release=rel)[0], "package_file must be")
    def test_stray_test_file(self):
        r, d = self.project(); (d / "tests").mkdir(); (d / "tests/blob.bin.dat").write_bytes(b"x"); self.expect(r, "only synthetic")
    def test_invalid_json(self):
        r, d = self.project(); (d / "package.json").write_text("{"); self.expect(r, "not valid JSON")
    def test_mod_package_json_must_name_the_mod(self):
        root = self.tree(); d = self.mod(root); (d / "package.json").write_text(json.dumps({"packages": [{"id": "someone-else", "schema_version": 3}]})); self.expect(root, "differs from mod.toml id")


if __name__ == "__main__":
    unittest.main()
