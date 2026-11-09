---
title: Security
description: Native patches are executable and not sandboxed. What a digest proves, what it does not, and how to report a problem.
---

## Native patches are executable code

A schema 2 `.segapatch` contains a C11 `provider.c`. segarecomp compiles it into the separate Patched program, where it runs with that program's operating-system permissions. **It is not sandboxed.** Bounded archive parsing, SHA-256 digests, a restricted SDK header and compiler flags are integrity and hygiene measures, not a security boundary.

Schema 1 (BPS-only) packages contain no executable code. They are still untrusted input: the importer parses them with strict bounds and verifies the exact original image before producing anything.

## What a digest proves

A digest proves that a file is the one the manifest names. It does **not** prove who wrote it or that it is safe. There are no signatures, certificates or identity service today. Do not treat a catalog entry or a matching hash as an endorsement.

## What the launcher does

The launcher shows an approval sheet (author, licence, package identity, source digest, declared capabilities, "contains executable source, not sandboxed") and builds only the exact package identity you approved. A changed package has a new identity and needs a new approval. See [patch packages](/product/patch-packages/#trust).

## Trust classes

| Class | Executes code | Available today |
|---|---|---|
| BPS-only (`data-only`) | No | Yes |
| Native (`trusted-native-source`) | Yes, unsandboxed | Yes |
| Scripted or mixed classes | not applicable | Reserved; none exists to install |

A package with any native source is native whatever else it contains. The repository policy is in [docs/policy.md](https://github.com/marinocg/segarecomp-patches/blob/main/docs/policy.md).

## Reporting

Report privately through GitHub's **Report a vulnerability** on the [repository](https://github.com/marinocg/segarecomp-patches/security). Include the package id and version and a minimal reproduction **without game data**. Never attach ROMs or dumps.
