// Strict reader for catalog/index.json (catalog_format 1 or 2; 2 = 1 plus schema 3 mod entries). Plain ESM so the Astro content collection and the Node tests share it.
// The pages are generated from this data only; a malformed entry throws and therefore fails `astro build`.
// The authoritative format contract is catalog/schema/catalog-2.schema.json (validated in CI by scripts/validate_catalog.py before the build);
// this schema asserts what the pages render, so a page can never show a missing digest or an unpinned source.
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { z } from 'astro/zod';

const sha256 = z.string().regex(/^[0-9a-f]{64}$/);
const sha1 = z.string().regex(/^[0-9a-f]{40}$/);
const https = z.string().regex(/^https:\/\/\S+$/);

const common = {
  id: z.string().regex(/^[a-z0-9]+(-[a-z0-9]+)*$/),
  version: z.string().regex(/^\d+\.\d+\.\d+(-[0-9A-Za-z.-]+)?$/),
  name: z.string().min(1),
  platform: z.enum(['genesis', 'master-system', 'game-gear', 'sega-cd']),
  game: z.string().min(1),
  game_path: z.string().min(1),
  source_path: z.string().min(1).optional(),   // where the sources were at source_revision.commit; absent on entries published before the per-patch layout (they were under game_path)
  release: z.string().regex(/^v\d+\.\d+\.\d+$/),
  source_identity_kind: z.enum(['cartridge-image-sha256', 'disc-image-identity']),
  bios_requirement: z.enum(['none', 'required', 'optional']),
  executable_code: z.boolean(),
  package_sha256: sha256,
  package_size: z.number().int().positive(),
  package_identity: sha256,
  evidence_tier: z.enum(['synthetic-only', 'maintainer-attested', 'automated']),
  gameplay: z.string().min(1),
  license: z.string().min(1),
  supported_scope: z.string().min(1),
  limitations: z.array(z.string()),
  superseded_by: z.string().optional(),
  source_revision: z.object({ repository: https, commit: sha1, tag: z.string().optional(), tag_commit: sha1.optional() }).strict(),
  build: z.object({ writer: z.string(), writer_ref: sha1, deterministic: z.boolean() }).strict(),
  asset: z.object({ name: z.string().min(1), url: https }).strict(),
};

/** A schema 1 or 2 package: a BPS delta against one exact image, optionally with native C11 source. */
export const patchEntrySchema = z.object({
  ...common,
  revision: z.string().min(1),
  region: z.string().min(1),
  schema_version: z.union([z.literal(1), z.literal(2)]),
  native_abi: z.number().int().nullish(),
  capabilities: z.array(z.string()).optional(),
  trust: z.enum(['data-only', 'trusted-native-source']),
  source_image_sha256: sha256,
  patched_image_sha256: sha256,
  bps_sha256: sha256,
  native_source_sha256: sha256.nullish(),
}).passthrough();

/** A schema 3 / native ABI 2 mod: source-based, no BPS delta and no patched image. `.strict()` so a fabricated BPS or ROM field fails the build. */
export const modEntrySchema = z.object({
  ...common,
  schema_version: z.literal(3),
  native_abi: z.literal(2),
  capabilities: z.array(z.string().min(1)).min(1),
  trust: z.literal('trusted-native-source'),
  images: z.array(z.object({ label: z.string().min(1), sha256 }).strict()).min(1),
}).strict();

export const isMod = (e) => e.schema_version === 3;

// One entry shape per package schema; the error names the real problem instead of "no alternative matched".
export const entrySchema = z.unknown().transform((v, ctx) => {
  const r = (v && typeof v === 'object' && v.schema_version === 3 ? modEntrySchema : patchEntrySchema).safeParse(v);
  if (r.success) return r.data;
  for (const i of r.error.issues) ctx.addIssue({ code: 'custom', message: i.message, path: i.path });
  return z.NEVER;
});

export const catalogSchema = z.object({ catalog_format: z.union([z.literal(1), z.literal(2)]), packages: z.array(entrySchema) }).strict();

/** Parse and validate; duplicates of (id, version) are refused. Returns the entries sorted by game, id, version. */
export function parseCatalog(text, where = 'catalog') {
  const r = catalogSchema.safeParse(JSON.parse(text));
  if (!r.success) {
    const msg = r.error.issues.map((i) => `${i.path.join('.')}: ${i.message}`).join('; ');
    throw new Error(`${where}: malformed catalog: ${msg}`);
  }
  const seen = new Set();
  for (const p of r.data.packages) {
    const k = `${p.id}@${p.version}`;
    if (seen.has(k)) throw new Error(`${where}: duplicate catalog entry ${k}`);
    seen.add(k);
  }
  return [...r.data.packages].sort((a, b) => (a.platform + a.game + a.id + a.version).localeCompare(b.platform + b.game + b.id + b.version));
}

export function loadCatalog(path) { return parseCatalog(readFileSync(path, 'utf8'), path); }

export const slug = (e) => `${e.id}/${e.version}`;
export const shortSha = (s) => s.slice(0, 12);
export const kib = (n) => (n < 1024 ? `${n} B` : `${(n / 1024).toFixed(1)} KiB`);

// The one place the catalog location is decided (CATALOG_PATH is only for the fixture tests): the content collection, the HTML pages and the
// public /catalog/index.json endpoint all read the same validated file.
// Astro (and its bundled endpoints) always run with the site/ directory as cwd, so the repository root is its parent.
export const REPO_ROOT = resolve(process.cwd(), '..');
export const CATALOG_PATH = process.env.CATALOG_PATH ?? resolve(REPO_ROOT, 'catalog/index.json');
export const SCHEMA_DIR = resolve(REPO_ROOT, 'catalog/schema');
