import type { HTMLAttributes } from 'react';

export interface CardProps extends HTMLAttributes<HTMLDivElement> {
  padded?: boolean;
}

export function Card({ padded = true, className = '', ...rest }: CardProps) {
  return <div className={`rounded-card bg-surface shadow-card ${padded ? 'p-4' : ''} ${className}`} {...rest} />;
}

export function SectionTitle({ children }: { children: React.ReactNode }) {
  return <h2 className="label px-1 pb-2 pt-6 text-ink">{children}</h2>;
}
