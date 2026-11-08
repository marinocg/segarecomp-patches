# Creating a patch

Authoring tools and the SDK live in the [segarecomp product repository](https://github.com/marinocg/segarecomp); this repository only publishes finished, reviewed patches.

1. Read [`patch-packages.md`](https://github.com/marinocg/segarecomp/blob/main/docs/product/patch-packages.md) and [`native-patch-sdk.md`](https://github.com/marinocg/segarecomp/blob/main/docs/product/native-patch-sdk.md). Start from the SDK sample `provider.c` if you need native code.
2. Compile-check a provider as the build does: `cc -std=c11 -Wall -Wextra -pedantic -I platforms/genesis/sdk -c provider.c`.
3. Create the package with the product's `tools/segapatch.py create ...` (deterministic output) and check it with `segarecomp patch inspect|verify`.
4. Add `patches/<platform>/<game>/` with `README.md`, `release.json` and, for native code, `source/provider.c` (its SHA-256 must equal the package's native source digest).
5. Run `python3 scripts/check_repo.py` and `python3 scripts/build_catalog.py`, then open a pull request. Maintainers do the publication review and upload the package to a draft release.

A BPS delta of a commercial image is never committed; it travels only in the release asset. Only patches that work against their exact image qualify. See [CONTRIBUTING.md](../CONTRIBUTING.md).

The package format is currently schema 1 (BPS only) and schema 2 (BPS plus trusted C11). Later schemas are expected to be additive; existing packages stay valid.
