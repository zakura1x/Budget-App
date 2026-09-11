/**
 * The add-transaction sheet - Phase 1 shell.
 *
 * Opens with the amount showing and the numpad up, as the finished one will.
 * Categories, account, date and saving arrive in Phase 4; the typed amount is
 * a decimal string from the first keypress to the last, never a float.
 */
import { useCallback, useState } from 'react';
import { applyAmountKey, formatPHP, toDecimalString } from '../lib/money';
import { useUiStore } from '../stores/uiStore';
import { Button } from './ui/Button';
import { NumPad, type NumPadKey } from './ui/NumPad';
import { Sheet } from './ui/Sheet';

type Kind = 'expense' | 'income' | 'transfer';

export function TransactionSheet() {
  const open = useUiStore((s) => s.addSheetOpen);
  const close = useUiStore((s) => s.closeAddSheet);
  const [typed, setTyped] = useState('0');
  const [kind, setKind] = useState<Kind>('expense');

  const onClose = useCallback(() => {
    close();
    setTyped('0');
  }, [close]);

  const display = formatPHP(toDecimalString(typed));

  return (
    <Sheet open={open} onClose={onClose} title="New transaction">
      <div className="mb-3 grid grid-cols-3 rounded-xl bg-surface-2 p-1" role="tablist" aria-label="Type">
        {(['expense', 'income', 'transfer'] as const).map((k) => (
          <button
            key={k}
            type="button"
            role="tab"
            aria-selected={kind === k}
            onClick={() => setKind(k)}
            className={`min-h-9 rounded-lg text-footnote font-semibold capitalize transition ${
              kind === k ? 'bg-surface text-ink shadow-card' : 'text-ink-2'
            }`}
          >
            {k}
          </button>
        ))}
      </div>

      <output
        aria-live="polite"
        className={`num block py-4 text-center text-display ${kind === 'income' ? 'text-ok' : 'text-ink'}`}
      >
        {display}
      </output>

      <NumPad onKey={(key: NumPadKey) => setTyped((t) => applyAmountKey(t, key))} onLongBackspace={() => setTyped('0')} />

      <p className="mt-3 text-center text-footnote text-ink-2">Categories, account and saving arrive in Phase 4.</p>
      <Button block size="lg" className="mt-3" disabled>
        Save
      </Button>
    </Sheet>
  );
}
