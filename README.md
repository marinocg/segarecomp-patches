# segarecomp Patches

Game-specific widescreen patches for [segarecomp](https://github.com/marinocg/segarecomp), the experimental static recompiler and launcher for Sega console software.

This repository holds the reviewed **source, metadata and documentation** of each patch. The installable `.segapatch` files are published as [GitHub Release](https://github.com/marinocg/segarecomp-patches/releases) assets. **No game images are included, and you need your own legally obtained copy of each game.**

## What is segarecomp?

segarecomp translates a supported Sega game ahead of time into portable C11 and compiles it, together with a native implementation of the console hardware, into a program for your computer. An **emulator** interprets (or JIT-compiles) the original CPU instructions while the game runs. A **static recompiler** does that translation once, before running, so the generated program contains no interpreter and no runtime opcode decoder. This is an experimental project and not a general replacement for an emulator.

## What is a `.segapatch`?

A `.segapatch` is a small ZIP archive that describes one optional modification of one exact game image. segarecomp verifies it against your image (full SHA-256, never a title or region label) and builds a separate **Patched** variant beside the untouched **Vanilla** one. Two kinds exist today:

| Kind | Contents | Trust |
|---|---|---|
| **Schema 1: BPS only** | one verified BPS delta | data only: segarecomp never executes anything from it |
| **Schema 2: BPS + native C11 source** | optional BPS and one `provider.c` written against segarecomp's public native patch SDK | **trusted executable code**: compiled into the Patched program and **not sandboxed**. SHA-256 digests prove the bytes are unchanged, not who wrote them |

The format is documented in the [product's patch package guide](https://github.com/marinocg/segarecomp/blob/main/docs/product/patch-packages.md) and the [native patch SDK guide](https://github.com/marinocg/segarecomp/blob/main/docs/product/native-patch-sdk.md).

## Generic widescreen versus game-specific patches

segarecomp can widen any supported Genesis game by itself (the pause menu's *Widescreen Mode*, *Widescreen Width* and *Side Presentation* options). That generic presentation can only show what the game already draws; for scenery it repeats or wraps what is on screen. A **game-specific patch** adds knowledge the engine does not have:

* **Native providers** (Sonic 1, Sonic 2, Sonic 3 & Knuckles) rebuild scenery beyond the picture from the game's own level data and redraw the original HUD at the edge of the wide picture. The engine contains no game-specific code; it lives in the package.
* **Actor-coverage changes** (Sonic 1, Sonic 2, Sonic 3 & Knuckles, Streets of Rage 2) make the game submit actors beside the original picture. Each page says whether gameplay can differ.

Patches are distributed separately so the core stays free of game-specific code and patch authors can release independently of the engine.

## Included patches (v0.1.0, draft)

| Game | Screenshot | Capabilities | Compatibility scope | Package |
|---|---|---|---|---|
| [**Sonic the Hedgehog**](patches/genesis/sonic-1/README.md) | <img src="https://raw.githubusercontent.com/marinocg/segarecomp/main/docs/assets/showcase/sonic-1-green-hill-patched-16x9.png" width="260" alt="Sonic the Hedgehog, Green Hill Zone 1, in 16:9 with reconstructed scenery on both sides and the HUD moved to the left edge"> | Native scenery, relocated HUD, extended actor initialisation (objects do not pop in at the picture edge). Gameplay changes slightly | Exact REV00 image | sonic1-native-widescreen |
| [**Sonic the Hedgehog 2**](patches/genesis/sonic-2/README.md) | <img src="https://raw.githubusercontent.com/marinocg/segarecomp/main/docs/assets/showcase/sonic-2-emerald-hill-patched-16x9.png" width="260" alt="Sonic the Hedgehog 2, Emerald Hill Zone 1, in 16:9 with extended scenery, relocated HUD and an enemy in the right margin"> | Native scenery, relocated HUD, widened actors. Gameplay changes slightly | Exact World REV00 and JUE REV01 images | REV00, REV01 |
| [**Sonic 3 & Knuckles**](patches/genesis/sonic-3-and-knuckles/README.md) | <img src="https://raw.githubusercontent.com/marinocg/segarecomp/main/docs/assets/showcase/sonic-3-knuckles-angel-island-patched-16x9.png" width="260" alt="Sonic 3 and Knuckles, Angel Island Zone 1, in 16:9 with extended jungle scenery and the relocated HUD"> | Native foreground (background where derivable, wrapped VDP plane elsewhere), relocated HUD, widened actors. Gameplay changes slightly | Playable widescreen (maintainer-tested); exact 4 MiB lock-on composite | sonic3k-native-widescreen |
| [**Streets of Rage 2**](patches/genesis/streets-of-rage-2/README.md) | <img src="https://raw.githubusercontent.com/marinocg/segarecomp/main/docs/assets/showcase/streets-of-rage-2-stage-1-patched-16x9.png" width="260" alt="Streets of Rage 2, stage 1, in 16:9 with extra enemies drawn beside the native picture"> | BPS only: extra enemies in the margins. No native scenery, no HUD relocation | Exact USA image | sor2-widescreen |

Screenshots are real captures of generated-native gameplay, linked from [segarecomp's showcase](https://github.com/marinocg/segarecomp/tree/main/docs/assets/showcase) rather than copied here. Packages are attached to the [v0.1.0 release](https://github.com/marinocg/segarecomp-patches/releases) once it is published; each game page lists the exact file names and SHA-256 digests. The supported target is **16:9** (Widescreen Width 100) and the suggested starting presentation is **Enhanced Widescreen · 16:9 · Raw Extension**; it is a starting point, not a forced setting, and your own choice is kept per installed variant. Other widths and aspect ratios are not validated by these packages. Nothing here promises universal widescreen support, complete coverage of every game, or unchanged gameplay.

## Install in short

1. Download the `.segapatch` for your exact game image and check it against `SHA256SUMS`.
2. In the segarecomp launcher open the game's **Details** page, **Patches / Variants**, **Install patch...**.
3. For a native (schema 2) package, read the approval sheet and approve only a package you trust.
4. **Build patched version**, then **Play Patched**.

Details, command-line verification and troubleshooting: [docs/installation.md](docs/installation.md). Compatibility: [docs/compatibility.md](docs/compatibility.md). Release process: [docs/releases.md](docs/releases.md). Writing a patch: [docs/creating-patches.md](docs/creating-patches.md).

segarecomp needs a build that includes the patch installer and native patch SDK. That functionality is on the product's `main` branch and is not part of the v0.7.0 release.

## Repository layout

```text
patches/<platform>/<game>/   README.md, release.json, source/ (reviewed provider source and BPS deltas)
catalog/index.json           static catalog derived from every release.json
docs/                        installation, compatibility, authoring, releases
scripts/                     repository checks (no commercial data needed)
```

## Links

* Product, SDK documentation and releases: <https://github.com/marinocg/segarecomp>
* Native patch SDK: [docs/product/native-patch-sdk.md](https://github.com/marinocg/segarecomp/blob/main/docs/product/native-patch-sdk.md)
* Security policy: [SECURITY.md](SECURITY.md). Contributing: [CONTRIBUTING.md](CONTRIBUTING.md)

## License and trademarks

Repository tooling and documentation are under the [MPL-2.0](LICENSE) unless a file says otherwise. The Sonic 1 provider is under the repository's [MPL-2.0](LICENSE): its package manifest has no license field, so this repository establishes it without changing the package bytes. The Sonic 2 and Sonic 3 & Knuckles providers keep the [MIT license](LICENSES/MIT.txt) that their package manifests declare. BPS deltas are data-only patches for the exact images they name.

SEGA, Sega Genesis, Mega Drive, Sonic the Hedgehog and Streets of Rage are trademarks of SEGA Corporation. segarecomp and this repository are not affiliated with or endorsed by SEGA.

## Documentation site

`site/` is an Astro + Starlight project (static output, built-in Pagefind search). Build it with `cd site && npm ci && npm run build`; CI also runs the link checker, a search test and every code sample of the [getting-started guide](site/src/content/docs/getting-started.md). Imported product documentation follows the pinned-revision rule in [docs/product-docs.md](docs/product-docs.md). Repository policy: [trust and licensing](docs/policy.md), [layout and versioning](docs/layout-and-versioning.md), [publication restrictions](docs/publication-restrictions.md), [repository settings](docs/repository-settings.md).
