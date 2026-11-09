#!/usr/bin/env python3
"""Execute the code samples of a documentation page (docs/product-docs.md, "Executable samples").

  run_guide_samples.py [--page PATH] [--list]     environment: WORK, SEGAPATCH, SDK_INCLUDE, SEGARECOMP

Every fenced code block must be preceded by a marker line:
  <!-- sample: exec -->                      run with bash; must exit 0
  <!-- sample: exec-cli -->                  same, but needs the shipped segarecomp binary (SEGARECOMP)
  <!-- sample: non-executable: <reason> --> not run; a reason is mandatory
An unmarked block, an unknown marker or a marker without a block is an error. Blocks run in order in the repository root.
"""
import argparse, os, pathlib, re, subprocess, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
DEFAULT_PAGE = ROOT / "site/src/content/docs/getting-started.md"
MARK = re.compile(r"^<!--\s*sample:\s*(exec-cli|exec|non-executable)(?::\s*(.+?))?\s*-->$")
FENCE = re.compile(r"^(`{3,}|~{3,})(.*)$")


def parse(text):
    """Returns ([(line, kind, reason, code)], errors)."""
    blocks, errs = [], []; lines = text.splitlines(); i = 0; marker = None
    while i < len(lines):
        s = lines[i].strip()
        m = FENCE.match(s)
        if m:
            fence = m.group(1); start = i + 1; j = start
            while j < len(lines) and not lines[j].strip().startswith(fence): j += 1
            if j >= len(lines): errs.append(f"line {i + 1}: unterminated code block")
            if marker is None: errs.append(f"line {i + 1}: code block without a '<!-- sample: ... -->' marker")
            else:
                kind, reason = marker
                if kind == "non-executable" and not reason: errs.append(f"line {i + 1}: non-executable block needs a reason")
                else: blocks.append((i + 1, kind, reason, "\n".join(lines[start:j])))
            marker = None; i = j + 1; continue
        if s.startswith("<!--") and "sample:" in s:
            m = MARK.match(s)
            if not m: errs.append(f"line {i + 1}: unrecognised sample marker {s!r}")
            elif marker is not None: errs.append(f"line {i + 1}: marker without a code block before it")
            else: marker = (m.group(1), m.group(2))
        elif s and marker is not None and not s.startswith("<!--"):
            # prose between a marker and its block orphans the marker
            errs.append(f"line {i + 1}: sample marker is not directly followed by a code block")
            marker = None
        i += 1
    if marker is not None: errs.append("trailing sample marker without a code block")
    return blocks, errs


def run(blocks, env, cwd=ROOT):
    errs = []
    for line, kind, reason, code in blocks:
        if kind == "non-executable": print(f"skip  line {line}: non-executable ({reason})"); continue
        need = ["WORK", "SEGAPATCH", "SDK_INCLUDE"] + (["SEGARECOMP"] if kind == "exec-cli" else [])
        missing = [n for n in need if not env.get(n)]
        if missing: errs.append(f"line {line}: environment variable(s) not set: {', '.join(missing)}"); continue
        r = subprocess.run(["bash", "-euo", "pipefail", "-c", code], cwd=cwd, env=env, capture_output=True, text=True)
        print(f"{'ok   ' if r.returncode == 0 else 'FAIL '} line {line}: {kind}")
        if r.returncode: errs.append(f"line {line}: exited {r.returncode}\n{code}\n{r.stdout[-800:]}{r.stderr[-800:]}")
    return errs


def main(argv=None):
    ap = argparse.ArgumentParser(); ap.add_argument("--page", default=str(DEFAULT_PAGE)); ap.add_argument("--list", action="store_true")
    a = ap.parse_args(argv); blocks, errs = parse(pathlib.Path(a.page).read_text())
    if not errs and not a.list: errs = run(blocks, dict(os.environ))
    if a.list and not errs:
        for line, kind, reason, _ in blocks: print(f"line {line}: {kind}{': ' + reason if reason else ''}")
    for e in errs: print("FAIL:", e, file=sys.stderr)
    print("ok" if not errs else f"{len(errs)} problem(s)"); return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
