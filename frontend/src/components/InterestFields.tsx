/**
 * ACC-37 - the interest terms of an account that earns some, inside the
 * account sheet.
 *
 * What it asks for is what a Philippine digital bank's help page states: a
 * rate a year, a higher one above a threshold, and the 20% withholding tax
 * that comes off before the money lands. One tap fills in a bank's own
 * numbers; anything else is typed.
 *
 * No arithmetic happens here on purpose. "About ₱2.84 a day" comes from the
 * server, which works it out with the same code that credits the daily
 * entries, so the figure on this form and the entries in the ledger can never
 * come from two different formulas. A rate typed but not yet saved shows no
 * estimate rather than a guessed one.
 */
import { INTEREST_PRESETS, type Interest, type InterestDraft } from '../lib/accounts';
import { type Category } from '../lib/categories';
import { formatPHP } from '../lib/money';
import { Button } from './ui/Button';
import { TextField } from './ui/TextField';
import { Toggle } from './ui/Toggle';

/** Digits, one dot - a rate is typed like an amount, and never becomes a Number here. */
const cleanRate = (input: string) => {
  const kept = input.replace(/[^\d.]/g, '');
  const dot = kept.indexOf('.');
  return dot === -1 ? kept.slice(0, 6) : `${kept.slice(0, dot)}.${kept.slice(dot + 1).replace(/\./g, '')}`.slice(0, 7);
};

const cleanAmount = (input: string) => {
  const kept = input.replace(/[^\d.]/g, '');
  const dot = kept.indexOf('.');
  return dot === -1 ? kept : `${kept.slice(0, dot)}.${kept.slice(dot + 1).replace(/\./g, '')}`;
};

/** Trailing zeros off a stored rate, so 3.2500 comes back as 3.25 to type against. */
const tidy = (rate: string) => (rate.includes('.') ? rate.replace(/0+$/, '').replace(/\.$/, '') : rate);

export interface InterestFieldsProps {
  /** The draft being edited, or null when the account earns nothing. */
  value: InterestDraft | null;
  onChange: (next: InterestDraft | null) => void;
  /** What the server last returned for this account, for the "about" line. */
  saved: Interest | null;
  /** The income categories interest can land in - fetched once by the sheet. */
  categories: Category[];
}

export function InterestFields({ value, onChange, saved, categories }: InterestFieldsProps) {
  const on = value !== null;
  const bands = value?.bands ?? [];

  const turnOn = () => {
    const preset = INTEREST_PRESETS[0];
    // Interest already lands somewhere for most people: a category called
    // Interest, under Investments in the default set (CAT-07).
    const guess = categories.find((c) => /interest/i.test(c.name)) ?? categories[0];
    onChange({
      bands: preset ? preset.bands.map((b) => ({ ...b })) : [{ up_to: null, rate: '' }],
      tax_rate: preset?.tax_rate ?? '20',
      category_id: guess?.id ?? 0,
    });
  };

  const edit = (changes: Partial<InterestDraft>) => value && onChange({ ...value, ...changes });
  const editBand = (index: number, changes: Partial<{ up_to: string | null; rate: string }>) =>
    edit({ bands: bands.map((band, i) => (i === index ? { ...band, ...changes } : band)) });

  return (
    <div className="space-y-3 rounded-2xl bg-surface-2 p-4">
      <Toggle
        checked={on}
        onChange={(next) => (next ? turnOn() : onChange(null))}
        label="Earns daily interest"
        hint="Your bank works it out on yesterday’s balance and credits it at midnight. The app posts the same entry each day, so the two never drift apart."
      />

      {on && (
        <>
          <div className="flex flex-wrap gap-2">
            {INTEREST_PRESETS.map((preset) => (
              <button
                key={preset.label}
                type="button"
                onClick={() => edit({ bands: preset.bands.map((b) => ({ ...b })), tax_rate: preset.tax_rate })}
                className="rounded-full bg-surface px-3 py-2 text-left text-footnote text-ink-2"
              >
                <span className="font-semibold text-ink">{preset.label}</span>
                <span className="block text-caption text-ink-3">{preset.hint}</span>
              </button>
            ))}
          </div>

          {bands.map((band, index) => {
            const top = index === bands.length - 1;
            return (
              <div key={index} className="flex items-end gap-2">
                <TextField
                  className="w-28"
                  label={index === 0 ? 'Rate a year' : 'Above that'}
                  value={tidy(band.rate)}
                  onChange={(e) => editBand(index, { rate: cleanRate(e.target.value) })}
                  inputMode="decimal"
                  placeholder="3.25"
                  trailing={<span className="pr-3.5 text-footnote text-ink-3">%</span>}
                />
                {top ? (
                  <p className="min-h-12 flex-1 pb-3.5 text-footnote text-ink-3">
                    {bands.length === 1 ? 'on the whole balance' : 'on everything above'}
                  </p>
                ) : (
                  <TextField
                    className="flex-1"
                    label="Up to"
                    value={band.up_to ?? ''}
                    onChange={(e) => editBand(index, { up_to: cleanAmount(e.target.value) || null })}
                    inputMode="decimal"
                    placeholder="1,000,000.00"
                  />
                )}
                {bands.length > 1 && (
                  <button
                    type="button"
                    onClick={() => edit({ bands: bands.filter((_, i) => i !== index) })}
                    aria-label={`Remove band ${index + 1}`}
                    className="min-h-12 px-2 pb-1 text-footnote text-ink-3"
                  >
                    Remove
                  </button>
                )}
              </div>
            );
          })}

          {bands.length < 5 && (
            <Button
              variant="ghost"
              onClick={() =>
                edit({
                  // The new band takes the top slot; the one below it needs the ceiling.
                  bands: [...bands.slice(0, -1), { ...bands[bands.length - 1]!, up_to: '' }, { up_to: null, rate: '' }],
                })
              }
            >
              Add a higher rate
            </Button>
          )}

          <TextField
            label="Withholding tax"
            value={tidy(value.tax_rate ?? '20')}
            onChange={(e) => edit({ tax_rate: cleanRate(e.target.value) })}
            inputMode="decimal"
            placeholder="20"
            trailing={<span className="pr-3.5 text-footnote text-ink-3">%</span>}
            hint="Taken off before the money lands — 20% in the Philippines. What the app credits is what your bank deposits."
          />

          <div>
            <label htmlFor="interest-category" className="mb-1.5 block text-footnote font-semibold text-ink-2">
              Lands in
            </label>
            <select
              id="interest-category"
              value={value.category_id || ''}
              onChange={(e) => edit({ category_id: Number(e.target.value) })}
              className="min-h-12 w-full rounded-xl border border-line bg-surface px-3 text-body"
            >
              <option value="">Choose a category…</option>
              {categories.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.parent_id ? `  ${c.name}` : c.name}
                </option>
              ))}
            </select>
            <p className="mt-1.5 text-footnote text-ink-3">
              {categories.length === 0
                ? 'Add an income category first, under More → Categories.'
                : 'Every day’s interest is filed here, so it shows up as income in your stats.'}
            </p>
          </div>

          {!saved && (
            <TextField
              label="Earning since"
              type="date"
              value={value.started ?? ''}
              onChange={(e) => edit({ started: e.target.value || undefined })}
              hint="Leave empty to start today. An earlier date fills in the days since, up to a year back."
            />
          )}

          {saved && (
            <p className="text-footnote text-ink-2">
              About <span className="num font-semibold">{formatPHP(saved.per_day)}</span> a day at this balance —{' '}
              <span className="num">{formatPHP(saved.per_year)}</span> a year. Credited up to {saved.credited_through}.
            </p>
          )}
        </>
      )}
    </div>
  );
}
