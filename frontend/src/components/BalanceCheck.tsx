/**
 * ACC-41 - check a cash, debit, savings or member account against the bank
 * (or the wallet) for a day. ACC-24 is the card's own check, by statement.
 *
 * One number, not every line: type what the bank shows for a day, and the
 * page shows the app's balance for the same day and the difference. A match
 * is "✓ Checked". A difference offers what could explain it:
 *
 *   A transaction I forgot   the add sheet on that day, the amount filled in -
 *                            once it is saved the difference is gone, because
 *                            the check is worked out again on every read
 *   Record an adjustment     the balance question's own path (ACC-28): today's
 *                            balance moved by the difference, as a balance
 *                            adjustment with its audit entry - never a new writer
 *   (or leave it)            it stays on the account until something answers it
 */
import { format, parseISO } from 'date-fns';
import { useEffect, useState } from 'react';
import { ApiError } from '../lib/api';
import { checkBalance, updateAccount, type Account } from '../lib/accounts';
import { afterWrite, MONEY } from '../lib/invalidate';
import { centavos, formatPHP, fromCentavos, toDecimalString } from '../lib/money';
import { localToday } from '../lib/transactions';
import { useUiStore } from '../stores/uiStore';
import { Button } from './ui/Button';
import { Card } from './ui/Card';
import { MoneyField } from './ui/MoneyField';
import { Sheet } from './ui/Sheet';

const day = (iso: string) => format(parseISO(iso), 'd MMM');
/** Cash is counted, not read off a bank's app. */
const source = (account: Account) => (account.type === 'cash' ? { where: 'in the wallet', said: 'you counted', field: 'What you counted' }
  : { where: 'at the bank', said: 'the bank said', field: 'What the bank shows' });
const unsigned = (value: string) => value.replace(/^-/, '');

export function BalanceCheck({ account }: { account: Account }) {
  const openSheet = useUiStore((s) => s.openAddSheet);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const check = account.balance_check ?? null;
  const words = source(account);

  const adjust = async () => {
    if (!check) return;
    setBusy(true);
    setError(null);
    try {
      // ACC-28's own question, answered up front: today's balance, moved by the difference.
      await updateAccount(account.id, {
        name: account.name, type: account.type, subtype: account.subtype, colour: account.colour,
        icon: account.icon, note: account.note,
        balance: fromCentavos(centavos(account.balance) + centavos(check.difference)),
        balance_action: 'adjust', balance_note: `Checked against the bank on ${day(check.on)}`,
      });
      afterWrite(...MONEY);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'That did not save.');
    }
    setBusy(false);
  };

  const forgot = () => {
    if (!check) return;
    // The bank has LESS: something went out that was never recorded. More: something came in.
    openSheet(undefined, check.on, {
      accountId: account.id,
      type: check.difference.startsWith('-') ? 'expense' : 'income',
      amount: unsigned(check.difference),
    });
  };

  return (
    <Card className="mt-3 space-y-3">
      {!check && (
        <>
          <p className="text-body">{account.type === 'cash' ? 'Does the wallet match?' : 'Does this match the bank?'}</p>
          <p className="text-footnote text-ink-2">Type the balance for a day, and the app checks its own balance for the same day.</p>
        </>
      )}
      {check?.checked && (
        <p className="text-body">
          <span className="font-bold text-ok">✓ Checked {day(check.on)}</span>
          <span className="text-ink-2"> · matches at <span className="num whitespace-nowrap">{formatPHP(check.bank)}</span></span>
          {check.stale && <span className="block text-footnote text-ink-3">That was over a month ago.</span>}
        </p>
      )}
      {check && !check.checked && (
        <>
          <div>
            <p className="text-body">
              <span className="font-bold text-warn">
                <span className="num">{formatPHP(unsigned(check.difference))}</span>
                {check.difference.startsWith('-') ? ` less ${words.where}` : ` more ${words.where}`}
              </span>
            </p>
            <p className="text-footnote text-ink-2">
              On {day(check.on)} {words.said} <span className="num">{formatPHP(check.bank)}</span>; the app had{' '}
              <span className="num">{formatPHP(check.app)}</span>.
            </p>
          </div>
          <div className="space-y-2">
            <Button variant="secondary" block disabled={busy} onClick={forgot}>A transaction I forgot</Button>
            <Button variant="secondary" block disabled={busy} onClick={() => void adjust()}>Record it as an adjustment</Button>
          </div>
          <p className="text-caption text-ink-3">Or leave it - it stays here until something explains it.</p>
        </>
      )}
      {error && <p className="text-footnote text-danger">{error}</p>}
      <Button block variant={check ? 'ghost' : 'primary'} onClick={() => setOpen(true)}>
        {check ? 'Check again' : 'Check the balance'}
      </Button>
      <CheckSheet account={account} open={open} onClose={() => setOpen(false)} />
    </Card>
  );
}

function CheckSheet({ account, open, onClose }: { account: Account; open: boolean; onClose: () => void }) {
  const [on, setOn] = useState(localToday());
  const [typed, setTyped] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (open) {
      setOn(localToday());
      setTyped('');
      setError(null);
    }
  }, [open]);

  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      await checkBalance(account.id, on, toDecimalString(typed));
      afterWrite('accounts');
      onClose();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'That did not save.');
    }
    setBusy(false);
  };

  return (
    <Sheet open={open} onClose={onClose} title={`Check ${account.name}`}>
      <div className="space-y-4 pb-2">
        <label className="block text-footnote font-semibold text-ink-2">
          The balance at the end of
          <input type="date" value={on} max={localToday()} onChange={(e) => setOn(e.target.value)}
            className="mt-1.5 block min-h-12 w-full rounded-xl border-2 border-stroke bg-surface px-3 text-body font-normal text-ink" />
        </label>
        <MoneyField label={source(account).field} value={typed} onChange={setTyped} allowNegative placeholder="0.00" />
        <p className="text-footnote text-ink-3">Only this figure is kept. Nothing is changed until you say what the difference was.</p>
        {error && <p className="text-footnote text-danger">{error}</p>}
        <Button block size="lg" disabled={busy || !typed || !on} onClick={() => void save()}>Check</Button>
      </div>
    </Sheet>
  );
}
