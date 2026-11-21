#!/usr/bin/env bash
# Build the product CLI (`segarecomp`) at one EXACT product revision, no viewer and no tests. Used by CI wherever a schema 3 package must be built or audited.
#   build_product_cli.sh <40-hex product commit> <work dir>      prints the path of the built CLI on its last line; the SDK headers are <work dir>/src/platforms
# The revision is never a branch or tag: a schema 3 package is only reproducible with the tool revision recorded in its build record (scripts/PRODUCT_REF).
set -euo pipefail
REF=${1:?product commit}; DEST=${2:?work dir}
[[ $REF =~ ^[0-9a-f]{40}$ ]] || { echo "the product revision must be a full 40-hex commit, got '$REF'" >&2; exit 2; }
[ -d "$DEST/src/.git" ] || git clone --quiet --filter=blob:none https://github.com/marinocg/segarecomp.git "$DEST/src"
git -C "$DEST/src" checkout --quiet --detach "$REF"
cmake -S "$DEST/src" -B "$DEST/build" -DCMAKE_BUILD_TYPE=Release -DBUILD_TESTING=OFF -DSEGARECOMP_ENABLE_SDL3_VIEWER=OFF >&2
cmake --build "$DEST/build" --target segarecomp -j"$(nproc)" >&2
echo "$DEST/build/apps/segarecomp/segarecomp"
