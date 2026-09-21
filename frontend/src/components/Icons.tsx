/**
 * Inline SVG icons - no icon font, no external request, nothing for the CSP
 * to allow. 24px grid, 1.75 stroke, currentColor.
 */
import type { SVGProps } from 'react';

type IconProps = SVGProps<SVGSVGElement> & { size?: number };

function Icon({ size = 24, children, ...rest }: IconProps & { children: React.ReactNode }) {
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
      {children}
    </svg>
  );
}

export const HomeIcon = (p: IconProps) => (
  <Icon {...p}>
    <path d="M3.5 10.5 12 3.75l8.5 6.75" />
    <path d="M5.5 9v10.25c0 .41.34.75.75.75H10v-5.5h4V20h3.75c.41 0 .75-.34.75-.75V9" />
  </Icon>
);

export const CalendarIcon = (p: IconProps) => (
  <Icon {...p}>
    <rect x="3.5" y="5" width="17" height="15.5" rx="2.5" />
    <path d="M3.5 9.5h17M8 3v4M16 3v4" />
    <path d="M8 13.5h.01M12 13.5h.01M16 13.5h.01M8 17h.01M12 17h.01" strokeWidth={2.5} />
  </Icon>
);

export const StatsIcon = (p: IconProps) => (
  <Icon {...p}>
    <path d="M12 3.5a8.5 8.5 0 1 0 8.5 8.5H12V3.5Z" />
    <path d="M15 3.8A8.5 8.5 0 0 1 20.2 9H15V3.8Z" />
  </Icon>
);

export const MoreIcon = (p: IconProps) => (
  <Icon {...p}>
    <circle cx="5.5" cy="12" r="1.25" fill="currentColor" />
    <circle cx="12" cy="12" r="1.25" fill="currentColor" />
    <circle cx="18.5" cy="12" r="1.25" fill="currentColor" />
  </Icon>
);

export const PlusIcon = (p: IconProps) => (
  <Icon strokeWidth={2.25} {...p}>
    <path d="M12 5v14M5 12h14" />
  </Icon>
);

export const TransferIcon = (p: IconProps) => (
  <Icon strokeWidth={2.25} {...p}>
    <path d="M4.5 8.5h15M15.5 4.5l4 4-4 4" />
    <path d="M19.5 15.5h-15M8.5 11.5l-4 4 4 4" />
  </Icon>
);

export const CloseIcon = (p: IconProps) => (
  <Icon strokeWidth={2.25} {...p}>
    <path d="M6 6l12 12M18 6 6 18" />
  </Icon>
);

export const BackspaceIcon = (p: IconProps) => (
  <Icon {...p}>
    <path d="M9 5h10.5c.83 0 1.5.67 1.5 1.5v11c0 .83-.67 1.5-1.5 1.5H9l-6-7 6-7Z" />
    <path d="m12 9.5 5 5M17 9.5l-5 5" />
  </Icon>
);

export const ChevronRightIcon = (p: IconProps) => (
  <Icon {...p}>
    <path d="m9.5 6 6 6-6 6" />
  </Icon>
);

export const ShieldIcon = (p: IconProps) => (
  <Icon {...p}>
    <path d="M12 3 5 5.75v5.5c0 4.6 3 8 7 9.75 4-1.75 7-5.15 7-9.75v-5.5L12 3Z" />
    <path d="m9 12 2.2 2.2L15.5 10" />
  </Icon>
);

export const ServerIcon = (p: IconProps) => (
  <Icon {...p}>
    <rect x="3.5" y="4" width="17" height="7" rx="2" />
    <rect x="3.5" y="13" width="17" height="7" rx="2" />
    <path d="M7.5 7.5h.01M7.5 16.5h.01" strokeWidth={2.5} />
  </Icon>
);

export const WalletIcon = (p: IconProps) => (
  <Icon {...p}>
    <path d="M4 7.5c0-1.1.9-2 2-2h11.5v3" />
    <rect x="4" y="8.5" width="16.5" height="11" rx="2.25" />
    <path d="M16 14h.01" strokeWidth={2.75} />
  </Icon>
);

export const TagIcon = (p: IconProps) => (
  <Icon {...p}>
    <path d="M3.5 12.1V4.75c0-.69.56-1.25 1.25-1.25h7.35c.33 0 .65.13.88.37l7.5 7.5c.49.49.49 1.28 0 1.77l-7.35 7.35c-.49.49-1.28.49-1.77 0l-7.5-7.5a1.25 1.25 0 0 1-.36-.89Z" />
    <path d="M8 8h.01" strokeWidth={2.75} />
  </Icon>
);

/** TXN-04 - the add sheet's "Add note". A pencil. */
export const NoteIcon = (p: IconProps) => (
  <Icon {...p}>
    <path d="M4 20.5h3.9l10.4-10.4a2.75 2.75 0 0 0-3.9-3.9L4 16.6v3.9Z" />
    <path d="M13.6 7.1l3.9 3.9" />
  </Icon>
);

/** TXN-16 - "Split": one amount forking into two. */
export const SplitIcon = (p: IconProps) => (
  <Icon {...p}>
    <path d="M3.5 12h4l3.5-5h6" />
    <path d="M11 17h6" />
    <path d="M14.5 4.5 17.5 7l-3 2.5" />
    <path d="M14.5 14.5 17.5 17l-3 2.5" />
  </Icon>
);

/** REC-34 - "Installments": a price cut into monthly parts. */
export const InstallmentsIcon = (p: IconProps) => (
  <Icon {...p}>
    <rect x="3.5" y="5.5" width="17" height="13" rx="2.5" />
    <path d="M3.5 10h17" />
    <path d="M7 14h3M13.5 14h3.5" strokeWidth={2.25} />
  </Icon>
);

/** TXN-22 - "Cashback": money coming back. */
export const CashbackIcon = (p: IconProps) => (
  <Icon {...p}>
    <circle cx="12" cy="12" r="8.5" />
    <path d="M9 15.5 15 8.5" />
    <path d="M9.5 9.5h.01M14.5 14.5h.01" strokeWidth={2.75} />
  </Icon>
);

export const RepeatIcon = (p: IconProps) => (
  <Icon {...p}>
    <path d="M17 3.5 20.5 7 17 10.5" />
    <path d="M3.5 11.5V10a3 3 0 0 1 3-3h14" />
    <path d="M7 20.5 3.5 17 7 13.5" />
    <path d="M20.5 12.5V14a3 3 0 0 1-3 3h-14" />
  </Icon>
);

export const LockIcon = (p: IconProps) => (
  <Icon {...p}>
    <rect x="5" y="10.5" width="14" height="10" rx="2.25" />
    <path d="M8 10.5V7.5a4 4 0 0 1 8 0v3" />
  </Icon>
);

export const LogoutIcon = (p: IconProps) => (
  <Icon {...p}>
    <path d="M14 4.5H6.75c-.69 0-1.25.56-1.25 1.25v12.5c0 .69.56 1.25 1.25 1.25H14" />
    <path d="M10.5 12h10M17 8.5l3.5 3.5-3.5 3.5" />
  </Icon>
);

export const GearIcon = (p: IconProps) => (
  <Icon {...p}>
    <circle cx="12" cy="12" r="3" />
    <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09a1.65 1.65 0 0 0-1.08-1.51 1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09a1.65 1.65 0 0 0 1.51-1.08 1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9c.26.6.85 1 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1Z" />
  </Icon>
);
