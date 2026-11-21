// The versioned JSON Schemas at stable URLs: <site>/schema/catalog-1.schema.json and <site>/schema/release-1.schema.json
// (the `$id` of each schema). Served unchanged from catalog/schema/, so there is no second copy.
import { readdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import { SCHEMA_DIR } from '../../lib/catalog.mjs';

export const getStaticPaths = () =>
  readdirSync(SCHEMA_DIR).filter((f) => /^[a-z]+-\d+\.schema\.json$/.test(f)).sort().map((f) => ({ params: { name: f.replace(/\.json$/, '') }, props: { file: f } }));

export const GET = ({ props }: { props: { file: string } }) => {
  const text = readFileSync(join(SCHEMA_DIR, props.file), 'utf8');
  JSON.parse(text);
  return new Response(text, { headers: { 'Content-Type': 'application/schema+json; charset=utf-8' } });
};
