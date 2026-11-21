// The authoritative catalog, served unchanged at <site>/catalog/index.json (static file, application/json by extension on GitHub Pages).
// It is the same validated file the HTML pages are generated from; a malformed catalog throws and fails the build. Format: docs/catalog-format.md.
import { readFileSync } from 'node:fs';
import { CATALOG_PATH, parseCatalog } from '../../lib/catalog.mjs';

export const GET = () => {
  const text = readFileSync(CATALOG_PATH, 'utf8');
  parseCatalog(text, CATALOG_PATH);
  return new Response(text, { headers: { 'Content-Type': 'application/json; charset=utf-8' } });
};
