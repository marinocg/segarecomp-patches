// Small shared SEO helpers: metadata text and Schema.org JSON-LD derived ONLY from verified catalog facts and real page metadata.
// Nothing here invents reviews, ratings, prices, download counts, authors, organisations, publication dates, operating systems or compatibility.
export const PLATFORM = { genesis: 'Sega Genesis / Mega Drive', 'master-system': 'Sega Master System', 'game-gear': 'Sega Game Gear', 'sega-cd': 'Sega CD' };
const LICENSE_URL = { 'MPL-2.0': 'https://www.mozilla.org/en-US/MPL/2.0/', MIT: 'https://opensource.org/licenses/MIT' };

/** Absolute canonical URL of a site path (`/catalog/`), from Astro.site and the base path; always the trailing-slash form. */
export function absolute(site, base, path) {
  const b = base.replace(/\/$/, '');
  return new URL(`${b}${path.startsWith('/') ? path : '/' + path}`, site).href;
}

/** Serialise for an inline <script type="application/ld+json">: `<` is escaped so page text can never end the script element. */
export function ldScript(obj) {
  return { tag: 'script', attrs: { type: 'application/ld+json' }, content: JSON.stringify(obj).replace(/</g, '\\u003c') };
}

const trunc = (s, n) => (s.length <= n ? s : s.slice(0, n).replace(/\s+\S*$/, '').replace(/[.,;:]$/, '') + '…');
const firstSentence = (s) => (s.match(/^.*?[.!?](?=\s|$)/)?.[0] ?? s);

/** Meta description of a package page, from its own catalog fields. */
export function packageDescription(e) {
  const kind = e.schema_version === 3 ? 'source-based mod package (schema 3)' : e.trust === 'trusted-native-source' ? 'native-source patch package' : 'data-only BPS patch package';
  return trunc(`${e.name} ${e.version} for ${e.game} on ${PLATFORM[e.platform] ?? e.platform}: a segarecomp ${kind}. ${firstSentence(e.supported_scope)}`, 200);
}

export function websiteLd(site, base, description) {
  const url = absolute(site, base, '/');
  return { '@context': 'https://schema.org', '@type': 'WebSite', '@id': `${url}#website`, name: 'segarecomp patches', url, description, inLanguage: 'en' };
}

export function articleLd(site, base, path, title, description, type = 'TechArticle') {
  const url = absolute(site, base, path);
  return { '@context': 'https://schema.org', '@type': type, '@id': `${url}#page`, headline: title, name: title, description, url, mainEntityOfPage: url, inLanguage: 'en',
    isPartOf: { '@id': `${absolute(site, base, '/')}#website` } };
}

export function breadcrumbLd(items) {   // [{ name, url }] from the site root down; the last item is the page itself
  return { '@context': 'https://schema.org', '@type': 'BreadcrumbList', itemListElement: items.map((x, i) => ({ '@type': 'ListItem', position: i + 1, name: x.name, item: x.url })) };
}

export function collectionLd(site, base, entries, description) {
  const url = absolute(site, base, '/catalog/');
  return { '@context': 'https://schema.org', '@type': 'CollectionPage', '@id': `${url}#page`, name: 'Patch catalog', url, description, inLanguage: 'en',
    isPartOf: { '@id': `${absolute(site, base, '/')}#website` },
    mainEntity: { '@type': 'ItemList', numberOfItems: entries.length,
      itemListElement: entries.map((e, i) => ({ '@type': 'ListItem', position: i + 1, url: absolute(site, base, `/catalog/${e.id}/${e.version}/`), name: `${e.name} ${e.version}` })) } };
}

/** A published package: downloadable software with its version, digests and licence (when the package declares one). */
export function packageLd(site, base, e) {
  const url = absolute(site, base, `/catalog/${e.id}/${e.version}/`);
  const ld = { '@context': 'https://schema.org', '@type': 'SoftwareApplication', '@id': `${url}#software`, name: `${e.name} ${e.version}`, url, softwareVersion: e.version,
    description: e.supported_scope, downloadUrl: e.asset.url, fileSize: `${e.package_size} bytes`, inLanguage: 'en',
    additionalProperty: [{ '@type': 'PropertyValue', name: 'Package SHA-256', value: e.package_sha256 },
      // a schema 3 mod has no single source image: it lists the images it targets, and has no BPS or patched image to describe
      ...(e.schema_version === 3 ? e.images.map((i) => ({ '@type': 'PropertyValue', name: `Target image SHA-256 (${i.label})`, value: i.sha256 })) : [{ '@type': 'PropertyValue', name: 'Source image SHA-256', value: e.source_image_sha256 }])] };
  if (LICENSE_URL[e.license]) ld.license = LICENSE_URL[e.license];
  return ld;
}
