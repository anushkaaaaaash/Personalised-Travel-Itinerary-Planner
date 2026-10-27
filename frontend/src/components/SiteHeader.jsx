import BrandMark from './BrandMark.jsx';
import { useTheme } from '../themes/DestinationTheme.jsx';
export default function SiteHeader({ onNavigate }) {
  const { theme } = useTheme();
  return <header className="site-header">
    <a className="site-header__brand" href="/" aria-label="Roamora home" onClick={onNavigate}>
      <span className="site-header__mark"><BrandMark /></span>
      <span><span className="brand-name">Roamora<span className="brand-dot">.</span></span><span className="brand-tagline">A little wonder. A plan of your own.</span></span>
    </a>
    <span className="header-passport"><span className="header-passport__dot" aria-hidden="true" />{theme.code === 'WORLD' ? 'Made for your kind of journey' : `${theme.name}, in full colour`}</span>
  </header>;
}
