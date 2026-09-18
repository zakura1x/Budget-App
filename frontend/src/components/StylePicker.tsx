/**
 * Colour and icon pickers (ACC-05, CAT-04/05).
 *
 * The colour a category is given shows up in the ledger, the pie and the
 * budget bars, so it is stored data rather than theme - which is why these
 * twelve hex values live here and not in theme.css. They are stored per
 * account and category, so changing the palette never rewrites them.
 *
 * The neo-brutalist set (2026-09-18, user: "replace them"): bright, flat
 * fills that carry a BLACK glyph and a black outline in every palette, light
 * or dark - a colour is the tile's fill now, not a tint behind a coloured
 * glyph. The order keeps the old roles (5 blue, 6 indigo, 8 pink, 3 green),
 * which TransactionSheet's presets pick by index. Colours saved before keep
 * working; they are only no longer offered.
 */
import { GLYPH_NAMES, Glyph } from './Glyph';

export const DEFAULT_COLOUR = '#FF7A59';

export const PALETTE = [
  DEFAULT_COLOUR, '#FFC53D', '#C6F04D', '#5FD68A',
  '#4FD1C5', '#5AB8FF', '#8C9EFF', '#B98CFF',
  '#FF8AD8', '#FF6B9A', '#FF5C5C', '#AEB6C2',
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
              'h-9 w-9 rounded-lg shadow-edge transition',
              selected ? 'ring-2 ring-stroke ring-offset-4 ring-offset-surface' : 'active:scale-90',
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
            style={selected ? { backgroundColor: colour } : undefined}
            className={[
              'flex aspect-square items-center justify-center rounded-lg shadow-edge transition',
              selected ? 'text-black' : 'bg-surface text-ink-2 active:bg-surface-2',
            ].join(' ')}
          >
            <Glyph name={name} size={22} />
          </button>
        );
      })}
    </div>
  );
}

/** The outlined tile an account or category is shown by, filled with its own colour. */
export function GlyphTile({ icon, colour, size = 40 }: { icon: string; colour: string; size?: number }) {
  return (
    <span
      className="flex shrink-0 items-center justify-center rounded-lg text-black shadow-edge"
      style={{ width: size, height: size, backgroundColor: colour }}
    >
      <Glyph name={icon} size={Math.round(size * 0.55)} />
    </span>
  );
}
