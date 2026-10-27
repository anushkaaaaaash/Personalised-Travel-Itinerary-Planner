import BrandMark from './BrandMark.jsx';
import { Link, useInRouterContext } from 'react-router-dom';
import { useTheme } from '../themes/DestinationTheme.jsx';
export default function SiteHeader({ onNavigate,showSavedTrips=false }) {
  const { theme } = useTheme();
  const inRouter=useInRouterContext();
  return <header className="site-header">
    <a className="site-header__brand" href="/" aria-label="Roamora home" onClick={onNavigate}>
      <span className="site-header__mark"><BrandMark /></span>
      <span><span className="brand-name">Roamora<span className="brand-dot">.</span></span><span className="brand-tagline">A little wonder. A plan of your own.</span></span>
    </a>
    <div className="site-header__actions"><span className="header-passport"><span className="header-passport__dot" aria-hidden="true" />{theme.code === 'WORLD' ? 'Made for your kind of journey' : `${theme.name}, in full colour`}</span>{showSavedTrips&&inRouter&&<Link className="site-header__saved" to="/saved-trips" onClick={onNavigate}>Saved trips</Link>}</div>
  </header>;
}
