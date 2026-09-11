import type { ReactNode } from 'react';

/** Large iOS-style title at the top of a tab. */
export function ScreenHeader({ title, subtitle, action }: { title: string; subtitle?: ReactNode; action?: ReactNode }) {
  return (
    <header className="flex items-end justify-between gap-3 pb-3 pt-4">
      <div>
        {subtitle && <p className="text-footnote font-medium text-ink-2">{subtitle}</p>}
        <h1 className="text-[2rem] font-bold leading-tight tracking-tight">{title}</h1>
      </div>
      {action}
    </header>
  );
}

/** A note on screens whose real content arrives in a later phase. */
export function PhaseNote({ phase, children }: { phase: string; children: ReactNode }) {
  return (
    <p className="mt-4 rounded-2xl border border-dashed border-line px-4 py-3 text-footnote text-ink-2">
      <span className="font-semibold text-ink">Arrives in Phase {phase}.</span> {children}
    </p>
  );
}
