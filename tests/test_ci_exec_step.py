"""The CI `exec` job's executable-test step must FAIL when a test fails and when a test is skipped, and succeed only when every test ran and passed (it uses `unittest | tee`, whose status needs `set -euo pipefail`).
The step's real `run:` block is extracted from .github/workflows/check.yml and executed with bash against stub test modules in a temporary directory: nothing here depends on the product CLI or any ROM."""
import pathlib, re, subprocess, tempfile, textwrap, unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
WORKFLOW = (ROOT / ".github/workflows/check.yml").read_text()


def exec_step():
    m = re.search(r"- name: Execute the injected retry code[^\n]*\n(?:        [^\n]*\n)*?        run: \|\n((?:          [^\n]*\n)+)", WORKFLOW)
    assert m, "the executable-test step is missing from the workflow"
    return textwrap.dedent(m.group(1))


class ExecStep(unittest.TestCase):
    def run_step(self, body):
        step = exec_step()
        with tempfile.TemporaryDirectory() as d:
            d = pathlib.Path(d)
            (d / "tests").mkdir()
            for m in ("test_castle_activation_exec", "test_castle_provider", "test_castle_activation", "test_castle_debug_fly"): (d / "tests" / (m + ".py")).write_text("import unittest\n" + textwrap.dedent(body))
            (d / "step.sh").write_text(step)
            # GitHub runs a `run:` block as `bash -e {0}`: reproduce exactly that shell
            r = subprocess.run(["bash", "-e", str(d / "step.sh")], cwd=d, env={"PATH": "/usr/bin:/bin:/usr/local/bin", "RUNNER_TEMP": str(d), "HOME": str(d)}, capture_output=True, text=True)
            return r.returncode, r.stdout + r.stderr

    def test_the_step_enables_pipefail(self):
        self.assertRegex(exec_step(), r"(?m)^set -euo pipefail$")

    def test_a_passing_suite_passes_the_step(self):
        code, out = self.run_step("class T(unittest.TestCase):\n    def test_a(self): pass\n    def test_b(self): pass\n")
        self.assertEqual(code, 0, out)
        self.assertIn("Ran 8 tests", out)

    def test_an_intentionally_failing_test_fails_the_step(self):
        code, out = self.run_step("class T(unittest.TestCase):\n    def test_a(self): pass\n    def test_fails(self): self.fail('intentional')\n")
        self.assertNotEqual(code, 0, "a failing test must fail the CI step (the pipeline status must not be hidden by tee)\n" + out)
        self.assertIn("FAILED", out)

    def test_an_erroring_test_fails_the_step(self):
        code, out = self.run_step("class T(unittest.TestCase):\n    def test_err(self): raise RuntimeError('boom')\n")
        self.assertNotEqual(code, 0, out)

    def test_a_skipped_test_fails_the_step(self):
        code, out = self.run_step("class T(unittest.TestCase):\n    def test_a(self): pass\n    @unittest.skip('no cli')\n    def test_s(self): pass\n")
        self.assertNotEqual(code, 0, "skipped tests are forbidden in CI\n" + out)
        self.assertIn("skipped", out)

    def test_a_suite_that_cannot_even_be_imported_fails_the_step(self):
        code, out = self.run_step("raise ImportError('broken')\n")
        self.assertNotEqual(code, 0, out)


if __name__ == "__main__":
    unittest.main()
