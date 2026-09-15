/**
 * The glyph set accounts and categories are drawn with.
 *
 * The server stores an icon as a short slug ("credit-card", "restaurant") and
 * knows nothing about how it looks - so the whole registry lives here, inline,
 * on the same 24px grid and 1.75 stroke as Icons.tsx. No icon font, no
 * external request, nothing for the CSP to allow (SEC-29 keeps the origin
 * clean of anything the API sent, and this never touches the API at all).
 *
 * A slug that is not in the registry falls back to the tag, so an icon we
 * retire later never leaves a hole in someone's category list.
 */
import type { ReactElement, SVGProps } from 'react';

type Props = SVGProps<SVGSVGElement> & { name: string; size?: number };

const GLYPHS: Record<string, ReactElement> = {
  // --- accounts
  cash: (
    <>
      <rect x="2.5" y="6" width="19" height="12" rx="2.5" />
      <circle cx="12" cy="12" r="2.75" />
      <path d="M6 9.5h.01M18 14.5h.01" strokeWidth={2.5} />
    </>
  ),
  card: (
    <>
      <rect x="2.5" y="5.5" width="19" height="13" rx="2.5" />
      <path d="M2.5 10h19M6 14.5h4" />
    </>
  ),
  'credit-card': (
    <>
      <rect x="2.5" y="5.5" width="19" height="13" rx="2.5" />
      <path d="M2.5 9.5h19M6 14.5h3.5" />
      <rect x="15" y="13" width="4" height="3" rx="1" />
    </>
  ),
  'piggy-bank': (
    <>
      <path d="M4 12.5c0-3.6 3.4-6 8-6s8 2.4 8 6c0 2-1 3.5-2.5 4.5V19a1 1 0 0 1-1 1h-1.5a1 1 0 0 1-1-1v-.6a13 13 0 0 1-4 0V19a1 1 0 0 1-1 1H7.5a1 1 0 0 1-1-1v-2A5.8 5.8 0 0 1 4 12.5Z" />
      <path d="M4.2 11.2 2.8 9.5M15 7.2l1.3-2.5" />
      <path d="M15.5 12h.01" strokeWidth={2.5} />
    </>
  ),
  chart: (
    <>
      <path d="M4 20V4M4 20h16" />
      <path d="M8 16.5V12M12.5 16.5V7.5M17 16.5v-6" />
    </>
  ),
  wallet: (
    <>
      <path d="M3.5 7.5A2.5 2.5 0 0 1 6 5h11.5A1.5 1.5 0 0 1 19 6.5V8" />
      <rect x="3.5" y="7.5" width="17" height="11.5" rx="2.5" />
      <path d="M16.5 13.5h.01" strokeWidth={2.5} />
    </>
  ),
  bank: (
    <>
      <path d="M3.5 9.5 12 4.5l8.5 5" />
      <path d="M5.5 10.5v7M10 10.5v7M14 10.5v7M18.5 10.5v7M3.5 19.5h17" />
    </>
  ),

  // --- categories
  restaurant: (
    <>
      <path d="M7 3.5v7.5a2.5 2.5 0 0 0 5 0V3.5M9.5 11v9.5" />
      <path d="M17.5 3.5c-1.4 1.3-2 3-2 5s.7 2.8 2 3v9" />
    </>
  ),
  cart: (
    <>
      <path d="M3 4.5h2.2l2.3 10.2a1.5 1.5 0 0 0 1.5 1.2h7.6a1.5 1.5 0 0 0 1.5-1.1L20 8H6" />
      <circle cx="9.5" cy="19.5" r="1.4" />
      <circle cx="17" cy="19.5" r="1.4" />
    </>
  ),
  coffee: (
    <>
      <path d="M4.5 8.5h12v6a4.5 4.5 0 0 1-4.5 4.5H9a4.5 4.5 0 0 1-4.5-4.5Z" />
      <path d="M16.5 10.5H19a2 2 0 0 1 0 4h-2.5" />
      <path d="M8 3v2.5M12 3v2.5" />
    </>
  ),
  car: (
    <>
      <path d="M4 15.5v3h2.5v-3M17.5 15.5v3H20v-3" />
      <path d="M3.5 15.5v-3l1.8-4.3A2 2 0 0 1 7.1 7h9.8a2 2 0 0 1 1.8 1.2l1.8 4.3v3Z" />
      <path d="M3.5 12.5h17M7 15.5h.01M17 15.5h.01" strokeWidth={2.5} />
    </>
  ),
  fuel: (
    <>
      <path d="M4.5 20V5.5A1.5 1.5 0 0 1 6 4h6a1.5 1.5 0 0 1 1.5 1.5V20M3 20h12" />
      <path d="M6.5 8.5h6.5" />
      <path d="M13.5 9.5h3a1.5 1.5 0 0 1 1.5 1.5v5a1.5 1.5 0 0 0 3 0V9l-2-2.5" />
    </>
  ),
  bolt: <path d="M13 2.5 5 13.5h6L10.5 21.5 19 10.5h-6Z" />,
  home: (
    <>
      <path d="M3.5 10.5 12 3.75l8.5 6.75" />
      <path d="M5.5 9v10.25c0 .41.34.75.75.75H10v-5.5h4V20h3.75c.41 0 .75-.34.75-.75V9" />
    </>
  ),
  bag: (
    <>
      <path d="M5 7.5h14l-1 12a1.5 1.5 0 0 1-1.5 1.4h-11A1.5 1.5 0 0 1 6 19.5Z" />
      <path d="M8.5 9.5V6.5a3.5 3.5 0 0 1 7 0v3" />
    </>
  ),
  heart: (
    <path d="M12 20s-7.5-4.4-7.5-9.4A4.1 4.1 0 0 1 12 8a4.1 4.1 0 0 1 7.5 2.6C19.5 15.6 12 20 12 20Z" />
  ),
  play: (
    <>
      <circle cx="12" cy="12" r="8.5" />
      <path d="M10 8.75 16 12l-6 3.25Z" />
    </>
  ),
  book: (
    <>
      <path d="M4 5a1.5 1.5 0 0 1 1.5-1.5H10A2.5 2.5 0 0 1 12 5v14a2.5 2.5 0 0 0-2-1H5.5A1.5 1.5 0 0 1 4 16.5Z" />
      <path d="M20 5a1.5 1.5 0 0 0-1.5-1.5H14A2.5 2.5 0 0 0 12 5v14a2.5 2.5 0 0 1 2-1h4.5a1.5 1.5 0 0 0 1.5-1.5Z" />
    </>
  ),
  gift: (
    <>
      <rect x="3.5" y="9" width="17" height="4" rx="1" />
      <path d="M5 13v6.5a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V13M12 9v11.5" />
      <path d="M12 9S10.5 3.5 8 3.5a2.25 2.25 0 0 0 0 4.5h8a2.25 2.25 0 0 0 0-4.5C13.5 3.5 12 9 12 9Z" />
    </>
  ),
  plane: <path d="M10.5 3.5a1.5 1.5 0 0 1 3 0v6l7 4v2.5l-7-2v4l2 1.5V21l-3.5-1-3.5 1v-1.5l2-1.5v-4l-7 2V13l7-4Z" />,
  tag: (
    <>
      <path d="M11 3.5H20.5V13L12 21.5 3.5 13Z" />
      <path d="M16.5 7.5h.01" strokeWidth={2.5} />
    </>
  ),
  phone: (
    <>
      <rect x="6.5" y="2.5" width="11" height="19" rx="2.5" />
      <path d="M10.5 5.5h3M12 18.5h.01" strokeWidth={2.5} />
    </>
  ),
  briefcase: (
    <>
      <rect x="2.5" y="7" width="19" height="13" rx="2.5" />
      <path d="M8.5 7V5.5A2 2 0 0 1 10.5 3.5h3a2 2 0 0 1 2 2V7M2.5 12.5h19" />
    </>
  ),
  laptop: (
    <>
      <rect x="4.5" y="4.5" width="15" height="11" rx="1.5" />
      <path d="M2 18.5h20" />
    </>
  ),
  undo: (
    <>
      <path d="M4 9.5h7a5.5 5.5 0 1 1 0 11H7" />
      <path d="m7.5 5.5-3.5 4 3.5 4" />
    </>
  ),
  star: <path d="m12 3.5 2.6 5.4 5.9.8-4.3 4.2 1 5.9-5.2-2.8-5.2 2.8 1-5.9L3.5 9.7l5.9-.8Z" />,
  tools: (
    <>
      <path d="M14.5 3.5a4.5 4.5 0 0 0-4 6.6L3.5 17v3.5H7l6.9-7a4.5 4.5 0 0 0 5.6-6.3l-2.6 2.6-2.4-.6-.6-2.4 2.6-2.6a4.5 4.5 0 0 0-2-.7Z" />
    </>
  ),
  pet: (
    <>
      <circle cx="7" cy="8" r="1.9" />
      <circle cx="12" cy="6" r="2" />
      <circle cx="17" cy="8" r="1.9" />
      <path d="M12 10.5c2.8 0 5 2.3 5 5a3.5 3.5 0 0 1-3.5 3.5h-3A3.5 3.5 0 0 1 7 15.5c0-2.7 2.2-5 5-5Z" />
    </>
  ),
  ticket: (
    <>
      <path d="M3.5 8.5A1.5 1.5 0 0 1 5 7h14a1.5 1.5 0 0 1 1.5 1.5V10a2 2 0 0 0 0 4v1.5A1.5 1.5 0 0 1 19 17H5a1.5 1.5 0 0 1-1.5-1.5V14a2 2 0 0 0 0-4Z" />
      <path d="M13.5 7v10" strokeDasharray="2 2" />
    </>
  ),
  dots: <path d="M6 12h.01M12 12h.01M18 12h.01" strokeWidth={3} />,
  // Account kinds (ACC-31..33, 2026-09-15)
  globe: (
    <>
      <circle cx="12" cy="12" r="8.5" />
      <path d="M3.5 12h17M12 3.5c2.5 2.6 3.5 5.4 3.5 8.5s-1 5.9-3.5 8.5c-2.5-2.6-3.5-5.4-3.5-8.5s1-5.9 3.5-8.5Z" />
    </>
  ),
  'hand-coin': (
    <>
      <circle cx="15" cy="6.5" r="3" />
      <path d="M2.5 14h3l3 1.5h4.5a1.5 1.5 0 0 1 0 3H9" />
      <path d="M5.5 20.5 9 19h6l5.2-4.3a1.5 1.5 0 0 0-2-2.2L14.5 15" />
    </>
  ),
  'hand-owe': (
    <>
      <path d="M15 2.5v7M12.5 7 15 9.5 17.5 7" />
      <path d="M2.5 14h3l3 1.5h4.5a1.5 1.5 0 0 1 0 3H9" />
      <path d="M5.5 20.5 9 19h6l5.2-4.3a1.5 1.5 0 0 0-2-2.2L14.5 15" />
    </>
  ),
  contract: (
    <>
      <path d="M6 3.5h8.5L18 7v13.5H6Z" />
      <path d="M14.5 3.5V7H18M9 12h6M9 15.5h6" />
    </>
  ),
  trend: (
    <>
      <path d="M3.5 17 9 11.5l3.5 3.5 8-8" />
      <path d="M15 7h5.5v5.5" />
    </>
  ),
  crypto: (
    <>
      <circle cx="12" cy="12" r="8.5" />
      <path d="M10 7.5v9M10 8h3a2 2 0 0 1 0 4h-3M10 12h3.5a2.2 2.2 0 0 1 0 4.4H10M11.5 6v1.5M11.5 16.5V18" />
    </>
  ),
  coins: (
    <>
      <ellipse cx="9" cy="7" rx="5.5" ry="2.5" />
      <path d="M3.5 7v4c0 1.4 2.5 2.5 5.5 2.5s5.5-1.1 5.5-2.5V7" />
      <path d="M9.5 13.5V17c0 1.4 2.5 2.5 5.5 2.5s5.5-1.1 5.5-2.5v-4c0-1.4-2.5-2.5-5.5-2.5" />
    </>
  ),
  badge: (
    <>
      <rect x="2.5" y="6" width="19" height="12" rx="2.5" />
      <path d="m6 9.5 1.5 5 1.5-5M12 9.5v5M15 14.5v-5h1.8a1.6 1.6 0 0 1 0 3.2H15" />
    </>
  ),
  bus: (
    <>
      <rect x="5" y="3.5" width="14" height="14" rx="2.5" />
      <path d="M5 11h14M8 20.5v-3M16 20.5v-3" />
      <path d="M8.5 14.5h.01M15.5 14.5h.01" strokeWidth={2.5} />
    </>
  ),
  graduation: (
    <>
      <path d="M2.5 9 12 4.5 21.5 9 12 13.5Z" />
      <path d="M6.5 11v4.5c0 1.5 2.5 3 5.5 3s5.5-1.5 5.5-3V11M21.5 9v5" />
    </>
  ),
  'id-card': (
    <>
      <rect x="2.5" y="5" width="19" height="14" rx="2.5" />
      <circle cx="8.5" cy="10.5" r="2" />
      <path d="M5.5 16c.5-1.5 1.7-2.2 3-2.2s2.5.7 3 2.2M14 10h4.5M14 13.5h3" />
    </>
  ),
};

/** Every slug the picker offers, in the order it shows them. */
export const GLYPH_NAMES = Object.keys(GLYPHS);

export const ACCOUNT_GLYPHS = [
  'cash', 'card', 'credit-card', 'piggy-bank', 'chart', 'wallet', 'bank', 'globe', 'hand-coin', 'hand-owe',
  'contract', 'trend', 'crypto', 'home', 'coins', 'badge', 'bus', 'graduation', 'id-card',
];

export function Glyph({ name, size = 24, ...rest }: Props) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.75}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      {...rest}
    >
      {GLYPHS[name] ?? GLYPHS.tag}
    </svg>
  );
}
