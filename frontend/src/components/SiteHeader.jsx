import { Compass } from 'lucide-react';
export default function SiteHeader() {
  return <header className="site-header"><a className="site-header__brand" href="/" aria-label="Travel planner home"><span className="site-header__mark"><Compass size={24} aria-hidden="true" /></span><h1 className="brand-name">Travel Planner</h1></a></header>;
}
