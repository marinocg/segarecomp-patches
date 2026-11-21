import { defineCollection } from 'astro:content';
import { docsLoader } from '@astrojs/starlight/loaders';
import { docsSchema } from '@astrojs/starlight/schema';
import { CATALOG_PATH, loadCatalog, slug } from './lib/catalog.mjs';

// The catalog collection is generated from catalog/index.json (or CATALOG_PATH, used by the fixture tests) and nothing else:
// there is no hand-maintained copy of any package fact. A malformed entry throws here, so the build fails.

export const collections = {
  docs: defineCollection({ loader: docsLoader(), schema: docsSchema() }),
  catalog: defineCollection({
    loader: {
      name: 'catalog-index-loader',
      load: async ({ store, generateDigest }) => {
        store.clear();
        for (const e of loadCatalog(CATALOG_PATH)) {
          const id = slug(e);
          store.set({ id, data: e, digest: generateDigest(e) });
        }
      },
    },
  }),
};
