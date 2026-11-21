// robots.txt: everything public may be crawled, and the sitemap Starlight generates is announced at its real production URL (site + base path).
export const GET = ({ site }: { site: URL }) => {
  const base = import.meta.env.BASE_URL.replace(/\/$/, '');
  const body = `User-agent: *\nAllow: /\n\nSitemap: ${new URL(`${base}/sitemap-index.xml`, site).href}\n`;
  return new Response(body, { headers: { 'Content-Type': 'text/plain; charset=utf-8' } });
};
