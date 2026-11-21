#!/usr/bin/env python3
"""A deterministic stand-in for the product's `segarecomp mod ...` commands, used ONLY by the synthetic fixtures (tests/synth_repo.py).

It reproduces the observable contract the repository relies on (JSON on stdout, `ok`, `package_identity`, a deterministic archive, `pack` and `build`
producing the same bytes) so the lifecycle and scalability tests do not need a product build. Every invocation is appended to $FAKE_PRODUCT_LOG, which is how
the tests count exactly which packages were built. The real product CLI is exercised by tests/test_mod_projects.py and tests/test_publication.py when
SEGARECOMP_CLI is set.
"""
import hashlib, json, os, pathlib, sys, tomllib, zipfile

args = sys.argv[1:]
if os.environ.get("FAKE_PRODUCT_LOG"):
    with open(os.environ["FAKE_PRODUCT_LOG"], "a") as f: f.write(" ".join(args) + "\n")


def say(doc, rc=0): print(json.dumps(doc)); sys.exit(rc)


def facts(d):
    m = tomllib.loads((pathlib.Path(d) / "mod.toml").read_text())
    return {"ok": True, "id": m["mod"]["id"], "version": m["mod"]["version"], "name": m["mod"]["name"], "platform": m["target"]["platform"],
            "source_identity_kind": "cartridge-image", "revisions": [{"label": r["label"], "sha256": r["sha256"]} for r in m["target"]["revision"]],
            "trust_class": "native", "capabilities": m["capabilities"]["required"], "abi_native": m["abi"]["native"]}


def pack(d, out):
    d = pathlib.Path(d); f = facts(d)
    if "BROKEN" in (d / "src/provider.c").read_text(): say({"ok": False, "error": "synthetic build failure"}, 1)
    files = [("manifest.json", json.dumps(f, sort_keys=True).encode())] + [(p.relative_to(d).as_posix(), p.read_bytes()) for p in sorted((d / "src").rglob("*")) if p.is_file()]
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for name, data in files:
            i = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0)); i.compress_type = zipfile.ZIP_DEFLATED; z.writestr(i, data)
    ident = hashlib.sha256(files[0][1]).hexdigest()
    say({**f, "package_identity": ident, "package_bytes": pathlib.Path(out).stat().st_size, "packed": True})


if args[:2] == ["patch", "inspect"]:   # a schema 1/2 archive (the fixture's manifests follow tools/segapatch.py's shape)
    with zipfile.ZipFile(args[-1]) as z: raw = z.read("manifest.json")
    m = json.loads(raw); pl = m.get("payloads", {})
    say({"ok": True, "id": m["id"], "version": m["version"], "schema_version": m.get("schema_version", 1), "package_identity": hashlib.sha256(raw).hexdigest(), "source_sha256": m["source_sha256"],
         "target_sha256": pl["rom"]["target_sha256"], "payload_sha256": pl["rom"]["sha256"], "executable_code": False, "native_source_sha256": ""})
if args[:1] != ["mod"] or len(args) < 3: say({"ok": False, "error": "unsupported"}, 2)
cmd = args[1]
if cmd == "check": say(facts(args[2]))
elif cmd in ("pack", "build"): pack(args[2], args[args.index("--out") + 1])
elif cmd == "inspect":
    with zipfile.ZipFile(args[-1]) as z: raw = z.read("manifest.json")
    say({**json.loads(raw), "package_identity": hashlib.sha256(raw).hexdigest()})
else: say({"ok": False, "error": f"unsupported {cmd}"}, 2)
