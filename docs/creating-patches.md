# Creating a patch

Authoring tools and the SDK live in the [segarecomp product repository](https://github.com/marinocg/segarecomp); this repository publishes finished, reviewed patches. Here is the whole path from an idea to a published download. The detailed commands for releasing are in [releases.md](releases.md); this page answers the everyday questions.

**1. Where do I add a new patch?** In `patches/<platform>/<game>/<patch>/`: always three levels. A game can hold any number of independent patches. A new game is just a new directory (`patches/genesis/my-game/widescreen/`); a new platform follows the same hierarchy ([layout](layout-and-versioning.md)).

```text
segarecomp mod init patches/genesis/my-game/widescreen --platform genesis --id my-game-widescreen --template c11-provider --rom-sha256 <image sha256>
```

Read [`mod-projects.md`](https://github.com/marinocg/segarecomp/blob/main/docs/product/mod-projects.md) and [`native-sdk-abi-2.md`](https://github.com/marinocg/segarecomp/blob/main/docs/architecture/native-sdk-abi-2.md). A new patch with native code **must** be a schema 3 mod (`mod.toml`) written against native ABI 2: native ABI 1 is deprecated and `check_repo.py` rejects new ABI 1 packages ([retention policy](abi1-retention.md); [migration guide](https://github.com/marinocg/segarecomp/blob/main/docs/product/native-abi-migration.md)). The existing schema 1/2 packages keep `package.json` and `source/`.

**2. How do I build and test it?** With the product's tools, never a second builder in this repository:

```text
segarecomp mod check patches/genesis/my-game/widescreen                        # manifest, sources, capabilities
segarecomp mod build patches/genesis/my-game/widescreen --out x.segapatch --cc cc --sdk-dir <product>/platforms   # + the host-compiled native code
python3 scripts/check_repo.py --segarecomp <CLI> --cc cc --sdk-dir <product>/platforms --changed-from origin/main  # only the projects you changed
```

`mod pack` (no compiler) and `mod build` (compiler gate) produce the same archive bytes; `pack` is what is distributed, `build` is the stricter check. Tests are focused and synthetic: fabricated work RAM and a synthetic image, never a ROM or a trace. Pin the expected package bytes in `tests/package.json` if you want a changed source byte to fail.

**3. How do I keep a patch internal?** Do nothing, or list it as `internal` in [`publication.json`](../publication.json). The default for any patch is `internal`: its source stays public and testable but it can never be cataloged, put in `SHA256SUMS` or attached to a release; selecting it fails. Castle's `debug-fly` and `input-recorder` are examples.

**4. How do I request approval for publication?** Record the package version (`prepare_release.py pin`, see [releases.md](releases.md)), then open a pull request that sets the patch to `candidate` while it is being reviewed and to `eligible` (with its `review` text) only when a maintainer approves it, and adds its per-file records (`python3 scripts/check_source_review.py --write`, [source-review.md](source-review.md)). Eligibility is an explicit, reviewable diff of `publication.json`; it never publishes anything by itself, and a technical scan is not legal clearance.

**5. How do I select patches for a release?** `python3 scripts/prepare_release.py begin --tag v0.2.0 --package <id>@<version> [--package ...]`. The release is exactly that list: other eligible patches and every earlier release are untouched.

**6 to 8. Draft, publish, catalog.** Run the **release** workflow with the tag (a draft with the selected assets and `SHA256SUMS`), publish the draft on GitHub, record it with `prepare_release.py publish` and regenerate the catalog (`build_catalog.py`); the site lists the package after the Pages deployment. Never edit `catalog/index.json`.

**9. How do I publish an updated version?** Bump `version` in `mod.toml`, `pin` again, select the new `id@version` in a new release, then `prepare_release.py supersede`. A published version is never replaced.

**10. How do I verify an old release?** `python3 scripts/rebuild_release.py --release v0.1.0 --work /tmp/w` rebuilds that one release from its pinned commit; the `audit` workflow does it for all of them on demand. Pull requests and releases never rebuild history.

## Worked example: Castle of Illusion

`patches/genesis/castle-of-illusion/` holds six independent patches. `widescreen-practice` (`castle-of-illusion-widescreen-practice@0.1.0`, schema 3 / ABI 2) is a **candidate**: its package version is recorded in its `package.json` (identity `b26a2134...`, SHA-256 `312ffd0b...`), but it is not `eligible` yet, so no release can select it. The three `activation-*` variants are candidates with no recorded package yet. `debug-fly` and `input-recorder` are internal. To release only the first one, a maintainer reviews it, changes its entry in `publication.json` to `eligible` with a `review`, records its source review, runs `prepare_release.py begin --tag v0.2.0 --package castle-of-illusion-widescreen-practice@0.1.0`, and follows steps 6 to 8. A dry run of exactly that selection (tests/test_publication.py, with the real product CLI) produces one `.segapatch` and one `SHA256SUMS` line.

## Rules

* No new native ABI 1 package is accepted.
* Commit the BPS delta of a schema 1/2 package next to its manifest as `source/<package-id>.bps`. Only patches that work against their exact image qualify. See [CONTRIBUTING.md](../CONTRIBUTING.md).
* Native code is trusted, unsandboxed code: say so, and keep the license the package declares.
* The package formats are schema 1 (BPS only), 2 (BPS plus trusted C11) and 3 (a source-based mod); later schemas are expected to be additive.
