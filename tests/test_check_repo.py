"""Negative fixtures for scripts/check_repo.py (no commercial data)."""
import json, pathlib, shutil, subprocess, sys, tempfile, unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import check_repo


class Checks(unittest.TestCase):
    def copy(self):
        d = pathlib.Path(tempfile.mkdtemp()); self.addCleanup(shutil.rmtree, d)
        for p in ROOT.rglob("*"):
            if p.is_file() and ".git" not in p.parts:
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

    def test_bad_asset(self):
        d = pathlib.Path(tempfile.mkdtemp()); self.addCleanup(shutil.rmtree, d)
        (d / "sor2-widescreen.segapatch").write_bytes(b"not it"); e = []
        check_repo.check_assets(ROOT, d, None, e); self.assertTrue(any("differs" in x for x in e))


if __name__ == "__main__":
    unittest.main()
