# Layout and versioning

`scripts/lint_layout.py` enforces this document; `scripts/check_repo.py` runs it on every pull request. It describes what exists today (schema 1 and 2). Nothing here makes schema 3 available.

## Layout of one patch project

```text
patches/<platform>/<game>/
├── README.md                  what the patch does, supported scope, limitations, compatibility declaration
├── release.json               release format 1: one entry per package (exact image digests, versions, evidence)
├── source/
│   ├── <package-id>.bps            BPS delta that produced the package (<= 4 KiB, no game content)
│   ├── <package-id>.manifest.json  the exact manifest shipped in the package
│   └── provider.c                  only when a package is schema 2 (native source); SHA-256 = native source digest
└── tests/                     optional: synthetic expectations (*.json, *.md) only
```

- `<platform>` is one of `genesis`, `master-system`, `game-gear`, `sega-cd`; `<game>` and every package id are lowercase slugs (`a-z`, `0-9`, single hyphens).
- `release.json` `platform` must equal the directory. Several packages (for example two revisions of one game) share a project directory; each lists its own exact image digests and has its own `<package-id>.*` files.
- Nothing else is allowed in a project directory or `source/`. Packages (`.segapatch`) are never committed.
- **Compatibility declaration:** the README and `release.json` state the exact source image SHA-256, region/revision, supported scope and limitations. A title or region is never an identity.
- **Expected digests:** `release.json` carries the SHA-256 of the package, manifest identity, source image, patched image, BPS and native source. CI recomputes the ones it can without any game image (BPS, source, manifest agreement and a full rebuild of every package) and fails on any difference.
- **Reserved:** `mod.toml` (schema 3 project description) is rejected until the product ships schema 3 tooling. The slot is reserved so that a future project can sit at the same path without a layout change.

## Versioning

| Thing | Rule |
|---|---|
| Package `version` | [SemVer](https://semver.org/) `MAJOR.MINOR.PATCH` (optional pre-release suffix). `PATCH`: fix without changing supported images or documented behaviour. `MINOR`: additive behaviour (new scope, new capability use) for the same images. `MAJOR`: behaviour that may change a user's saved settings or gameplay, or a different set of supported images. |
| Immutability | A published `(id, version)` is never rebuilt with different content. A fix is a new version; the digest in `release.json` is the identity. |
| Collection release | `release` is `vMAJOR.MINOR.PATCH` and names a GitHub Release grouping packages. It is unrelated to package versions. |
| `.segapatch` schema | `schema_version` 1 (BPS only) or 2 (BPS and/or native C11 source). A new schema is additive: existing packages stay valid and keep their schema. |
| SDK ABI | A schema 2 package declares `native_abi` (today `1`) and the capabilities it needs. A provider built for ABI N is not assumed to work on ABI N+1; a package for a new ABI is a new package version declaring it. The lint accepts only supported ABIs. |
| Relation | Package SemVer is independent of schema and ABI. Changing the schema or ABI of a package is at least a `MINOR` bump and is stated in the README. |
| Catalog | `catalog_format` versions `catalog/index.json`; it is generated from `release.json` and evolves additively. |

## Synthetic tests are the mandatory public validation

`scripts/synthetic_fixture.py` fabricates a tiny image (deterministic pseudo-random bytes with a Genesis-style header, unrelated to any title), derives a target, builds schema 1 and schema 2 packages with the product's pinned `segapatch.py`, applies them with the reference reader and compares every digest with `tests/synthetic/expected.json`. CI runs it with no ROM. Commercial verification is **never** run in public CI; it is recorded only as an aggregate maintainer attestation (`evidence_tier` `maintainer-attested`). See [publication restrictions](publication-restrictions.md).

## Lint fixtures

`tests/test_lint_layout.py` has a positive fixture (the repository tree and a minimal generated project) and one negative fixture per rule (unknown platform, stray file, missing README, `mod.toml`, non-SemVer version, unsupported ABI, undeclared source file, platform mismatch, stray test file).
