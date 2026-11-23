# Layout and versioning

`scripts/lint_layout.py` enforces this document; `scripts/check_repo.py` runs it on every pull request.

## The layout: platform / game / patch

```text
patches/
└── <platform>/                    genesis, master-system, game-gear, sega-cd
    └── <game>/                    a lowercase slug; holds patch directories only
        └── <patch>/               one independently buildable, independently releasable project
```

A game directory contains **only** patch directories, and a patch directory is exactly one of:

```text
schema 3 / native ABI 2 (source-based mod)       schema 1 / 2 (BPS delta, optional native C11 source)
├── README.md                                    ├── README.md
├── mod.toml                  authoritative      ├── package.json      package facts (digests, versions, evidence)
├── src/ scripts/ edits/      declared sources   ├── source/
├── bps/                      optional: one BPS delta (bps-image)
├── tests/                    optional           │   ├── <package-id>.bps            BPS delta that produced the package (<= 4 KiB, no game content)
└── package.json              once a version     │   ├── <package-id>.manifest.json  the exact manifest shipped in the package
                              was recorded       │   └── provider.c                  only for schema 2; SHA-256 = native source digest
                              (prepare_release   └── tests/            optional: synthetic expectations (*.json, *.md) only
                              .py pin)
```

Only the directories a patch needs exist. Example:

```text
patches/genesis/
├── castle-of-illusion/
│   ├── widescreen-practice/     (candidate)   activation-16x9/ activation-21x9/ activation-32x9/  (candidates)
│   └── debug-fly/ input-recorder/              (internal: public source, never released)
├── sonic-1/native-widescreen/
├── sonic-2/native-widescreen/   two packages (World REV00, JUE REV01) that share one provider.c
├── sonic-3-and-knuckles/native-widescreen/
└── streets-of-rage-2/widescreen/
```

Rules, all checked by the lint:

* `<platform>` is one of the known platforms; `<game>`, `<patch>` and every package id are lowercase slugs (`a-z`, `0-9`, single hyphens). A patch directory name need not equal a package id; package ids are unique across the whole repository (a duplicate identity is rejected, as is one declared in two patches).
* The old two-level layout (project files directly in a game directory), a project nested inside a patch, a stray file in a platform or game directory, and the retired `release.json` are rejected. A patch directory with neither `mod.toml` nor `package.json` is not a project.
* One patch may hold several packages when they are inseparable, for example two image revisions built from one `provider.c` (Sonic 2); each has its own `<package-id>.*` files and entry. Separate games or separate behaviours are separate patches.
* `package.json` `platform` must equal the directory. Packages (`.segapatch`) are never committed.
* **Compatibility declaration:** the README and the package facts state the exact image SHA-256 digests, supported scope and limitations. A title or region is never an identity.
* **Expected digests:** a schema 1/2 `package.json` carries the SHA-256 of the package, manifest identity, source image, patched image, BPS and native source; CI recomputes the ones it can without a game image. A schema 3 entry carries the package digest, size and identity produced by the product tool and the images and capabilities declared by `mod.toml`; CI checks that they agree with `mod.toml` and, with the product CLI, that `mod pack` still produces exactly those bytes.
* **Schema 3 project:** `mod.toml` plus the files it declares under `src/`, `scripts/`, `edits/` or `bps/` (text only: `.c`/`.h`, `.luau`, `.edits`, `.asm`, plus the one `bps-image` delta: a `.bps` file of at most 4 KiB under `bps/` that carries a `target_sha256` in `mod.toml`; it is a binary patch against an original image, never a game image, and is reviewed like a schema 1/2 delta). `lint_layout.py` checks layout, declared files, safe paths, links, text-only sources and the schema/ABI combination (`native-c11` requires `[abi] native = 2`; a `bps-image` source is a `BPS1` delta of at most 4 KiB with a `target_sha256`); the product's `segarecomp mod check/pack/build` is the only manifest and package authority. An optional `tests/package.json` (`package_identity`, `package_sha256`) pins the expected rebuild so a changed source byte fails; when a recorded version exists both must agree.
* **Publication is separate from layout.** Where a patch lives says nothing about whether it may be released: that is `publication.json` (default `internal`) and `releases/<tag>.json` ([releases.md](releases.md)).

## Historical layout (v0.1.0)

Releases before this layout kept their sources in `patches/<platform>/<game>/source/` with a per-game `release.json`. Those files were moved into `patches/<platform>/<game>/<patch>/` with **identical bytes**, so no package, digest, manifest, id or version changed. `releases/v0.1.0.json` records `"source_layout": "game-dir"` and its pinned `source_revision.commit`, so verification and rebuilds read the files from Git at that commit under the layout it had (`patches/genesis/<game>/source/...`), never from today's working tree. A catalog entry's `game_path` keeps its historical meaning (the game directory); entries from `patch-dir` releases add `source_path` (the patch directory), see [catalog-format.md](catalog-format.md).

## Versioning

| Thing | Rule |
|---|---|
| Package `version` | [SemVer](https://semver.org/) `MAJOR.MINOR.PATCH` (optional pre-release suffix). `PATCH`: fix without changing supported images or documented behaviour. `MINOR`: additive behaviour (new scope, new capability use) for the same images. `MAJOR`: behaviour that may change a user's saved settings or gameplay, or a different set of supported images. |
| Immutability | A published `(id, version)` is never rebuilt with different content. A fix is a new version; the recorded digest is the identity. |
| Collection release | `release` is `vMAJOR.MINOR.PATCH` and names a GitHub Release grouping packages. It is unrelated to package versions. |
| `.segapatch` schema | `schema_version` 1 (BPS only), 2 (BPS and/or native C11 source) or 3 (a source-based mod: no BPS delta, no patched image). A new schema is additive: existing packages stay valid and keep their schema. |
| SDK ABI | A schema 2 package declares `native_abi` `1`, a schema 3 package `native_abi` `2`, and the capabilities it needs. A provider built for ABI N is not assumed to work on ABI N+1; a package for a new ABI is a new package version declaring it. The lint accepts only supported ABIs. |
| Relation | Package SemVer is independent of schema and ABI. Changing the schema or ABI of a package is at least a `MINOR` bump and is stated in the README. |
| Catalog | `catalog_format` versions `catalog/index.json`, `release_format` versions `releases/<tag>.json` and `package_format` versions a patch's `package.json`; each has a JSON Schema under `catalog/schema/`. Policy, immutability and supersession: [catalog-format.md](catalog-format.md). |

## Synthetic tests are the mandatory public validation

`scripts/synthetic_fixture.py` fabricates a tiny image (deterministic pseudo-random bytes with a Genesis-style header, unrelated to any title), derives a target, builds schema 1 and schema 2 packages with the product's pinned `segapatch.py`, applies them with the reference reader and compares every digest with `tests/synthetic/expected.json`. CI runs it with no ROM. Commercial verification is **never** run in public CI; it is recorded only as an aggregate maintainer attestation (`evidence_tier` `maintainer-attested`). See [publication restrictions](publication-restrictions.md).

## Lint fixtures

`tests/test_lint_layout.py` has positive fixtures (the repository tree, several independent patches under one game, several games, a future platform) and one negative fixture per rule (unknown platform, old two-level layout, stray file, nested project, duplicate package identity, missing README, retired `release.json`, non-SemVer version, unsupported ABI, undeclared source file, platform mismatch, stray test file).
