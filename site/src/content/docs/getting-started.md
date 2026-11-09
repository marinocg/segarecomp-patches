---
title: Getting started
description: Write, build, pack and verify a synthetic native patch provider with the shipped segarecomp tools. No game image is involved.
---

This guide takes you from nothing to a verified `.segapatch` package using only **fabricated** data. It never touches a commercial game. Every code block is either executed by this repository's CI against pinned product tools or is explicitly marked non-executable with a reason; the marker is the line above each block in the page source.

:::caution[Native patches are executable code]
A schema 2 package contains C source that is compiled into the Patched program and runs with that program's permissions. It is **not sandboxed**. Read the [security page](/security/) before installing one that someone else wrote.
:::

## What you need

* A clone of [`marinocg/segarecomp-patches`](https://github.com/marinocg/segarecomp-patches) (this repository) for the synthetic fixture script and the sample provider.
* The product's authoring tool `tools/segapatch.py` and the SDK header `platforms/genesis/sdk/segarecomp_genesis_patch.h`, taken at the revision this repository pins in `scripts/SEGAPATCH_REF`.
* A C11 compiler (`cc`) and Python 3.
* The shipped `segarecomp` command-line tool from the pinned product release, for `segarecomp patch verify`.

The commands below use four environment variables: `WORK` (an empty scratch directory), `SEGAPATCH` (path to `segapatch.py`), `SDK_INCLUDE` (the directory that contains the SDK header) and `SEGARECOMP` (path to the shipped CLI). CI sets them after downloading the pinned files; you set them to wherever you saved yours.

<!-- sample: non-executable: environment setup that CI performs before running the guide -->
```sh
REF=$(cat scripts/SEGAPATCH_REF)
curl -fsSL "https://raw.githubusercontent.com/marinocg/segarecomp/$REF/tools/segapatch.py" -o segapatch.py
curl -fsSL "https://raw.githubusercontent.com/marinocg/segarecomp/$REF/platforms/genesis/sdk/segarecomp_genesis_patch.h" -o segarecomp_genesis_patch.h
export WORK="$(mktemp -d)" SEGAPATCH="$PWD/segapatch.py" SDK_INCLUDE="$PWD" SEGARECOMP=/path/to/segarecomp
```

## 1. Make a synthetic image

The fixture script fabricates a tiny deterministic image with a Genesis-style header. It is not derived from any game, so it can be shared freely.

<!-- sample: exec -->
```sh
python3 scripts/synthetic_fixture.py --write-images "$WORK"
sha256sum "$WORK/synthetic.bin"
```

## 2. Read the provider

`examples/synthetic/provider.c` is the product's synthetic SDK sample. It exports `segarecomp_patch_provider()`, declines every frame whose state it cannot verify in `prepare`, contributes one scenery word per off-screen cell and a small RGBA overlay. A real provider reads only what the host gives it through the SDK header; there is no API to write guest memory.

## 3. Compile-check it like the build does

The launcher compiles a provider as strict C11 against the SDK header only. Do the same before packing.

<!-- sample: exec -->
```sh
cc -std=c11 -Wall -Wextra -pedantic -Werror -I "$SDK_INCLUDE" -c examples/synthetic/provider.c -o "$WORK/provider.o"
```

## 4. Pack it

A native-only package leaves the image unchanged; add `--target` to also ship a BPS delta that changes the game image.

<!-- sample: exec -->
```sh
python3 "$SEGAPATCH" create --source "$WORK/synthetic.bin" --id synthetic-native --name "Synthetic native" --version 1.0.0 \
    --native-source examples/synthetic/provider.c --native-caps frame.work_ram,frame.vdp,scenery.words,overlay.rgba \
    --author "Your Name" --license MIT --out "$WORK/synthetic-native.segapatch"
sha256sum "$WORK/synthetic-native.segapatch"
```

Packing is deterministic: the same inputs always give the same bytes, so a second build can be compared with the first.

<!-- sample: exec -->
```sh
python3 "$SEGAPATCH" create --source "$WORK/synthetic.bin" --id synthetic-native --name "Synthetic native" --version 1.0.0 \
    --native-source examples/synthetic/provider.c --native-caps frame.work_ram,frame.vdp,scenery.words,overlay.rgba \
    --author "Your Name" --license MIT --out "$WORK/again.segapatch"
cmp "$WORK/synthetic-native.segapatch" "$WORK/again.segapatch"
```

## 5. Verify it with the shipped CLI

`segarecomp patch inspect` reports the manifest facts without any image. `verify` checks the archive, every digest and the exact image.

<!-- sample: exec-cli -->
```sh
"$SEGARECOMP" patch inspect "$WORK/synthetic-native.segapatch"
"$SEGARECOMP" patch verify "$WORK/synthetic-native.segapatch" --rom "$WORK/synthetic.bin"
```

A different image is refused, because the package names the exact SHA-256 of the image it applies to. This block must fail, and the guide treats the refusal as success:

<!-- sample: exec-cli -->
```sh
head -c 8192 /dev/zero > "$WORK/other.bin"
if "$SEGARECOMP" patch verify "$WORK/synthetic-native.segapatch" --rom "$WORK/other.bin"; then echo "unexpectedly accepted"; exit 1; fi
```

## 6. Try a BPS-only (schema 1) package

A schema 1 package carries one BPS delta and no code. The reference reader applies it and reproduces the target image exactly.

<!-- sample: exec -->
```sh
python3 "$SEGAPATCH" create --source "$WORK/synthetic.bin" --target "$WORK/synthetic-target.bin" --id synthetic-bps --name "Synthetic BPS" \
    --version 1.0.0 --out "$WORK/synthetic-bps.segapatch"
python3 "$SEGAPATCH" apply "$WORK/synthetic-bps.segapatch" --source "$WORK/synthetic.bin" --out "$WORK/patched.bin"
cmp "$WORK/patched.bin" "$WORK/synthetic-target.bin" && echo "patched image equals target"
```

## Where to go next

* [Patch packages](/product/patch-packages/) and the [native patch SDK](/product/native-patch-sdk/) are the format and API references.
* Publishing a real patch here follows the layout and review rules in [the repository documentation](/repository/).
* What is supported for which game is recorded only in the [compatibility ledger](/support/).
