import { useId } from 'react';
export default function JourneyArtwork({ className = '', motif = 'mountains' }) {
  const gradient = `journey-sky-${useId().replace(/:/g, '')}`;
  return <svg className={`journey-artwork ${className}`} viewBox="0 0 520 310" fill="none" aria-hidden="true" data-motif={motif}>
    <defs><linearGradient id={gradient} x1="260" y1="0" x2="260" y2="310" gradientUnits="userSpaceOnUse"><stop stopColor="var(--theme-wash, #e3ebe2)"/><stop offset="1" stopColor="var(--sand, #f5f3ec)"/></linearGradient></defs>
    <rect width="520" height="310" rx="24" fill={`url(#${gradient})`} />
    <circle className="journey-artwork__sun" cx="386" cy="83" r="43" fill="var(--theme-glow, #d8c6a6)" />
    <g className="artwork-mountains"><path d="m0 247 142-142 91 93 85-108 202 157v63H0Z" fill="var(--sea, #28564c)" opacity=".13"/><path d="m65 310 135-156 123 129 73-89 124 116H65Z" fill="var(--sea, #28564c)" opacity=".2"/><path d="m118 128 24-23 31 32-20-3-12-11-10 9-13-4Z" fill="var(--card, #fffefa)" opacity=".8"/></g>
    <g className="artwork-waves"><path d="M0 171c90-48 129 54 221 0s164-42 299 5v134H0Z" fill="var(--sea, #28564c)" opacity=".1"/><path d="M0 222c110-60 154 47 273-4s172-21 247 1v91H0Z" fill="var(--sea, #28564c)" opacity=".15"/><path d="M0 266c108-44 183 40 290 0s162-15 230 0" stroke="var(--card, #fffefa)" strokeWidth="2" opacity=".9"/></g>
    <g className="artwork-arches" stroke="var(--sea, #28564c)" strokeWidth="2" opacity=".22"><path d="M66 274V137a61 61 0 0 1 122 0v137M83 274V137a44 44 0 0 1 88 0v137M224 274V157a40 40 0 0 1 80 0v117M237 274V157a27 27 0 0 1 54 0v117"/><path d="M46 276h283M363 274V149h13v125m12 0V131h13v143m12 0V165h13v109"/></g>
    <g className="artwork-forest" fill="var(--sea, #28564c)"><path d="m76 265 49-121 49 121Zm75 9 62-163 62 163Zm160-1 49-132 49 132Z" opacity=".16"/><path d="M125 221v63m88-106v106m147-59v59" stroke="var(--sea, #28564c)" strokeWidth="2" opacity=".35"/></g>
    <path className="journey-artwork__route" d="M61 264c27-68 81-50 123-68 66-29 32-87 111-94 42-4 72 16 110-26" stroke="var(--sea, #28564c)" strokeWidth="2" strokeDasharray="5 7" strokeLinecap="round" opacity=".65"/>
    <circle cx="61" cy="264" r="5" fill="var(--sea, #28564c)"/><circle cx="61" cy="264" r="11" stroke="var(--sea, #28564c)" opacity=".3"/>
    <g transform="translate(407 69) rotate(-28)"><g className="journey-artwork__plane"><path d="m-14 0 28-7-9 26-5-13-14-6Z" fill="var(--sea, #28564c)"/><path d="m0 6 14-13" stroke="var(--card, #fffefa)" strokeWidth="1.5"/></g></g>
    <text x="31" y="38" fill="var(--sea, #28564c)" opacity=".75" fontFamily="system-ui, sans-serif" fontSize="9" letterSpacing="3">A LITTLE FURTHER FROM ORDINARY</text>
  </svg>;
}
