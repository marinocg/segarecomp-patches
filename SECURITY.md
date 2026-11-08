# Security policy

## Native patches are executable code

A schema 2 `.segapatch` contains a C11 `provider.c` that segarecomp compiles into the Patched program, where it runs with that program's operating-system permissions. **It is not sandboxed.** Bounded archive parsing, SHA-256 digests and a restricted SDK are integrity and hygiene measures, not a security boundary. A digest proves a file is unchanged; it does not authenticate its publisher. There are no signatures today. Install native patches only from sources you trust, and read the approval sheet in the launcher.

Schema 1 (BPS-only) packages contain no executable code.

## Reporting a vulnerability

Please report privately through GitHub's **Report a vulnerability** (Security tab of this repository) rather than a public issue. Include the package id/version, what you observed and, if possible, a minimal reproduction that does not contain game data. Do not attach ROMs or game dumps.

Examples of in-scope reports: a published asset whose digest differs from `release.json`/`SHA256SUMS`, provider code that does more than its documentation states, or commercial game content committed to the repository.
