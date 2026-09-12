import { useId, type ReactNode } from 'react';

export interface ToggleProps {
  checked: boolean;
  onChange: (value: boolean) => void;
  label: string;
  hint?: ReactNode;
  disabled?: boolean;
}

/** An iOS-style switch on a list row. The whole row is the target, not the switch. */
export function Toggle({ checked, onChange, label, hint, disabled }: ToggleProps) {
  const id = useId();
  return (
    <label
      htmlFor={id}
      className={`flex min-h-tap items-center gap-3 py-1 ${disabled ? 'opacity-40' : 'cursor-pointer'}`}
    >
      <span className="min-w-0 flex-1">
        <span className="block text-body">{label}</span>
        {hint && <span className="mt-0.5 block text-footnote text-ink-2">{hint}</span>}
      </span>
      <input
        id={id}
        type="checkbox"
        role="switch"
        className="peer sr-only"
        checked={checked}
        disabled={disabled}
        onChange={(e) => onChange(e.target.checked)}
      />
      <span
        aria-hidden="true"
        className={[
          'relative h-7 w-12 shrink-0 rounded-full transition-colors duration-200',
          'peer-focus-visible:ring-2 peer-focus-visible:ring-accent peer-focus-visible:ring-offset-2',
          checked ? 'bg-accent' : 'bg-line',
        ].join(' ')}
      >
        <span
          className={`absolute top-0.5 h-6 w-6 rounded-full bg-white shadow transition-transform duration-200 ease-ios ${
            checked ? 'translate-x-[1.375rem]' : 'translate-x-0.5'
          }`}
        />
      </span>
    </label>
  );
}
