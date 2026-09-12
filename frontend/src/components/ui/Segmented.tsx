export interface SegmentedProps<T extends string> {
  options: { value: T; label: string }[];
  value: T;
  onChange: (value: T) => void;
  label: string;
}

/** Two or three mutually exclusive views - expense/income, and later the
 *  transaction types. Arrow keys move between them, as a tablist should. */
export function Segmented<T extends string>({ options, value, onChange, label }: SegmentedProps<T>) {
  const move = (delta: number) => {
    const at = (options.findIndex((o) => o.value === value) + delta + options.length) % options.length;
    const next = options[at];
    if (next) onChange(next.value);
  };
  return (
    <div role="tablist" aria-label={label} className="flex gap-1 rounded-2xl bg-surface-2 p-1">
      {options.map((option) => {
        const selected = option.value === value;
        return (
          <button
            key={option.value}
            type="button"
            role="tab"
            aria-selected={selected}
            tabIndex={selected ? 0 : -1}
            onClick={() => onChange(option.value)}
            onKeyDown={(e) => {
              if (e.key === 'ArrowRight') move(1);
              if (e.key === 'ArrowLeft') move(-1);
            }}
            className={[
              'min-h-tap flex-1 rounded-xl px-3 text-body font-semibold transition',
              selected ? 'bg-surface text-ink shadow-card' : 'text-ink-2 active:bg-line',
            ].join(' ')}
          >
            {option.label}
          </button>
        );
      })}
    </div>
  );
}
