export default function BrandMark({ className = '' }) {
  return <svg className={`brand-mark ${className}`} viewBox="0 0 64 64" fill="none" aria-hidden="true">
    <path className="brand-mark__orbit" d="M51 18A25 25 0 1 0 54 41" stroke="currentColor" strokeWidth="2" strokeLinecap="round" opacity=".4" />
    <path d="M21 46V18h12c9 0 14 5 14 12s-5 12-14 12h-3" stroke="currentColor" strokeWidth="4" strokeLinecap="round" strokeLinejoin="round" />
    <path d="m32 35 14 13M43 12l11-4-4 11-2-5-5-2Z" fill="currentColor" stroke="currentColor" strokeWidth="2" strokeLinejoin="round" />
    <circle cx="21" cy="46" r="3.5" fill="var(--theme-glow, #d8c6a6)" stroke="currentColor" strokeWidth="2" />
  </svg>;
}
