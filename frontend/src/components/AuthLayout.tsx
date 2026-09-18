import type { ReactNode } from 'react';
import { ShieldIcon } from './Icons';

/** The frame for every signed-out screen: brand mark, title, content. */
export function AuthLayout({ title, subtitle, children, footer }: {
  title: string;
  subtitle?: ReactNode;
  children: ReactNode;
  footer?: ReactNode;
}) {
  return (
    <div className="mx-auto flex min-h-dvh max-w-app flex-col px-safe pb-safe pt-safe">
      <div className="flex flex-1 flex-col justify-center py-8">
        <div className="mb-7">
          <span className="mb-5 flex h-12 w-12 items-center justify-center rounded-2xl bg-accent text-on-accent shadow-raised">
            <ShieldIcon size={26} />
          </span>
          <h1 className="text-[1.75rem] font-bold leading-tight tracking-tight">{title}</h1>
          {subtitle && <p className="mt-1.5 text-body text-ink-2">{subtitle}</p>}
        </div>
        {children}
      </div>
      {footer && <div className="pb-6 text-center text-footnote text-ink-2">{footer}</div>}
    </div>
  );
}

export function FormError({ message }: { message: string | null }) {
  if (!message) return null;
  return (
    <p role="alert" className="rounded-xl border-2 border-danger bg-danger/10 px-3.5 py-2.5 text-footnote font-medium text-danger">
      {message}
    </p>
  );
}
