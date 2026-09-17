/**
 * A money input that reads like money while you type it: ₱ in front and the
 * thousands grouped - "₱185,000.50" - (2026-09-16, user).
 *
 * What the form holds is still the PLAIN typed string - "185000.50", or
 * "-8420" where a minus is allowed - so every sheet keeps sending text exactly
 * as before and nothing becomes a Number (invariant 5). The commas exist only
 * on screen: they are stripped from every keystroke, and the caret is put
 * back after the same count of digits it followed, so typing in the middle of
 * a figure does not throw the cursor to the end when a comma appears.
 */
import { forwardRef, useImperativeHandle, useLayoutEffect, useRef, type InputHTMLAttributes, type ReactNode } from 'react';
import { groupThousands } from '../../lib/money';
import { TextField } from './TextField';

export interface MoneyFieldProps extends Omit<InputHTMLAttributes<HTMLInputElement>, 'value' | 'onChange'> {
  label: string;
  /** The plain typed amount: digits, one point, up to two places; a leading minus when allowed. */
  value: string;
  onChange: (plain: string) => void;
  allowNegative?: boolean;
  hint?: ReactNode;
  error?: string | null;
}

/** Keep what an amount can contain - the same rule the sheets used before. */
export function plainAmount(input: string, allowNegative = false): string {
  const negative = allowNegative && input.trimStart().startsWith('-');
  const [whole = '', ...rest] = input.replace(/[^\d.]/g, '').split('.');
  const body = rest.length ? `${whole}.${rest.join('').slice(0, 2)}` : whole;
  return negative ? `-${body}` : body;
}

/** "-185000.5" -> "-185,000.5": grouped for the eye, never rounded or padded while typing. */
export function groupedAmount(plain: string): string {
  const negative = plain.startsWith('-');
  const body = negative ? plain.slice(1) : plain;
  const [whole = '', frac] = body.split('.');
  const grouped = whole ? groupThousands(whole.replace(/^0+(?=\d)/, '')) : '';
  return `${negative ? '-' : ''}${grouped}${frac !== undefined ? `.${frac}` : ''}`;
}

/** How many characters that are not commas sit before `position` in `text`. */
const significantBefore = (text: string, position: number) => text.slice(0, position).replace(/,/g, '').length;

export const MoneyField = forwardRef<HTMLInputElement, MoneyFieldProps>(function MoneyField(
  { label, value, onChange, allowNegative = false, hint, error, placeholder, ...rest },
  ref,
) {
  const input = useRef<HTMLInputElement>(null);
  useImperativeHandle(ref, () => input.current as HTMLInputElement);
  const caret = useRef<number | null>(null);
  const shown = groupedAmount(value);

  useLayoutEffect(() => {
    const element = input.current;
    if (caret.current === null || !element || document.activeElement !== element) return;
    // Walk the formatted text until as many non-comma characters have passed as the caret followed.
    let seen = 0;
    let position = 0;
    while (position < shown.length && seen < caret.current) {
      if (shown[position] !== ',') seen += 1;
      position += 1;
    }
    element.setSelectionRange(position, position);
    caret.current = null;
  }, [shown]);

  return (
    <TextField
      ref={input}
      label={label}
      value={shown}
      inputMode="decimal"
      autoComplete="off"
      placeholder={placeholder ? groupedAmount(plainAmount(placeholder, allowNegative)) : undefined}
      leading={<span className="-mr-2 pl-3.5 text-body text-ink-3" aria-hidden="true">₱</span>}
      hint={hint}
      error={error}
      onChange={(e) => {
        const typed = e.target.value;
        const plain = plainAmount(typed, allowNegative);
        caret.current = significantBefore(typed, e.target.selectionStart ?? typed.length);
        onChange(plain);
      }}
      {...rest}
    />
  );
});
