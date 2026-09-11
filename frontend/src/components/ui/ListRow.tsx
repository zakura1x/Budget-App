import type { ReactNode } from 'react';
import { ChevronRightIcon } from '../Icons';

export interface ListRowProps {
  icon?: ReactNode;
  iconTone?: string;
  title: ReactNode;
  subtitle?: ReactNode;
  trailing?: ReactNode;
  chevron?: boolean;
  onClick?: () => void;
}

/** One row of an iOS-style grouped list. 56px tall - comfortably tappable. */
export function ListRow({ icon, iconTone = 'bg-accent-soft text-accent', title, subtitle, trailing, chevron, onClick }: ListRowProps) {
  const Tag = onClick ? 'button' : 'div';
  return (
    <Tag
      {...(onClick ? { type: 'button' as const, onClick } : {})}
      className="flex min-h-14 w-full items-center gap-3 px-4 py-2.5 text-left transition active:bg-surface-2"
    >
      {icon && <span className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-xl ${iconTone}`}>{icon}</span>}
      <span className="min-w-0 flex-1">
        <span className="block truncate text-body">{title}</span>
        {subtitle && <span className="block truncate text-footnote text-ink-2">{subtitle}</span>}
      </span>
      {trailing && <span className="num shrink-0 text-body text-ink-2">{trailing}</span>}
      {chevron && <ChevronRightIcon size={18} className="shrink-0 text-ink-3" />}
    </Tag>
  );
}

/** A group of rows on one card, divided by hairlines. */
export function ListGroup({ children }: { children: ReactNode }) {
  return <div className="divide-y divide-line overflow-hidden rounded-card bg-surface shadow-card">{children}</div>;
}
