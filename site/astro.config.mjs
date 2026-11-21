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
      description: 'Reviewed widescreen and game patches for Sega Genesis / Mega Drive games recompiled by segarecomp, a static recompiler, plus the .segapatch package format, native patch SDK and security documentation.',
      social: [{ icon: 'github', label: 'GitHub', href: 'https://github.com/marinocg/segarecomp-patches' }],
      lastUpdated: false,
      routeMiddleware: './src/routeData.ts',
      // No sharing image exists, so the card is the plain summary card (Starlight's default would announce a large image that is not there).
      head: [{ tag: 'meta', attrs: { name: 'twitter:card', content: 'summary' } }],
      customCss: ['./src/styles/global.css'],
      components: { Hero: './src/components/Hero.astro', Footer: './src/components/Footer.astro' },
      sidebar: [
        { label: 'Start here', items: [{ slug: 'getting-started' }, { slug: 'security' }, { slug: 'support' }, { slug: 'privacy' }] },
        { label: 'Catalog', items: [{ label: 'All packages', link: '/catalog/' }] },
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
