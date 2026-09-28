/**
 * The custom numpad - big keys, decimal, backspace, and no OS keyboard.
 *
 * The OS keyboard covers half the screen, differs per device, and on iOS
 * decimal pads have no "done". A fixed pad keeps the category chips and the
 * save button where the thumb expects them (ARCHITECTURE.md 7).
 *
 * `decimal={false}` for the PIN pad: the bottom-left key is left empty.
 */
import { BackspaceIcon } from '../Icons';
import { buzz } from '../../lib/haptics';

export type NumPadKey = '0' | '1' | '2' | '3' | '4' | '5' | '6' | '7' | '8' | '9' | '.' | 'back';

const KEYS: NumPadKey[] = ['1', '2', '3', '4', '5', '6', '7', '8', '9', '.', '0', 'back'];

export interface NumPadProps {
  onKey: (key: NumPadKey) => void;
  onLongBackspace?: () => void;
  decimal?: boolean;
  disabled?: boolean;
  /** Round keys - the lock-screen look. */
  variant?: 'amount' | 'pin';
}

export function NumPad({ onKey, onLongBackspace, decimal = true, disabled = false, variant = 'amount' }: NumPadProps) {
  let pressTimer: number | undefined;
  const keyClass =
    variant === 'pin'
      ? 'press num mx-auto flex h-[4.5rem] w-[4.5rem] items-center justify-center rounded-full bg-surface text-[1.75rem] font-semibold text-ink'
      : 'press num flex h-14 items-center justify-center rounded-xl bg-surface text-[1.625rem] font-semibold text-ink';

  return (
    <div className={`grid select-none grid-cols-3 ${variant === 'pin' ? 'gap-x-6 gap-y-4' : 'gap-2'}`} role="group" aria-label="Number pad">
      {KEYS.map((key) =>
        key === '.' && !decimal ? (
          <span key={key} aria-hidden="true" />
        ) : (
          <button
            key={key}
            type="button"
            disabled={disabled}
            aria-label={key === 'back' ? 'Delete' : key === '.' ? 'Decimal point' : key}
            onClick={() => {
              buzz('tap');
              onKey(key);
            }}
            onPointerDown={() => {
              if (key === 'back' && onLongBackspace) pressTimer = window.setTimeout(onLongBackspace, 500);
            }}
            onPointerUp={() => window.clearTimeout(pressTimer)}
            onPointerLeave={() => window.clearTimeout(pressTimer)}
            className={`${keyClass} disabled:opacity-40 ${key === 'back' && variant === 'pin' ? '!bg-transparent !shadow-none' : ''}`}
          >
            {key === 'back' ? <BackspaceIcon size={26} /> : key}
          </button>
        ),
      )}
    </div>
  );
}
