// Starlight route middleware: one shared place that adds Schema.org JSON-LD to documentation pages from their real title and description.
// Catalog pages carry their own JSON-LD (src/pages/catalog/*) and are skipped here.
import { defineRouteMiddleware } from '@astrojs/starlight/route-data';
import { articleLd, ldScript, websiteLd } from './lib/seo.mjs';

export const onRequest = defineRouteMiddleware((context) => {
  const { starlightRoute } = context.locals;
  const { head, entry } = starlightRoute;
  if (head.some((h) => h.tag === 'script' && h.attrs?.type === 'application/ld+json')) return;
  const { title, description } = entry.data;
  if (!description || context.url.pathname.endsWith('/404') || entry.id === '404') return;
  const base = import.meta.env.BASE_URL;
  const rel = context.url.pathname.slice(base.replace(/\/$/, '').length) || '/';
  if (rel === '/') head.push(ldScript(websiteLd(context.site!, base, description)));
  else head.push(ldScript(articleLd(context.site!, base, rel, title, description, entry.id === 'privacy' ? 'WebPage' : 'TechArticle')));
});
