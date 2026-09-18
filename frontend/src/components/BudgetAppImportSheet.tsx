/**
 * Import a backup from the Budget phone app (DAT-21).
 *
 * Three steps on one sheet: the preview says what the file becomes; every
 * account asks for TODAY'S balance as the old app shows it - a card or a loan
 * as the amount owed - because that app's own history does not add up to its
 * balances; then one tap imports. A person's loan comes prefilled with what
 * they still owe. Nothing is written until the button, and the file is never
 * kept: it travels in the request body and is read in memory.
 */
import { format, parseISO } from 'date-fns';
import { useEffect, useState } from 'react';
import { ApiError } from '../lib/api';
import { kindLabelOf } from '../lib/accounts';
import {
  previewBudgetApp,
  runBudgetApp,
  type BudgetAppAccount,
  type BudgetAppPreview,
} from '../lib/backups';
import { formatPHP, toDecimalString } from '../lib/money';
import { useBudgetStore } from '../stores/budgetStore';
import { useLedgerStore } from '../stores/ledgerStore';
import { Button } from './ui/Button';
import { Sheet } from './ui/Sheet';

/** One leading minus, one point, two places - the minus matters for a loan that turned around. */
function clean(input: string): string {
  const negative = input.trimStart().startsWith('-');
  const [whole = '', ...rest] = input.replace(/[^\d.]/g, '').split('.');
  const body = rest.length ? `${whole}.${rest.join('').slice(0, 2)}` : whole;
  return negative ? `-${body}` : body;
}

function label(account: BudgetAppAccount): string {
  if (account.type === 'lent') return 'Still owed to you';
  if (account.owed) return 'Owed today';
  return 'Balance today';
}

export function BudgetAppImportSheet({ file, onClose }: { file: { name: string; data: string } | null; onClose: () => void }) {
  const [preview, setPreview] = useState<BudgetAppPreview | null>(null);
  const [balances, setBalances] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!file) return;
    setPreview(null);
    setError(null);
    setResult(null);
    setBusy(true);
    previewBudgetApp(file.data)
      .then((found) => {
        setPreview(found);
        setBalances(Object.fromEntries(found.accounts.map((a) => [a.key, a.suggested ?? ''])));
      })
      .catch((e) => setError(e instanceof ApiError ? e.message : 'That file could not be read.'))
      .finally(() => setBusy(false));
  }, [file]);

  if (!file) return null;
  const missing = preview ? preview.accounts.filter((a) => !balances[a.key]?.trim()).length : 0;

  const go = async () => {
    if (!preview) return;
    setBusy(true);
    setError(null);
    try {
      const typed = Object.fromEntries(Object.entries(balances).map(([key, value]) => [key, toDecimalString(value.trim())]));
      const done = await runBudgetApp(file.data, typed);
      setResult(
        `${done.transactions} transaction${done.transactions === 1 ? '' : 's'} imported · ${done.accounts_created} accounts and ` +
          `${done.categories_created} categories added${done.skipped_duplicates ? ` · ${done.skipped_duplicates} already here, skipped` : ''}.`,
      );
      setPreview(null);
      useLedgerStore.setState((s) => ({ version: s.version + 1 }));
      void useLedgerStore.getState().load({});
      void useBudgetStore.getState().load(null);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'The import did not run.');
    }
    setBusy(false);
  };

  return (
    <Sheet open onClose={onClose} title="Import from Budget App">
      <div className="space-y-4 pb-2">
        <p className="truncate text-footnote text-ink-2">{file.name}</p>
        {busy && !preview && !result && <div className="skeleton h-40 rounded-card" aria-hidden="true" />}
        {error && <p className="rounded-2xl border-2 border-danger bg-danger/10 px-4 py-3 text-footnote text-danger">{error}</p>}
        {result && <p className="rounded-2xl border-2 border-ok bg-ok/10 px-4 py-3 text-footnote font-semibold text-ok">✓ {result}</p>}

        {preview && (
          <>
            <div className="rounded-card border-2 border-stroke bg-surface-2 p-4 text-footnote text-ink-2">
              <p className="text-body font-semibold text-ink">
                {preview.ready} of {preview.transactions} transactions to import
              </p>
              {preview.first_date && preview.last_date && (
                <p>{format(parseISO(preview.first_date), 'd MMM yyyy')} – {format(parseISO(preview.last_date), 'd MMM yyyy')}</p>
              )}
              <ul className="mt-2 list-disc space-y-0.5 pl-4">
                <li>{preview.accounts.filter((a) => !a.exists).length} new accounts · {preview.categories_new} new categories</li>
                {preview.duplicates > 0 && <li>{preview.duplicates} already recorded here — skipped</li>}
                {preview.adjustments_folded > 0 && (
                  <li>{preview.adjustments_folded} balance adjustments not copied — the balances you type below replace them</li>
                )}
                {preview.loan_records_folded > 0 && (
                  <li>{preview.loan_records_folded} loan records with no account — they only move that person’s balance</li>
                )}
                {preview.unassigned > 0 && <li>{preview.unassigned} entries had no account — they go to “Unassigned (Budget App)”</li>}
                {preview.skipped > 0 && <li>{preview.skipped} rows could not be read and are left out</li>}
              </ul>
            </div>

            <div>
              <p className="text-footnote font-semibold text-ink-2">Today’s balance, as the Budget app shows it</p>
              <p className="mt-0.5 text-caption text-ink-3">
                The history is imported as it is; each account’s starting balance is set so today matches what you type.
              </p>
            </div>
            <div className="divide-y divide-stroke/80 overflow-hidden rounded-card border-2 border-stroke bg-surface-2">
              {preview.accounts.map((account) => (
                <label key={account.key} className="flex items-center gap-3 px-4 py-2.5">
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-body">{account.name}</span>
                    <span className="block truncate text-caption text-ink-3">
                      {kindLabelOf(account.type, account.subtype)}
                      {account.exists ? ' · already here' : ' · new'}
                      {account.archived && ' · settled, archived'}
                      {` · ${account.transactions} ${account.transactions === 1 ? 'entry' : 'entries'}`}
                    </span>
                  </span>
                  <span className="w-32 shrink-0">
                    <span className="block text-right text-caption text-ink-3">{label(account)}</span>
                    <input
                      value={balances[account.key] ?? ''}
                      onChange={(e) => setBalances((b) => ({ ...b, [account.key]: clean(e.target.value) }))}
                      inputMode="decimal"
                      placeholder="0.00"
                      aria-label={`${account.name}: ${label(account).toLowerCase()}`}
                      className="num min-h-tap w-full rounded-xl border-2 border-stroke bg-surface px-2.5 text-right text-body"
                    />
                  </span>
                </label>
              ))}
            </div>
            <p className="text-caption text-ink-3">
              History alone adds up to {preview.accounts.slice(0, 2).map((a) => `${a.name} ${formatPHP(a.history)}`).join(', ')}
              {preview.accounts.length > 2 ? '…' : ''} — which is why the balance is asked for.
            </p>

            <Button block size="lg" disabled={busy || missing > 0} onClick={() => void go()}>
              {missing > 0
                ? `Type ${missing} more balance${missing === 1 ? '' : 's'}`
                : preview.ready === 0
                  ? 'Update balances only'
                  : `Import ${preview.ready} transactions`}
            </Button>
          </>
        )}
      </div>
    </Sheet>
  );
}
