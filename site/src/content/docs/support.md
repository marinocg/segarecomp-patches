---
title: What is supported
description: This site makes no support claims of its own. The product compatibility ledger is the single record.
---

This documentation site does not decide which games or platforms work. The only record of which platforms exist, which games were tried, how far they got and on what evidence is the product's **compatibility ledger**:

* [`compatibility-ledger.json`](https://github.com/marinocg/segarecomp/blob/8fa9f66f839bbd750fb9171ac0d67016ca2b08d4/docs/product/compatibility-ledger.json) (the data)
* [How to read it](https://github.com/marinocg/segarecomp/blob/8fa9f66f839bbd750fb9171ac0d67016ca2b08d4/docs/product/compatibility-ledger.md)

The ledger link above is pinned to the product revision recorded in `docs/product-docs.pin.json`.

Each published package states the exact image SHA-256 it applies to, its scope and its limitations in its own `release.json` and README in the [repository](https://github.com/marinocg/segarecomp-patches/tree/main/patches). A package that is not listed there, or an image whose digest differs, is not supported.

Features that are not implemented yet are not documented here as available.
