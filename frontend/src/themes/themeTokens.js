export const DEFAULT_THEME = Object.freeze({
  code: 'WORLD', name: 'The world', story: 'A world of possibility', motif: 'contours',
  primary: '#28564c', accent: '#bd5b39', canvas: '#f5f3ec', wash: '#e3ebe2', glow: '#d8c6a6',
});

export function normalizeDestination(value) {
  return typeof value === 'string' ? value.normalize('NFKD').replace(/[\u0300-\u036f]/g, '').toLowerCase().replace(/[.’']/g, '').replace(/\s+/g, ' ').trim() : '';
}

export function resolveDestinationTheme(destination, catalogue = []) {
  const normalized = normalizeDestination(destination);
  if (!normalized) return DEFAULT_THEME;
  const parts = normalized.split(',').map(part => part.trim());
  const tail = parts.at(-1);
  const exactCountry = catalogue.find(theme => [theme.name, ...(theme.aliases || [])].some(alias => normalizeDestination(alias) === normalized));
  if (exactCountry) return exactCountry;
  const qualifiedCountry = parts.length > 1 && catalogue.find(theme => [theme.name, ...(theme.aliases || [])].some(alias => normalizeDestination(alias) === tail));
  if (qualifiedCountry) return qualifiedCountry;
  if (parts.length > 1) return DEFAULT_THEME;
  return catalogue.find(theme => (theme.cities || []).some(city => normalizeDestination(city) === normalized)) || DEFAULT_THEME;
}

export function themeTokens(theme = DEFAULT_THEME) {
  return {
    '--sea': theme.primary, '--lagoon': theme.primary, '--coral': theme.accent,
    '--sand': theme.canvas, '--foam': theme.canvas, '--theme-wash': theme.wash, '--theme-glow': theme.glow,
    '--ink': '#24332e', '--muted': '#525f58', '--card': '#fffefa', '--line': '#d5ddd4',
    '--shadow': `0 20px 60px ${theme.primary}12`,
  };
}
