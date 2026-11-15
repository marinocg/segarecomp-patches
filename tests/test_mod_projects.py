"""Schema 3 / native ABI 2 project support (SEG-143-T009): synthetic positive and negative fixtures; no commercial data.

The lint cases need only Python. The cases that exercise the PRODUCT's `segarecomp mod check` / `mod pack` (agreement, deterministic rebuild, identity pinning) run when SEGARECOMP_CLI is set
(and SEGARECOMP_SDK_DIR / SEGARECOMP_CC point at the product's platforms directory and a C compiler); otherwise they are skipped with that reason, never silently passed."""
import hashlib, json, os, pathlib, shutil, subprocess, sys, tempfile, unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import build_catalog, check_repo, lint_layout

TOML = """[mod]
id = "synthetic-castle"
version = "0.1.0"
name = "Synthetic"
license = "CC0-1.0"

[target]
platform = "genesis"

[[target.revision]]
label = "fixture"
sha256 = "%s"

[[source]]
kind = "native-c11"
path = "src/provider.c"

[abi]
native = 2
""" % ("ab" * 32)
CLI, SDK, CC = os.environ.get("SEGARECOMP_CLI"), os.environ.get("SEGARECOMP_SDK_DIR"), os.environ.get("SEGARECOMP_CC", "cc")


class Lint(unittest.TestCase):
    def project(self, toml=TOML, platform="genesis", game="synthetic-castle"):
        root = pathlib.Path(tempfile.mkdtemp()); self.addCleanup(shutil.rmtree, root)
        d = root / "patches" / platform / game; (d / "src").mkdir(parents=True)
        (d / "README.md").write_text("# Synthetic\n"); (d / "mod.toml").write_text(toml); (d / "src/provider.c").write_text("/* synthetic */\n")
        return root, d

    def errs(self, root):
        e = []; lint_layout.lint(root, e); return e

    def expect(self, root, fragment):
        e = self.errs(root); self.assertTrue(any(fragment in x for x in e), (fragment, e))

    def test_positive(self): self.assertEqual(self.errs(self.project()[0]), [])
    def test_positive_repository(self): self.assertEqual(self.errs(ROOT), [])
    def test_unpublished_project_is_not_in_the_catalog(self):
        r, _ = self.project(); (r / "catalog").mkdir(); (r / "catalog/index.json").write_text(build_catalog.build(r))
        self.assertNotIn("synthetic-castle", (r / "catalog/index.json").read_text())
    def test_release_json_beside_mod_toml(self):
        r, d = self.project(); (d / "release.json").write_text("{}"); self.expect(r, "release.json cannot accompany mod.toml")
    def test_missing_mod_toml_is_a_legacy_project(self):
        r, d = self.project(); (d / "mod.toml").unlink(); self.expect(r, "missing release.json")
    def test_malformed_mod_toml(self):
        self.expect(self.project(toml="[mod\nid=")[0], "malformed")
    def test_undeclared_source_file(self):
        r, d = self.project(); (d / "src/extra.c").write_text("x"); self.expect(r, "not a declared source file")
    def test_native_source_needs_abi_2(self):
        self.expect(self.project(toml=TOML.replace("native = 2", "native = 1"))[0], "requires [abi] native = 2")
    def test_abi_without_native_source(self):
        r, d = self.project(toml=TOML.replace('kind = "native-c11"', 'kind = "luau-source"').replace("provider.c", "main.luau")); (d / "src/main.luau").write_text("x"); (d / "src/provider.c").unlink()
        self.expect(r, "no native-c11 source is")
    def test_missing_declared_source(self):
        r, d = self.project(); (d / "src/provider.c").unlink(); self.expect(r, "declared source src/provider.c is missing")
    def test_unsafe_paths(self):
        for bad in ("../outside.c", "/abs/provider.c", "src\\\\provider.c"):
            self.expect(self.project(toml=TOML.replace("src/provider.c", bad))[0], "unsafe or empty source path")
    def test_disallowed_file_type(self):
        self.expect(self.project(toml=TOML.replace("provider.c", "provider.bin"))[0], "disallowed file type")
    def test_platform_mismatch(self): self.expect(self.project(platform="master-system")[0], "differs from directory")
    def test_binary_source_kind_rejected(self):
        self.expect(self.project(toml=TOML.replace("native-c11", "bps-image"))[0], "not accepted in a repository project")
    def test_stray_entry(self):
        r, d = self.project(); (d / "notes.txt").write_text("x"); self.expect(r, "unexpected entry")
    def test_symlink_source(self):
        r, d = self.project(); (d / "src/link.c").symlink_to(d / "src/provider.c"); self.expect(r, "links are not allowed")
    def test_legacy_projects_unchanged(self):
        e = []; lint_layout.lint(ROOT, e); self.assertEqual(e, [])


@unittest.skipUnless(CLI and SDK, "set SEGARECOMP_CLI and SEGARECOMP_SDK_DIR to run the checks against the product's mod check / mod pack")
class ProductAgreement(unittest.TestCase):
    def project(self):
        root = pathlib.Path(tempfile.mkdtemp()); self.addCleanup(shutil.rmtree, root)
        d = root / "patches" / "genesis" / "synthetic-castle"; d.parent.mkdir(parents=True)
        r = subprocess.run([CLI, "mod", "init", str(d), "--platform", "genesis", "--id", "synthetic-castle", "--template", "c11-provider", "--rom-sha256", "cd" * 32], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout)
        (d / "README.md").write_text("# Synthetic\n")
        return root, d

    def run_checks(self, root):
        e = []; lint_layout.lint(root, e); check_repo.check_mod_projects(root, CLI, e, ["--cc", CC, "--sdk-dir", SDK]); return e

    def test_product_and_repository_agree(self):
        root, d = self.project(); self.assertEqual(self.run_checks(root), [])

    def test_rebuild_is_deterministic_and_identity_pins_the_source(self):
        root, d = self.project(); extra = ["--cc", CC, "--sdk-dir", SDK]
        ok, info, data = check_repo.pack_mod_project(CLI, d, root / "a.segapatch", extra); self.assertTrue(ok, info)
        ok2, info2, data2 = check_repo.pack_mod_project(CLI, d, root / "b.segapatch", extra)
        self.assertEqual((data, info["package_identity"]), (data2, info2["package_identity"]))
        (d / "tests").mkdir(); (d / "tests/package.json").write_text(json.dumps({"package_identity": info["package_identity"], "package_sha256": hashlib.sha256(data).hexdigest()}))
        self.assertEqual(self.run_checks(root), [])
        src = d / "src/provider.c"; src.write_text(src.read_text() + "\n/* one more comment byte */\n")   # a modified source byte changes the package identity
        e = self.run_checks(root); self.assertTrue(any("package identity differs" in x or "SHA-256 differs" in x for x in e), e)

    def test_product_refuses_what_the_lint_accepts_structurally(self):
        root, d = self.project(); (d / "src/provider.c").write_text("this is not C;\n")
        e = self.run_checks(root); self.assertTrue(any("product build failed" in x or "mod check refused" in x for x in e), e)


if __name__ == "__main__":
    unittest.main()
