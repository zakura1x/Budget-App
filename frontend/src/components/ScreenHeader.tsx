import type { ReactNode } from 'react';

/** The large title at the top of a tab - heavy type, a mono caption over it. */
export function ScreenHeader({ title, subtitle, action }: { title: string; subtitle?: ReactNode; action?: ReactNode }) {
  return (
    <header className="flex items-end justify-between gap-3 pb-3 pt-4">
      <div>
        {subtitle && <p className="label text-ink-2">{subtitle}</p>}
        <h1 className="text-[2.125rem] font-black leading-tight tracking-tighter">{title}</h1>
      </div>
      {action}
    </header>
  );
}

/** A note on screens whose real content arrives in a later phase. */
export function PhaseNote({ phase, children }: { phase: string; children: ReactNode }) {
  return (
    <p className="mt-4 rounded-card border-2 border-dashed border-stroke px-4 py-3 text-footnote text-ink-2">
      <span className="font-semibold text-ink">Arrives in Phase {phase}.</span> {children}
    </p>
  );
}
