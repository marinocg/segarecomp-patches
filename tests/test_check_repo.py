"""Negative fixtures for scripts/check_repo.py (no commercial data)."""
import json, pathlib, shutil, subprocess, sys, tempfile, unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import check_repo


class Checks(unittest.TestCase):
    def copy(self):
        d = pathlib.Path(tempfile.mkdtemp()); self.addCleanup(shutil.rmtree, d)
        for p in ROOT.rglob("*"):
            if p.is_file() and not ({".git", "node_modules", "dist", ".astro", "__pycache__"} & set(p.parts)):
                t = d / p.relative_to(ROOT); t.parent.mkdir(parents=True, exist_ok=True); shutil.copy(p, t)
        return d

    def errs(self, d):
        e = []; check_repo.check(d, e); return e

    def test_clean(self): self.assertEqual(self.errs(self.copy()), [])

    def test_forbidden_rom_extension(self):
        d = self.copy(); (d / "patches/genesis/sonic-1/game.bin").write_bytes(b"x")
        self.assertTrue(any("forbidden" in e for e in self.errs(d)))

    def test_bps_digest_mismatch(self):
        d = self.copy(); (d / "patches/genesis/streets-of-rage-2/source/sor2-widescreen.bps").write_bytes(b"x")
        self.assertTrue(any("BPS digest" in e for e in self.errs(d)))

    def test_stray_bps(self):
        d = self.copy(); (d / "docs/other.bps").write_bytes(b"x")
        self.assertTrue(any("forbidden" in e for e in self.errs(d)))

    def test_source_digest_mismatch(self):
        d = self.copy(); (d / "patches/genesis/sonic-1/source/provider.c").write_text("tampered")
        self.assertTrue(any("digest" in e for e in self.errs(d)))

    def test_placeholder_hash_and_http(self):
        d = self.copy(); f = d / "patches/genesis/sonic-1/release.json"; j = json.loads(f.read_text())
        j["packages"][0]["package_sha256"] = "0" * 10; j["packages"][0]["asset"]["url"] = "http://x"
        f.write_text(json.dumps(j))
        e = self.errs(d); self.assertTrue(any("SHA-256" in x for x in e) and any("HTTPS" in x for x in e))

    def test_private_marker(self):
        d = self.copy(); (d / "docs/x.md").write_text("see private-corpus/")
        self.assertTrue(any("marker" in e for e in self.errs(d)))

    def test_secret_scan(self):
        # Credential-shaped strings are assembled at run time so this file itself never contains one.
        cases = {"private key block": "-----BEGIN " + "RSA PRIVATE KEY-----", "GitHub token": "gh" + "p_" + "a1B2" * 9,
                 "AWS access key id": "AKIA" + "ABCDEFGHIJKLMNOP", "npm token": "npm_" + "x" * 36,
                 "credential assignment": 'api_key = "' + "k" * 20 + '"'}
        for what, text in cases.items():
            d = self.copy(); (d / "docs/leak.md").write_text("notes\n" + text + "\n")
            self.assertTrue(any("possible secret" in e and what in e for e in self.errs(d)), what)

    def test_secret_scan_ignores_placeholders(self):
        d = self.copy(); (d / "docs/ok.md").write_text('token = "${{ secrets.TOKEN }}"\npassword = "<your-password>"\nsecret: "short"\n')
        self.assertEqual(self.errs(d), [])

    def test_forbidden_binary_and_large_file(self):
        d = self.copy(); (d / "docs/tool.exe").write_bytes(b"MZ"); (d / "docs/big.json").write_text("x" * (512 * 1024 + 1))
        e = self.errs(d); self.assertTrue(any("tool.exe" in x for x in e) and any("big.json" in x for x in e))

    def test_governance_files_required(self):
        for rel in ("CODE_OF_CONDUCT.md", ".github/CODEOWNERS", "docs/repository-settings.md", "docs/publication-restrictions.md"):
            d = self.copy(); (d / rel).unlink()
            self.assertTrue(any(f"missing {rel}" in e for e in self.errs(d)), rel)

    def test_required_checks_documented(self):
        d = self.copy(); f = d / "docs/repository-settings.md"; f.write_text(f.read_text().replace("site / build", "site"))
        self.assertTrue(any("required check" in e for e in self.errs(d)))

    def test_layout_violation_fails_repo_check(self):
        d = self.copy(); (d / "patches/genesis/sonic-1/mod.toml").write_text("x = 1\n")
        self.assertTrue(any("mod.toml" in e for e in self.errs(d)))

    def test_sums_required(self):
        d = pathlib.Path(tempfile.mkdtemp()); self.addCleanup(shutil.rmtree, d); e = []
        check_repo.check_assets(ROOT, d, None, e); self.assertTrue(any("SHA256SUMS is missing" in x for x in e))

    def test_bad_asset(self):
        d = pathlib.Path(tempfile.mkdtemp()); self.addCleanup(shutil.rmtree, d)
        (d / "sor2-widescreen.segapatch").write_bytes(b"not it"); e = []
        check_repo.check_assets(ROOT, d, None, e); self.assertTrue(any("differs" in x for x in e))


if __name__ == "__main__":
    unittest.main()
