import { forwardRef, useId, type InputHTMLAttributes, type ReactNode } from 'react';

export interface TextFieldProps extends InputHTMLAttributes<HTMLInputElement> {
  label: string;
  hint?: ReactNode;
  error?: string | null;
  trailing?: ReactNode;
  /** Shown inside the field before the text - the ₱ of a MoneyField. */
  leading?: ReactNode;
}

/** A labelled input, 48px tall, 16px text (so iOS never zooms on focus). */
export const TextField = forwardRef<HTMLInputElement, TextFieldProps>(function TextField(
  { label, hint, error, trailing, leading, className = '', id, ...rest },
  ref,
) {
  const autoId = useId();
  const inputId = id ?? autoId;
  const described = error ? `${inputId}-error` : hint ? `${inputId}-hint` : undefined;
  return (
    <div className={className}>
      <label htmlFor={inputId} className="label mb-1.5 block text-ink-2">
        {label}
      </label>
      <div
        className={`flex items-center rounded-xl border-2 bg-surface transition focus-within:shadow-[var(--lift)_var(--lift)_0_0_rgb(var(--c-shadow))] ${
          error ? 'border-danger' : 'border-stroke'
        }`}
      >
        {leading}
        <input
          ref={ref}
          id={inputId}
          aria-invalid={Boolean(error)}
          aria-describedby={described}
          className="min-h-12 w-full min-w-0 flex-1 rounded-xl bg-transparent px-3.5 text-body text-ink outline-none placeholder:text-ink-3"
          {...rest}
        />
        {trailing}
      </div>
      {error ? (
        <p id={`${inputId}-error`} className="mt-1.5 text-footnote text-danger">
          {error}
        </p>
      ) : hint ? (
        <p id={`${inputId}-hint`} className="mt-1.5 text-footnote text-ink-3">
          {hint}
        </p>
      ) : null}
    </div>
  );
});
