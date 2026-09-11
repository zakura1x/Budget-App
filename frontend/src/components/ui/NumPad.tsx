/**
 * The custom numpad - big keys, decimal, backspace, and no OS keyboard.
 *
 * The OS keyboard covers half the screen, differs per device, and on iOS
 * decimal pads have no "done". A fixed pad keeps the category chips and the
 * save button where the thumb expects them (ARCHITECTURE.md 7).
 */
import { BackspaceIcon } from '../Icons';

export type NumPadKey = '0' | '1' | '2' | '3' | '4' | '5' | '6' | '7' | '8' | '9' | '.' | 'back';

const KEYS: NumPadKey[] = ['1', '2', '3', '4', '5', '6', '7', '8', '9', '.', '0', 'back'];

export interface NumPadProps {
  onKey: (key: NumPadKey) => void;
  onLongBackspace?: () => void;
}

export function NumPad({ onKey, onLongBackspace }: NumPadProps) {
  let pressTimer: number | undefined;

  return (
    <div className="grid grid-cols-3 gap-2 select-none" role="group" aria-label="Number pad">
      {KEYS.map((key) => (
        <button
          key={key}
          type="button"
          aria-label={key === 'back' ? 'Delete' : key === '.' ? 'Decimal point' : key}
          onClick={() => onKey(key)}
          onPointerDown={() => {
            if (key === 'back' && onLongBackspace) pressTimer = window.setTimeout(onLongBackspace, 500);
          }}
          onPointerUp={() => window.clearTimeout(pressTimer)}
          onPointerLeave={() => window.clearTimeout(pressTimer)}
          className="num flex h-14 items-center justify-center rounded-2xl bg-surface-2 text-[1.625rem] font-medium text-ink transition active:scale-95 active:bg-line"
        >
          {key === 'back' ? <BackspaceIcon size={26} /> : key}
        </button>
      ))}
    </div>
  );
}
