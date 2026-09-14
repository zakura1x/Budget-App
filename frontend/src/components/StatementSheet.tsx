/**
 * The statement check (ACC-24..26, FEATURES.md §21).
 *
 * One number from the bank, not every line. The app already knows what should
 * be on the statement - the purchases entered on the days they were made - so
 * the sheet shows its own figure, takes the bank's, and asks what any
 * difference is. The app suggests; nothing is recorded without a tap:
 *
 *   higher  a fee or interest (posts to the card on the closing date) ·
 *           a purchase I forgot (the ordinary add sheet) · leave it
 *   lower   a purchase the bank posted on the next statement (moves it; the
 *           budget keeps its date) · a refund I forgot · leave it
 *
 * A lower total is never offered as interest. A difference can be explained in
 * parts: each answer comes back as the statement now stands, with what is left.
 * Installment interest joins the choices with installments (Phase 7).
 */
import { format, parseISO } from 'date-fns';
import { useEffect, useState } from 'react';
import type { Account } from '../lib/accounts';
import { ApiError } from '../lib/api';
import { flatten, listCategories, type Category } from '../lib/categories';
import { formatPHP, sanitizeAmount, toDecimalString } from '../lib/money';
import { checkStatement, getStatement, markPostedNext, recordCharge, type StatementCheck } from '../lib/statements';
import { useLedgerStore } from '../stores/ledgerStore';
import { useUiStore } from '../stores/uiStore';
import { Button } from './ui/Button';
import { Sheet } from './ui/Sheet';
import { TextField } from './ui/TextField';

const isZero = (value: string) => /^-?0+(\.0+)?$/.test(value);
const day = (iso: string) => format(parseISO(iso), 'd MMM');
/** Interest and bank fees first - the categories a statement charge usually belongs in. */
const LIKELY = /interest|fee|charge/i;

function Choice({ title, hint, onClick, disabled }: { title: string; hint: string; onClick: () => void; disabled?: boolean }) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className="w-full rounded-2xl bg-surface-2 px-4 py-3 text-left transition active:bg-line disabled:opacity-40"
    >
      <span className="block text-body font-semibold text-ink">{title}</span>
      <span className="mt-0.5 block text-footnote text-ink-2">{hint}</span>
    </button>
  );
}

export interface StatementSheetProps {
  open: boolean;
  account: Account | null;
  onClose: () => void;
  /** Something was recorded - balances and the bill have moved. */
  onChanged: () => void;
}

export function StatementSheet({ open, account, onClose, onChanged }: StatementSheetProps) {
  const openAddSheet = useUiStore((s) => s.openAddSheet);
  const [data, setData] = useState<StatementCheck | null>(null);
  const [categories, setCategories] = useState<Category[]>([]);
  const [bank, setBank] = useState('');
  const [charging, setCharging] = useState(false);
  const [amount, setAmount] = useState('');
  const [categoryId, setCategoryId] = useState<number | null>(null);
  const [note, setNote] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const closes = account?.credit?.bill.closes ?? null;

  useEffect(() => {
    if (!open || !account || !closes) return;
    setData(null);
    setError(null);
    setBusy(false);
    setCharging(false);
    setNote('');
    const controller = new AbortController();
    Promise.all([getStatement(account.id, closes, controller.signal), listCategories(controller.signal)])
      .then(([check, tree]) => {
        accept(check);
        setBank(check.statement.bank_total ?? '');
        const spending = flatten(tree).filter((c) => c.kind === 'expense' && !c.archived);
        spending.sort((a, b) => Number(LIKELY.test(b.name)) - Number(LIKELY.test(a.name)));
        setCategories(spending);
        setCategoryId(spending.find((c) => LIKELY.test(c.name))?.id ?? null);
      })
      .catch((e: Error) => e.name !== 'AbortError' && setError(e.message));
    return () => controller.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, account, closes]);

  const accept = (check: StatementCheck) => {
    setData(check);
    const difference = check.statement.difference;
    setAmount(difference && !difference.startsWith('-') ? difference : '');
  };

  const run = async (call: () => Promise<StatementCheck>, recorded: boolean) => {
    setBusy(true);
    setError(null);
    try {
      accept(await call());
      setCharging(false);
      if (recorded) {
        onChanged();
        void useLedgerStore.getState().load();
      }
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'That did not save. Try again.');
    }
    setBusy(false);
  };

  const forgot = () => {
    onClose();
    openAddSheet();
  };

  if (!account || !closes) return null;
  const statement = data?.statement;
  const difference = statement?.difference ?? null;
  const higher = difference !== null && !difference.startsWith('-') && !isZero(difference);
  const lower = difference !== null && difference.startsWith('-');
  const gap = difference === null ? '' : difference.replace(/^-/, '');

  return (
    <Sheet open={open} onClose={onClose} title="Check statement">
      <div className="space-y-4 pb-2">
        <p className="text-footnote text-ink-2">
          {account.name}
          {statement && ` · ${day(statement.start)} – ${day(statement.closes)} · due ${day(statement.due)}`}
        </p>

        {!statement ? (
          error ? <p className="text-footnote text-danger">{error}</p> : <div className="skeleton h-40 rounded-card" aria-hidden="true" />
        ) : (
          <>
            <div className="grid grid-cols-2 gap-3 text-center">
              <div className="rounded-2xl bg-surface-2 px-3 py-3">
                <p className="text-caption text-ink-3">The app’s figure</p>
                <p className="num mt-0.5 text-headline">{formatPHP(statement.amount)}</p>
              </div>
              <div className="rounded-2xl bg-surface-2 px-3 py-3">
                <p className="text-caption text-ink-3">The bank’s figure</p>
                <p className="num mt-0.5 text-headline">{statement.bank_total ? formatPHP(statement.bank_total) : '—'}</p>
              </div>
            </div>

            <TextField
              label="Statement total from your bank"
              value={bank}
              onChange={(e) => setBank(sanitizeAmount(e.target.value))}
              inputMode="decimal"
              placeholder="0.00"
              hint="One number — the total the bank says you owe. Not every line."
              trailing={
                <Button
                  variant="ghost"
                  disabled={busy || !bank.trim()}
                  onClick={() => void run(() => checkStatement(account.id, closes, toDecimalString(bank)), false)}
                >
                  Check
                </Button>
              }
            />

            {difference !== null && isZero(difference) && (
              <p className="rounded-2xl bg-ok/10 px-4 py-3 text-footnote font-semibold text-ok">✓ Matches the bank.</p>
            )}

            {(higher || lower) && (
              <div className="space-y-2">
                <p className={`text-footnote font-semibold ${higher ? 'text-warn' : 'text-ink'}`}>
                  The bank shows <span className="num">{formatPHP(gap)}</span> {higher ? 'more' : 'less'} than the app.
                  What is it?
                </p>

                {higher && (
                  <>
                    <Choice
                      title="A fee or interest"
                      hint={`Recorded on the card on ${day(statement.closes)}, so it lands on this statement.`}
                      onClick={() => setCharging((v) => !v)}
                      disabled={busy}
                    />
                    {charging && (
                      <div className="space-y-3 rounded-2xl border border-line p-3">
                        <div className="flex flex-wrap gap-2" role="group" aria-label="Category">
                          {categories.map((c) => (
                            <button
                              key={c.id}
                              type="button"
                              aria-pressed={categoryId === c.id}
                              onClick={() => setCategoryId(c.id)}
                              className={`min-h-tap rounded-xl px-3 text-footnote font-medium transition ${
                                categoryId === c.id ? 'bg-accent text-on-accent' : 'bg-surface-2 text-ink-2'
                              }`}
                            >
                              {c.name}
                            </button>
                          ))}
                        </div>
                        <TextField
                          label="Amount"
                          value={amount}
                          onChange={(e) => setAmount(sanitizeAmount(e.target.value))}
                          inputMode="decimal"
                          hint={`Up to ${formatPHP(gap)} — the rest can be explained separately.`}
                        />
                        <TextField label="Note (optional)" value={note} onChange={(e) => setNote(e.target.value)} maxLength={500}
                          placeholder="Finance charge" />
                        <Button
                          block
                          disabled={busy || categoryId === null || !amount.trim()}
                          onClick={() =>
                            void run(
                              () =>
                                recordCharge(account.id, closes, {
                                  amount: toDecimalString(amount),
                                  category_id: categoryId as number,
                                  note: note.trim() || null,
                                }),
                              true,
                            )
                          }
                        >
                          Record charge
                        </Button>
                      </div>
                    )}
                    <Choice
                      title="A purchase I forgot"
                      hint={`Add it on this card, dated on or before ${day(statement.closes)}.`}
                      onClick={forgot}
                      disabled={busy}
                    />
                  </>
                )}

                {lower && (
                  <>
                    {data.late_candidates.map((purchase) => (
                      <Choice
                        key={purchase.id}
                        title={`${purchase.merchant ?? 'A purchase'} was posted on the next statement`}
                        hint={`${formatPHP(purchase.amount)} on ${day(purchase.txn_date)} — within this card’s ${statement.posting_lag_days}-day posting delay. Your budget keeps its date.`}
                        onClick={() => void run(() => markPostedNext(account.id, closes, purchase.id), true)}
                        disabled={busy}
                      />
                    ))}
                    <Choice
                      title="A refund I haven’t entered"
                      hint="Add it as income on this card."
                      onClick={forgot}
                      disabled={busy}
                    />
                  </>
                )}

                <Button variant="ghost" block onClick={onClose} disabled={busy}>
                  Leave it for now
                </Button>
              </div>
            )}

            {error && <p className="text-footnote text-danger">{error}</p>}
          </>
        )}
      </div>
    </Sheet>
  );
}
