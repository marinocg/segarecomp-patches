#!/usr/bin/env python3
"""Validate the static catalog and per-release metadata (standard library only; docs/catalog-format.md).

  validate_catalog.py                                  schemas + semantic rules for every package.json, releases/*.json, publication.json and catalog/index.json
  validate_catalog.py --baseline-ref origin/main       also enforce immutability against the catalog at that Git ref
  validate_catalog.py --baseline FILE                  ... or against a catalog file
  validate_catalog.py --catalog FILE                   validate one catalog document (examples, a built site's input)

The JSON Schemas under catalog/schema/ are the format contract. This script implements exactly the JSON Schema keywords those
files use (`SUPPORTED`); a schema using any other keyword is itself an error, so a schema can never silently weaken a check.
"""
import argparse, json, pathlib, re, subprocess, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import release_meta

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCHEMA_DIR = ROOT / "catalog" / "schema"
SUPPORTED = {"$schema", "$id", "title", "description", "type", "enum", "const", "pattern", "minLength", "minimum", "minItems", "required",
             "properties", "additionalProperties", "items", "oneOf"}
TYPES = {"object": dict, "array": list, "string": str, "boolean": bool, "integer": int}
CURRENT = {"catalog": 2, "release": 2, "package": 1}   # the schema version each document kind is validated against today (older schemas stay served for the formats they describe)
NULLABLE = "null"   # `"type": ["integer", "null"]`: data-only packages carry explicit nulls for native-only fields (release.json format 1 has always done so)


def _type_ok(v, t):
    if t == "integer": return isinstance(v, int) and not isinstance(v, bool)
    if t in ("string", "object", "array"): return isinstance(v, TYPES[t])
    return isinstance(v, bool)


def schema_errors(value, schema, where="$"):
    """Errors of `value` against `schema` (the JSON Schema subset in SUPPORTED)."""
    errs = []
    for k in schema:
        if k not in SUPPORTED: errs.append(f"{where}: schema keyword {k!r} is not implemented by validate_catalog.py")
    if "oneOf" in schema:   # exactly one branch must accept the value; when none does, report the closest branch (fewest errors), not a wall of text
        branches = [schema_errors(value, b, where) for b in schema["oneOf"]]
        ok = [i for i, e in enumerate(branches) if not e]
        if len(ok) != 1: errs += [f"{where}: matches {len(ok)} of {len(branches)} alternatives"] + (min(branches, key=len) if not ok else [])
    t = schema.get("type")
    if t:
        ts = t if isinstance(t, list) else [t]
        if value is None and NULLABLE in ts: return errs
        if not any(_type_ok(value, x) for x in ts if x != NULLABLE): return errs + [f"{where}: expected {t}, got {type(value).__name__}"]
        t = None
    if "enum" in schema and not any(type(value) is type(x) and value == x for x in schema["enum"]): errs.append(f"{where}: {value!r} is not one of {schema['enum']}")
    if "const" in schema and value != schema["const"]: errs.append(f"{where}: {value!r} is not {schema['const']!r}")
    if isinstance(value, str):
        if "pattern" in schema and not re.search(schema["pattern"], value): errs.append(f"{where}: {value!r} does not match {schema['pattern']}")
        if len(value) < schema.get("minLength", 0): errs.append(f"{where}: shorter than {schema['minLength']}")
    if isinstance(value, int) and not isinstance(value, bool) and value < schema.get("minimum", value): errs.append(f"{where}: below {schema['minimum']}")
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0): errs.append(f"{where}: fewer than {schema['minItems']} items")
        if "items" in schema:
            for i, x in enumerate(value): errs += schema_errors(x, schema["items"], f"{where}[{i}]")
    if isinstance(value, dict):
        props = schema.get("properties", {})
        for k in schema.get("required", []):
            if k not in value: errs.append(f"{where}: missing required {k!r}")
        for k, v in value.items():
            if k in props: errs += schema_errors(v, props[k], f"{where}.{k}")
            elif schema.get("additionalProperties") is False: errs.append(f"{where}: unknown field {k!r}")
    return errs


def load_schema(name, root=ROOT, version=None):
    version = version or CURRENT[name]
    return json.loads((pathlib.Path(root) / "catalog" / "schema" / f"{name}-{version}.schema.json").read_text())


def _entries(doc): return doc.get("packages", []) if isinstance(doc, dict) else []


def _key(p): return (p.get("id"), p.get("version"))


def _semver(v):
    m = re.match(r"^(\d+)\.(\d+)\.(\d+)", str(v)); return tuple(map(int, m.groups())) if m else (0, 0, 0)


def _kind_errors(p, n):
    """Rules every entry of a package.json or the catalog obeys, whatever its release: trust/schema agreement and the fields only one kind may carry."""
    errs, schema = [], p.get("schema_version")
    native = p.get("trust") == "trusted-native-source"
    if "abi_status" in p and p.get("native_abi") != 1: errs.append(f"{n}: abi_status applies only to a native ABI 1 package")
    if schema == 3:
        if not native or not p.get("executable_code"): errs.append(f"{n}: a schema 3 package is trusted native source and executable")
        if p.get("native_abi") != 2 or not p.get("capabilities"): errs.append(f"{n}: a schema 3 package needs native_abi 2 and its capabilities")
        for k in ("source_image_sha256", "patched_image_sha256", "bps_sha256", "bps", "native_source_sha256", "revision", "region"):
            if k in p: errs.append(f"{n}: a schema 3 mod package has no {k}: it is not a BPS/ROM transformation (its images are listed in `images`)")
        if len({i.get("sha256") for i in p.get("images", [])}) != len(p.get("images", [])): errs.append(f"{n}: duplicate image digest")
        return errs
    if native != (schema == 2) or native != bool(p.get("executable_code")): errs.append(f"{n}: trust, schema_version and executable_code disagree")
    if native and not (p.get("native_abi") and p.get("native_source_sha256")): errs.append(f"{n}: a native package needs native_abi and native_source_sha256")
    if native and p.get("license") not in ("MIT", "MPL-2.0"): errs.append(f"{n}: a native package needs an established MIT or MPL-2.0 license")
    if not native and (p.get("native_abi") or p.get("native_source_sha256")): errs.append(f"{n}: a data-only package cannot carry native_abi/native_source_sha256")
    if p.get("source_image_sha256") == p.get("patched_image_sha256"): errs.append(f"{n}: patched image digest equals the source digest")
    return errs


def semantic_errors(doc, kind="catalog"):
    """Rules a JSON Schema cannot express for catalog/index.json (flat entries, each carrying its own release and source revision)."""
    errs, seen, hashes = [], set(), set()
    ids = {_key(p) for p in _entries(doc)}
    for p in _entries(doc):
        n = f"{p.get('id')}@{p.get('version')}"
        if _key(p) in seen: errs.append(f"{n}: duplicate (id, version): a published version exists exactly once")
        seen.add(_key(p))
        if p.get("package_sha256") in hashes: errs.append(f"{n}: package_sha256 shared with another entry")
        hashes.add(p.get("package_sha256"))
        a = p.get("asset", {}) if isinstance(p.get("asset"), dict) else {}
        if a.get("name") != f"{p.get('id')}.segapatch": errs.append(f"{n}: asset name must be '<id>.segapatch'")
        rev = p.get("source_revision") or {}
        want = f"{rev.get('repository')}/releases/download/{p.get('release')}/{a.get('name')}"
        if a.get("url") != want: errs.append(f"{n}: asset URL must be the version-pinned release URL {want} (never 'latest' or a branch)")
        errs += _kind_errors(p, n)
        sup = p.get("superseded_by")
        if sup:
            sid, _, sver = sup.partition("@")
            if (sid, sver) == _key(p): errs.append(f"{n}: supersedes itself")
            elif (sid, sver) not in ids: errs.append(f"{n}: superseded_by {sup} is not in this catalog")
            elif sid == p.get("id") and _semver(sver) <= _semver(p.get("version")): errs.append(f"{n}: superseded_by must name a higher version")
    by = {_key(x): x for x in _entries(doc)}
    for p in _entries(doc):   # supersession must not loop
        cur, hops = p, 0
        while cur and cur.get("superseded_by") and hops <= len(by):
            sid, _, sver = cur["superseded_by"].partition("@"); cur = by.get((sid, sver)); hops += 1
        if hops > len(by): errs.append(f"{p.get('id')}@{p.get('version')}: supersession cycle")
    return errs


def validate_catalog(doc, schema=None):
    """A catalog is validated against the schema of its own `catalog_format` (1 or 2); anything else falls to the current one and fails its enum."""
    fmt = doc.get("catalog_format") if isinstance(doc, dict) else None
    return schema_errors(doc, schema or load_schema("catalog", version=fmt if fmt in (1, 2) else None)) + (semantic_errors(doc) if isinstance(doc, dict) else [])


def validate_package(doc, schema=None):
    """One patch's package.json: its schema plus the per-entry rules. Duplicate versions across patches are release_meta.consistency_errors."""
    errs = schema_errors(doc, schema or load_schema("package"))
    if isinstance(doc, dict):
        for p in _entries(doc):
            if isinstance(p, dict):
                errs += _kind_errors(p, f"{p.get('id')}@{p.get('version')}")
                if p.get("package_file", f"{p.get('id')}.segapatch") != f"{p.get('id')}.segapatch": errs.append(f"{p.get('id')}: package_file must be '<id>.segapatch'")
        keys = [_key(p) for p in _entries(doc)]
        if len(set(keys)) != len(keys): errs.append("duplicate (id, version) in one package.json")
    return errs


def withdrawn(root=ROOT):
    """`withdrawn.json` lists `id@version` entries the maintainer deliberately removed from a published release; only those may disappear from the catalog."""
    f = pathlib.Path(root) / "withdrawn.json"
    return {w["package"] for w in json.loads(f.read_text()).get("withdrawn", [])} if f.is_file() else set()


def immutability_errors(old, new):
    """A published (id, version) never changes: every field it already had keeps its exact value, and none is removed. Permitted evolution is purely additive:
    new entries, new optional fields introduced by a compatible format revision (the v0.1.0 entries gained `source_revision` and `build` this way), and a
    `superseded_by` pointer, which once set is itself immutable."""
    errs, cur = [], {_key(p): p for p in _entries(new)}
    for o in _entries(old):
        n = f"{o.get('id')}@{o.get('version')}"
        c = cur.get(_key(o))
        if c is None and n in withdrawn(): continue
        if c is None: errs.append(f"{n}: a published release entry was removed"); continue
        for k in sorted(o):
            if k not in c: errs.append(f"{n}: published field {k!r} was removed"); continue
            if o[k] != c[k]: errs.append(f"{n}: published field {k!r} changed ({o[k]!r} -> {c[k]!r}); publish a new version instead")
    return errs


def baseline_from_ref(root, ref):
    r = subprocess.run(["git", "show", f"{ref}:catalog/index.json"], cwd=root, capture_output=True, text=True)
    if r.returncode != 0: return None
    return json.loads(r.stdout)


def validate_repository(root, errs, baseline=None):
    root = pathlib.Path(root)
    pkg_schema, rel_schema, cat_schema = load_schema("package", root), load_schema("release", root), load_schema("catalog", root)
    for pj in sorted((root / "patches").glob("*/*/*/package.json")):
        for e in validate_package(json.loads(pj.read_text()), pkg_schema): errs.append(f"{pj.relative_to(root).as_posix()}: {e}")
    for rj in sorted((root / "releases").glob("*.json")):
        for e in schema_errors(json.loads(rj.read_text()), rel_schema): errs.append(f"{rj.relative_to(root).as_posix()}: {e}")
    for e in release_meta.consistency_errors(root): errs.append(f"releases: {e}")
    cp = root / "catalog" / "index.json"
    if not cp.is_file(): errs.append("catalog/index.json missing"); return
    doc = json.loads(cp.read_text())
    for e in validate_catalog(doc, cat_schema): errs.append(f"catalog/index.json: {e}")
    if baseline is not None:
        for e in immutability_errors(baseline, doc): errs.append(f"catalog/index.json: {e}")


def main(argv=None):
    ap = argparse.ArgumentParser(); ap.add_argument("--root", default=str(ROOT)); ap.add_argument("--catalog"); ap.add_argument("--baseline"); ap.add_argument("--baseline-ref")
    a = ap.parse_args(argv); errs = []
    base = None
    if a.baseline: base = json.loads(pathlib.Path(a.baseline).read_text())
    elif a.baseline_ref:
        base = baseline_from_ref(a.root, a.baseline_ref)
        if base is None: print(f"note: no catalog at {a.baseline_ref}; immutability not checked", file=sys.stderr)
    if a.catalog:
        doc = json.loads(pathlib.Path(a.catalog).read_text()); errs += validate_catalog(doc)
        if base is not None: errs += immutability_errors(base, doc)
    else: validate_repository(a.root, errs, base)
    for e in errs: print("FAIL:", e, file=sys.stderr)
    print("ok" if not errs else f"{len(errs)} problem(s)")
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
