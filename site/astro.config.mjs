// @ts-check
import { defineConfig } from 'astro/config';
import starlight from '@astrojs/starlight';

// Static output only: `npm run build` writes dist/ (HTML, CSS, JS and the Pagefind search index).
// No server, no runtime backend and no network fetch at runtime. Deployment target is decided separately (SEG-134-T006).
export default defineConfig({
  integrations: [
    starlight({
      title: 'segarecomp patches',
      description: 'Documentation for the segarecomp public patch collection: package formats, the native patch SDK, trust and security.',
      social: [{ icon: 'github', label: 'GitHub', href: 'https://github.com/marinocg/segarecomp-patches' }],
      editLink: { baseUrl: 'https://github.com/marinocg/segarecomp-patches/edit/main/site/' },
      lastUpdated: false,
      sidebar: [
        { label: 'Start here', items: [{ slug: 'getting-started' }, { slug: 'security' }, { slug: 'support' }] },
        {
          label: 'Reference (imported)',
          items: [
            { slug: 'product/patch-packages' },
            { slug: 'product/native-patch-sdk' },
            { slug: 'product/widescreen-and-patches' },
          ],
        },
        { label: 'This repository', items: [{ slug: 'repository' }] },
      ],
    }),
  ],
});
