// @ts-check
import { defineConfig } from 'astro/config';
import starlight from '@astrojs/starlight';
import tailwindcss from '@tailwindcss/vite';

// GitHub Pages project site: https://marinocg.github.io/segarecomp-patches/ . SITE_BASE overrides the path prefix (the tools in
// scripts/ read the same variable, default included). Site-absolute links written in Markdown ("/security/") are prefixed by the
// rehype plugin below, so content never hard-codes the deployment path.
const SITE = process.env.SITE_URL ?? 'https://marinocg.github.io';
const BASE = (process.env.SITE_BASE ?? '/segarecomp-patches').replace(/\/+$/, '');

/** Prefix site-absolute hrefs with the base path (Starlight already does this for its own navigation and assets). */
function rehypeBaseLinks() {
  const walk = (node) => {
    if (node.type === 'element' && node.tagName === 'a' && typeof node.properties?.href === 'string') {
      const h = node.properties.href;
      if (BASE && h.startsWith('/') && !h.startsWith('//') && h !== BASE && !h.startsWith(BASE + '/')) node.properties.href = BASE + h;
    }
    (node.children ?? []).forEach(walk);
  };
  return walk;
}

// Static output only: `npm run build` writes dist/ (HTML, CSS, JS and the Pagefind search index).
// No server, no runtime backend and no network fetch at runtime.
export default defineConfig({
  site: SITE,
  base: BASE || '/',
  markdown: { rehypePlugins: [rehypeBaseLinks] },
  vite: { plugins: [tailwindcss()] },
  integrations: [
    starlight({
      title: 'segarecomp patches',
      description: 'Documentation for the segarecomp public patch collection: package formats, the native patch SDK, trust and security.',
      social: [{ icon: 'github', label: 'GitHub', href: 'https://github.com/marinocg/segarecomp-patches' }],
      editLink: { baseUrl: 'https://github.com/marinocg/segarecomp-patches/edit/main/site/' },
      lastUpdated: false,
      customCss: ['./src/styles/global.css'],
      components: { Hero: './src/components/Hero.astro' },
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
