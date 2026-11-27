# Native ABI 1: deprecation and retention policy

Native ABI 1 (schema 2 packages written against `segarecomp_genesis_patch.h`) is **deprecated but supported**. New work is a schema 3 mod written against native ABI 2; the product's [migration guide](https://github.com/marinocg/segarecomp/blob/main/docs/product/native-abi-migration.md) maps one to the other. Deprecation removes nothing.

## Retained packages and their successors

| Deprecated ABI 1 package (published in `v0.1.0`) | Recommended ABI 2 successor | Successor state |
|---|---|---|
| `sonic1-native-widescreen` 2.0.1 | `sonic1-native-widescreen-abi2` ([source](../patches/genesis/sonic-1/native-widescreen-abi2/README.md)) | source only: not published, no recorded package |
| `sonic2-native-widescreen` 3.0.1 | `sonic2-native-widescreen-abi2-rev00` ([source](../patches/genesis/sonic-2/native-widescreen-abi2-rev00/README.md)) | candidate: not published |
| `sonic2-native-widescreen-rev01` 3.0.1 | `sonic2-native-widescreen-abi2-rev01` ([source](../patches/genesis/sonic-2/native-widescreen-abi2-rev01/README.md)) | candidate: not published |
| `sonic3k-native-widescreen` 1.0.1 | `sonic3k-native-widescreen-abi2` ([source](../patches/genesis/sonic-3-and-knuckles/native-widescreen-abi2/README.md)) | candidate: not published |

**Until a successor is published, the ABI 1 package is the only downloadable one for its game, and it is the one to install.** `sor2-widescreen` is a data-only schema 1 package with no native code: this policy does not apply to it.

## What is kept

Until the product's ABI 1 removal gate is met and a separate removal decision is taken ([product ADR 0322](https://github.com/marinocg/segarecomp/blob/main/docs/decisions/0322-abi-1-deprecation-and-removal-gate.md)):

* the packages above stay published and installable, with the same ids, versions and digests; they are never rebuilt, renamed, re-released or removed because of the deprecation;
* their sources stay in this repository;
* the launcher treats them as before: an exact-image schema 2 package with its native-code approval sheet. The deprecation adds no launcher warning and changes no behaviour.

The removal gate needs a published release with the ABI 2 replacements, no recommended catalog package with `native_abi` 1, a published and elapsed support window with a migration notice, a third-party impact assessment and an explicit operator decision. None is scheduled.

## How it is shown and enforced

* `catalog/index.json`: every `native_abi` 1 entry carries `abi_status: "deprecated"`. The generator derives it; no published value changes.
* `superseded_by` is added to an old entry only when its successor is published (`scripts/prepare_release.py supersede`): the field must name an existing catalog entry and is immutable once published, so it cannot point at an unpublished package. When it is added, this table is updated in the same change.
* The site's `/catalog/` page lists only packages without a published successor. A retained ABI 1 package stays there, marked "replacement not yet published", until `superseded_by` is recorded ([sequence](releases.md#replacing-a-published-package-supersession)); after that its page and download remain.
* `scripts/check_repo.py` accepts exactly the four retained package versions with their recorded digests and rejects any other native ABI 1 package, including a new version of a retained id.
