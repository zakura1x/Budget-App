/**
 * Colour and icon pickers (ACC-05, CAT-04/05).
 *
 * The colour a category is given shows up in the ledger, the pie and the
 * budget bars, so it is stored data rather than theme - which is why these
 * twelve hex values live here and not in theme.css. They are picked to stay
 * apart from each other in both light and dark, and none of them is the
 * accent green: an account should never be mistaken for a control.
 */
import { GLYPH_NAMES, Glyph } from './Glyph';

export const DEFAULT_COLOUR = '#E8734A';

export const PALETTE = [
  DEFAULT_COLOUR, '#F2B544', '#8CA83D', '#3FA37A',
  '#5BB3A6', '#4A90D9', '#5C6BC7', '#8B6FD4',
  '#C86FB0', '#E05A8A', '#D64C40', '#6E7B8B',
];

export function ColourPicker({ value, onChange }: { value: string; onChange: (hex: string) => void }) {
  return (
    <div role="radiogroup" aria-label="Colour" className="flex flex-wrap gap-2.5">
      {PALETTE.map((hex) => {
        const selected = hex.toUpperCase() === value.toUpperCase();
        return (
          <button
            key={hex}
            type="button"
            role="radio"
            aria-checked={selected}
            aria-label={hex}
            onClick={() => onChange(hex)}
            style={{ backgroundColor: hex }}
            className={[
              'h-9 w-9 rounded-full transition',
              selected ? 'ring-2 ring-ink ring-offset-2 ring-offset-surface' : 'active:scale-90',
            ].join(' ')}
          />
        );
      })}
    </div>
  );
}

export function IconPicker({
  value,
  onChange,
  colour,
  names = GLYPH_NAMES,
}: {
  value: string;
  onChange: (name: string) => void;
  colour: string;
  names?: string[];
}) {
  return (
    <div role="radiogroup" aria-label="Icon" className="grid grid-cols-6 gap-2">
      {names.map((name) => {
        const selected = name === value;
        return (
          <button
            key={name}
            type="button"
            role="radio"
            aria-checked={selected}
            aria-label={name.replace(/-/g, ' ')}
            onClick={() => onChange(name)}
            style={selected ? { backgroundColor: colour, color: '#fff' } : undefined}
            className={[
              'flex aspect-square items-center justify-center rounded-xl transition',
              selected ? '' : 'bg-surface-2 text-ink-2 active:bg-line',
            ].join(' ')}
          >
            <Glyph name={name} size={22} />
          </button>
        );
      })}
    </div>
  );
}

/** The rounded tile an account or category is shown by, in its own colour. */
export function GlyphTile({ icon, colour, size = 40 }: { icon: string; colour: string; size?: number }) {
  return (
    <span
      className="flex shrink-0 items-center justify-center rounded-xl"
      style={{ width: size, height: size, backgroundColor: `${colour}1F`, color: colour }}
    >
      <Glyph name={icon} size={Math.round(size * 0.55)} />
    </span>
  );
}
