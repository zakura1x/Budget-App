/**
 * The palette choice (UX-05, the neo-brutalist redesign of 2026-09-18).
 *
 * Each tile is drawn IN its own palette - it carries data-palette, which
 * theme.css honours on any element - so it shows the real ground, tile and
 * accent in whichever light or dark is on, with no colour written here.
 */
import type { Palette } from '../lib/budgets';

const PALETTES: { value: Palette; label: string }[] = [
  { value: 'classic', label: 'Classic' },
  { value: 'candy', label: 'Candy' },
  { value: 'lime', label: 'Lime' },
  { value: 'mono', label: 'Mono' },
];

export function PalettePicker({ value, onChange }: { value: Palette; onChange: (value: Palette) => void }) {
  const move = (delta: number) => {
    const at = (PALETTES.findIndex((p) => p.value === value) + delta + PALETTES.length) % PALETTES.length;
    const next = PALETTES[at];
    if (next) onChange(next.value);
  };
  return (
    <div>
      <p className="label mb-2 text-ink-2">Palette</p>
      <div role="radiogroup" aria-label="Palette" className="grid grid-cols-4 gap-2.5">
        {PALETTES.map((p) => {
          const selected = p.value === value;
          return (
            <button
              key={p.value}
              type="button"
              role="radio"
              aria-checked={selected}
              tabIndex={selected ? 0 : -1}
              onClick={() => onChange(p.value)}
              onKeyDown={(e) => {
                if (e.key === 'ArrowRight') move(1);
                if (e.key === 'ArrowLeft') move(-1);
              }}
              data-palette={p.value}
              className={`flex flex-col gap-1.5 rounded-lg bg-bg p-1.5 text-ink ${selected ? 'shadow-card' : 'shadow-edge'}`}
            >
              <span className="flex h-9 items-end gap-1 rounded bg-surface p-1 shadow-edge" aria-hidden="true">
                <span className="h-full w-1/2 rounded-sm bg-accent" />
                <span className="h-2/3 w-1/4 rounded-sm bg-highlight" />
                <span className="h-1/3 w-1/4 rounded-sm bg-ink" />
              </span>
              <span className={`font-mono text-[0.625rem] font-bold uppercase tracking-wide ${selected ? 'underline underline-offset-2' : ''}`}>
                {p.label}
              </span>
            </button>
          );
        })}
      </div>
    </div>
  );
}
