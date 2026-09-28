/**
 * PIN entry: a row of dots and the round numpad. Submits by itself when the
 * last digit lands; shakes and clears on a wrong PIN. The digits never touch
 * an <input>, so no browser offers to "save" them.
 */
import { useEffect, useState } from 'react';
import { buzz } from '../lib/haptics';
import { NumPad, type NumPadKey } from './ui/NumPad';

export interface PinPadProps {
  length: number;
  onComplete: (pin: string) => void;
  busy?: boolean;
  /** Bump this number to shake the dots and clear the entry. */
  errorKey?: number;
}

export function PinPad({ length, onComplete, busy = false, errorKey = 0 }: PinPadProps) {
  const [pin, setPin] = useState('');
  const [shaking, setShaking] = useState(false);

  useEffect(() => {
    if (!errorKey) return;
    setShaking(true);
    setPin('');
    buzz('error');
    const t = window.setTimeout(() => setShaking(false), 420);
    return () => window.clearTimeout(t);
  }, [errorKey]);

  const onKey = (key: NumPadKey) => {
    if (busy) return;
    if (key === 'back') return setPin((p) => p.slice(0, -1));
    if (!/^\d$/.test(key) || pin.length >= length) return;
    const next = pin + key;
    setPin(next);
    if (next.length === length) window.setTimeout(() => onComplete(next), 120);
  };

  return (
    <div className="flex flex-col items-center">
      <div
        className={`mb-10 flex gap-4 ${shaking ? 'animate-[shake_0.4s_ease-in-out]' : ''}`}
        role="status"
        aria-label={`${pin.length} of ${length} digits entered`}
      >
        {Array.from({ length }, (_, i) => (
          <span
            key={i}
            className={`h-3.5 w-3.5 rounded-full border-2 transition ${
              i < pin.length ? 'border-accent bg-accent' : 'border-ink-3/60'
            } ${shaking ? '!border-danger !bg-danger' : ''}`}
          />
        ))}
      </div>
      <div className="w-full max-w-[18rem]">
        <NumPad variant="pin" decimal={false} disabled={busy} onKey={onKey} onLongBackspace={() => setPin('')} />
      </div>
    </div>
  );
}
