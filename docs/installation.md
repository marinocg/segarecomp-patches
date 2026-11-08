# Installing a patch

Everything here was checked against the `segarecomp` command-line tool and the product's [patch package guide](https://github.com/marinocg/segarecomp/blob/main/docs/product/patch-packages.md). If a command differs in your build, the product documentation is authoritative.

## Before you start

* You need a segarecomp build that includes the patch installer and native patch SDK (on the product's `main` branch; not in v0.7.0).
* You need your own copy of the **exact** game image listed on the patch's page. Compare it with `sha256sum` (or `shasum -a 256`). A different dump, revision or region is refused.
* Download the `.segapatch` and `SHA256SUMS` from the [release](https://github.com/marinocg/segarecomp-patches/releases) and check the archive:

  ```text
  sha256sum -c SHA256SUMS --ignore-missing
  ```

  The digest is an integrity check, **not** publisher authentication.

## Launcher (recommended)

1. Add your game image to the launcher and open its **Details** page.
2. In the **Patches / Variants** card choose **Install patch...** and select the `.segapatch`.
3. The package is verified against the exact image. For a **schema 2** package a sheet shows author, license, package identity, source digest and declared capabilities. It says the package contains executable source and is not sandboxed. Approve only if you trust it. A changed package has a different identity and needs a new approval.
4. Select **Patched**, then **Build patched version**, then **Play Patched**. **Vanilla** stays untouched. **Remove patch** returns to Vanilla and keeps saves and settings.

The first patched build compiles the game and can take several minutes. Sonic 3 & Knuckles is built as a declared lock-on cartridge; the launcher recognises the exact image and does this automatically.

## Command line

Inspect, verify and (for schema 1) apply a package:

```text
segarecomp patch inspect <package.segapatch>
segarecomp patch verify  <package.segapatch> --rom <original image>
segarecomp patch apply   <package.segapatch> --rom <original image> --out <patched image>
```

Each prints one JSON object (`"ok":true` or `"ok":false` plus an error) and exits 0, 1 (refused) or 2 (usage). `inspect` reports `schema_version`, `executable_code`, `native_abi`, `native_capabilities`, `native_source_sha256` and `package_identity`. Compare these with the package's entry in `release.json`.

### Schema 1 (BPS only), e.g. Streets of Rage 2

1. `segarecomp patch verify sor2-widescreen.segapatch --rom <original image>`
2. `segarecomp patch apply sor2-widescreen.segapatch --rom <original image> --out <patched image>`
3. Build the patched image with the normal `segarecomp build` workflow (see the product README, "Build from source" and the launcher), keeping it as a separate program from the vanilla build.

### Schema 2 (native), e.g. Sonic 1, 2 and 3 & Knuckles

1. `segarecomp patch inspect <package>`: read author, license, `executable_code`, capabilities and the `package_identity`.
2. Review `provider.c` (it is the file under `source/` for this package, byte for byte) and decide whether you trust it.
3. `segarecomp patch verify <package> --rom <original image>`.
4. Build the separate Patched program with `segarecomp build --rom <original image> --patch-package <package> --patch-identity <package_identity> ...` plus the usual `--output`, `--cc` and `--runtime-dir` options. The build re-verifies the package and identity, extracts and compiles `provider.c` against the public SDK only. `--patch-identity` is a consistency check, not authenticated consent. For Sonic 3 & Knuckles add `--mapper lock_on`.

## Widescreen settings

Open the pause menu (**Esc**) and choose **Widescreen Mode** (Enhanced Widescreen), **Widescreen Width** 100 (16:9) and a **Side Presentation**. Packages carry a suggested starting setting; you can change it. The patches are validated for 16:9 only.

## Troubleshooting

* *"the original image is not the exact image this patch was made for"*: your dump differs. Compare the SHA-256 on the patch's page.
* The Sonic 3 & Knuckles composite stops after a few frames: it was not built as a lock-on cartridge.
* Frames the provider cannot explain are declined and drawn by the generic renderer; some backgrounds look wrapped by design.
