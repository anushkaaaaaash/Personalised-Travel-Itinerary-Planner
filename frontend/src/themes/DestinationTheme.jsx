import { createContext, useContext, useEffect, useMemo, useState } from 'react';
import { DEFAULT_THEME, resolveDestinationTheme, themeTokens } from './themeTokens.js';

let cataloguePromise;
export function loadCountryThemes() {
  if (!cataloguePromise) cataloguePromise = import('./countryThemes.js').then(module => module.COUNTRY_THEMES).catch(error => { cataloguePromise = null; throw error; });
  return cataloguePromise;
}

const ThemeContext = createContext({ theme: DEFAULT_THEME, countries: [], setDestination: () => {} });

export function DestinationThemeProvider({ children, loadCatalogue = loadCountryThemes }) {
  const [destination, setDestination] = useState('');
  const [countries, setCountries] = useState([]);
  useEffect(() => {
    let active = true;
    const load = () => { void loadCatalogue().then(value => { if (active) setCountries(value); }).catch(() => {}); };
    if (typeof window === 'undefined') return undefined;
    const idle = typeof window.requestIdleCallback === 'function';
    const handle = idle ? window.requestIdleCallback(load, { timeout: 1200 }) : window.setTimeout(load, 120);
    return () => { active = false; if (idle) window.cancelIdleCallback(handle); else window.clearTimeout(handle); };
  }, [loadCatalogue]);
  useEffect(() => {
    if (!destination || countries.length) return undefined;
    let active = true;
    void loadCatalogue().then(value => { if (active) setCountries(value); }).catch(() => {});
    return () => { active = false; };
  }, [destination, countries.length, loadCatalogue]);
  const theme = useMemo(() => resolveDestinationTheme(destination, countries), [destination, countries]);
  useEffect(() => {
    if (typeof document === 'undefined') return undefined;
    const root = document.documentElement;
    const tokens = themeTokens(theme);
    const previous = Object.fromEntries(Object.keys(tokens).map(key => [key, root.style.getPropertyValue(key)]));
    const priorTheme = root.dataset.destinationTheme;
    const priorMotif = root.dataset.themeMotif;
    Object.entries(tokens).forEach(([key, value]) => root.style.setProperty(key, value));
    root.dataset.destinationTheme = theme.code;
    root.dataset.themeMotif = theme.motif;
    const meta = document.querySelector('meta[name="theme-color"]');
    const priorMeta = meta?.getAttribute('content');
    meta?.setAttribute('content', theme.canvas);
    return () => {
      Object.entries(previous).forEach(([key, value]) => value ? root.style.setProperty(key, value) : root.style.removeProperty(key));
      if (priorTheme) root.dataset.destinationTheme = priorTheme; else delete root.dataset.destinationTheme;
      if (priorMotif) root.dataset.themeMotif = priorMotif; else delete root.dataset.themeMotif;
      if (meta && priorMeta) meta.setAttribute('content', priorMeta);
    };
  }, [theme]);
  const value = useMemo(() => ({ theme, countries, setDestination }), [theme, countries]);
  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useDestinationTheme(destination) {
  const context = useContext(ThemeContext);
  useEffect(() => {
    context.setDestination(destination || '');
    return () => context.setDestination('');
  }, [destination, context.setDestination]);
  return context;
}

export function useTheme() { return useContext(ThemeContext); }
