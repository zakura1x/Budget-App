/**
 * The add-transaction sheet - the most important screen in the app (TXN-01).
 *
 * The target is two taps and a number: the sheet opens with the numpad up and
 * the account already chosen, so an expense is a category chip and the digits.
 * Everything else is one tap away and never in the way:
 *
 *  - Category chips scroll sideways, most-used first (TXN-05).
 *  - Repeat last entry (TXN-17) sits where a fresh sheet has nothing typed yet
 *    - the second-most-used action, right under the thumb that opened this.
 *  - SPLIT (TXN-16) is hidden until asked for. Splits are the exception, and a
 *    simple entry must not get slower because they exist. Opened, it shows a
 *    live "left to allocate" in exact centavos; the server refuses anything
 *    that does not add up, so the sheet never offers to save it.
 *
 * New entries are optimistic: the sheet closes and the row appears in the
 * ledger before the response lands. Edits and deletes wait for the server.
 *
 * Pick a card with your own spending limit and the sheet says what is left of
 * it this cycle, live as you type (ACC-23). It warns; it never stops the save -
 * refusing a purchase you really made would only make the records wrong.
 *
 * A balance adjustment (ACC-29) opens read-only, with Delete: it was recorded
 * when a balance was set, and editing its amount would contradict the record.
 *
 * TAGS (TXN-10) sit behind a "Tags" button beside "Add note" - one tap away,
 * never in the way of two taps and a number. An entry that has tags opens
 * with them showing.
 */
import { useEffect, useMemo, useState } from 'react';
import { ApiError } from '../lib/api';
import { listAccounts, type Account } from '../lib/accounts';
import { flatten, listCategories, type Category } from '../lib/categories';
import {
  applyAmountKey,
  centavos,
  formatPHP,
  fromCentavos,
  sanitizeAmount,
  toDecimalString,
} from '../lib/money';
import {
  createTransaction,
  deleteTransaction,
  localToday,
  repeatLast,
  updateTransaction,
  type EntryType,
  type TransactionDraft,
} from '../lib/transactions';
import { listTags, type Tag } from '../lib/tags';
import { useLedgerStore } from '../stores/ledgerStore';
import { useUiStore } from '../stores/uiStore';
import { ReceiptControl } from './ReceiptControl';
import { GlyphTile } from './StylePicker';
import { Button } from './ui/Button';
import { NumPad, type NumPadKey } from './ui/NumPad';
import { Segmented } from './ui/Segmented';
import { Sheet } from './ui/Sheet';

interface SplitLine {
  key: number;
  category_id: number | null;
  amount: string;
}

/** Centavos in a typed amount, or 0 while it is still half-typed. */
function cents(typed: string): number {
  try {
    return centavos(toDecimalString(typed || '0'));
  } catch {
    return 0;
  }
}

/** The typed form of a stored amount: "150.00" -> "150", "12.50" -> "12.50". */
function typedFrom(amount: string): string {
  return amount.endsWith('.00') ? amount.slice(0, -3) : amount;
}

function Chip({
  selected,
  onClick,
  children,
  colour,
}: {
  selected: boolean;
  onClick: () => void;
  children: React.ReactNode;
  colour?: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={selected}
      className={[
        'flex min-h-tap shrink-0 items-center gap-2 rounded-xl px-3 text-footnote font-medium transition',
        selected ? 'bg-accent text-on-accent' : 'bg-surface-2 text-ink-2 active:bg-line',
      ].join(' ')}
      style={selected && colour ? { backgroundColor: colour, color: '#fff' } : undefined}
    >
      {children}
    </button>
  );
}

export function TransactionSheet() {
  const open = useUiStore((s) => s.addSheetOpen);
  const editing = useUiStore((s) => s.editing);
  const close = useUiStore((s) => s.closeAddSheet);
  const addOn = useUiStore((s) => s.addOn);
  const ledger = useLedgerStore();

  const [kind, setKind] = useState<EntryType>('expense');
  const [typed, setTyped] = useState('0');
  const [categoryId, setCategoryId] = useState<number | null>(null);
  const [accountId, setAccountId] = useState<number | null>(null);
  const [counterId, setCounterId] = useState<number | null>(null);
  const [txnDate, setTxnDate] = useState(localToday());
  const [note, setNote] = useState('');
  const [showNote, setShowNote] = useState(false);
  const [splitting, setSplitting] = useState(false);
  const [lines, setLines] = useState<SplitLine[]>([]);
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [tree, setTree] = useState<Category[]>([]);
  const [tags, setTags] = useState<Tag[]>([]);
  const [tagIds, setTagIds] = useState<number[]>([]);
  const [showTags, setShowTags] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // Load what the chips need, and set the sheet up, every time it opens.
  useEffect(() => {
    if (!open) return;
    setError(null);
    setBusy(false);
    const controller = new AbortController();
    Promise.all([listAccounts(controller.signal), listCategories(controller.signal), listTags(controller.signal)])
      .then(([accountList, categories, tagList]) => {
        const active = accountList.accounts.filter((a) => !a.archived || a.id === editing?.account_id);
        setAccounts(active);
        setTree(categories);
        setTags(tagList);
        if (!editing) {
          // The account you used last is the account you are about to use.
          const recent = ledger.items.find((row) => row.id > 0)?.account_id;
          setAccountId(active.some((a) => a.id === recent) ? (recent ?? null) : (active[0]?.id ?? null));
          setCounterId(active[1]?.id ?? null);
        }
      })
      .catch((e: Error) => e.name !== 'AbortError' && setError(e.message));

    if (editing) {
      setKind(editing.type === 'adjustment' ? 'expense' : editing.type);
      setTyped(typedFrom(editing.amount));
      setTxnDate(editing.txn_date);
      setNote(editing.notes ?? '');
      setShowNote(Boolean(editing.notes));
      setTagIds(editing.tag_ids ?? []);
      setShowTags((editing.tag_ids ?? []).length > 0);
      if (editing.type === 'transfer') {
        const out = editing.direction !== 'in';
        setAccountId(out ? editing.account_id : editing.counter_account_id);
        setCounterId(out ? editing.counter_account_id : editing.account_id);
      } else {
        setAccountId(editing.account_id);
      }
      const multi = editing.splits.length > 1;
      setSplitting(multi);
      setCategoryId(editing.splits[0]?.category_id ?? null);
      setLines(
        multi
          ? editing.splits.map((s, i) => ({ key: i, category_id: s.category_id, amount: typedFrom(s.amount) }))
          : [],
      );
    } else {
      setKind('expense');
      setTyped('0');
      setCategoryId(null);
      setTxnDate(addOn ?? localToday());
      setNote('');
      setShowNote(false);
      setTagIds([]);
      setShowTags(false);
      setSplitting(false);
      setLines([]);
    }
    return () => controller.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, editing]);

  // Most-used first (TXN-05), then the order you arranged them in.
  const chips = useMemo(() => {
    if (kind === 'transfer') return [];
    return flatten(tree)
      .filter((c) => c.kind === kind && !c.archived)
      .map((c, order) => ({ c, order }))
      .sort((a, b) => b.c.usage - a.c.usage || a.order - b.order)
      .map(({ c }) => c);
  }, [tree, kind]);

  const amount = toDecimalString(typed);
  const amountCents = cents(typed);
  const allocated = lines.reduce((sum, line) => sum + cents(line.amount), 0);
  const remaining = amountCents - allocated;

  const startSplit = () => {
    setSplitting(true);
    setLines([
      { key: 1, category_id: categoryId, amount: typed === '0' ? '' : typed },
      { key: 2, category_id: null, amount: '' },
    ]);
  };

  const problem = (() => {
    if (amountCents <= 0) return 'Type an amount';
    if (accountId === null) return 'Choose an account';
    if (kind === 'transfer') {
      if (counterId === null) return 'Choose where the money goes';
      if (counterId === accountId) return 'Pick two different accounts';
      return null;
    }
    if (splitting) {
      if (lines.some((l) => l.category_id === null || cents(l.amount) <= 0)) return 'Each line needs a category and an amount';
      if (remaining !== 0) return null; // shown live under the lines instead
      return null;
    }
    if (categoryId === null) return 'Choose a category';
    return null;
  })();
  const canSave = !busy && problem === null && (!splitting || kind === 'transfer' || remaining === 0);

  const draft = (): TransactionDraft => {
    const base = { type: kind, amount, account_id: accountId as number, txn_date: txnDate, notes: note.trim() || null };
    if (kind === 'transfer') return { ...base, counter_account_id: counterId as number };
    // Only ids that still exist - a tag deleted while the sheet was open would be refused.
    const tagged = { ...base, tag_ids: tagIds.filter((id) => tags.some((t) => t.id === id)) };
    if (splitting) {
      return {
        ...tagged,
        splits: lines.map((l) => ({ category_id: l.category_id as number, amount: toDecimalString(l.amount) })),
      };
    }
    return { ...tagged, category_id: categoryId as number };
  };

  const save = async () => {
    if (!canSave) return;
    const body = draft();

    if (!editing) {
      // Optimistic: the row is in the ledger before the server has answered.
      const pendingId = ledger.addPending({
        type: body.type,
        txn_date: body.txn_date,
        amount: body.amount,
        account_id: body.account_id,
        splits: body.splits
          ? body.splits.map((s) => ({ ...s, note: null }))
          : [{ category_id: body.category_id ?? null, amount: body.amount, note: null }],
        merchant: null,
        notes: body.notes ?? null,
        direction: body.type === 'transfer' ? 'out' : null,
        counter_account_id: body.counter_account_id ?? null,
        pair_id: null,
        tag_ids: body.tag_ids ?? [],
        created_at: null,
      });
      close();
      try {
        ledger.applyOutcome(await createTransaction(body), pendingId);
      } catch (e) {
        ledger.failPending(pendingId);
        useLedgerStore.setState({
          error: `That entry did not save — ${e instanceof ApiError ? e.message : 'try again'}.`,
        });
      }
      return;
    }

    setBusy(true);
    setError(null);
    try {
      ledger.applyOutcome(await updateTransaction(editing.id, body), editing.id);
      close();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'That did not save. Try again.');
      setBusy(false);
    }
  };

  const remove = async () => {
    if (!editing) return;
    setBusy(true);
    try {
      const outcome = await deleteTransaction(editing.id);
      ledger.removeIds(outcome.transactions.map((t) => t.id), outcome);
      close();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'That did not delete. Try again.');
      setBusy(false);
    }
  };

  const repeat = async () => {
    setBusy(true);
    setError(null);
    try {
      ledger.applyOutcome(await repeatLast(localToday()));
      close();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Nothing to repeat yet.');
      setBusy(false);
    }
  };

  // ACC-23. What is left of your own limit on the chosen card after this
  // purchase - only for a new expense dated inside the card's open cycle.
  const chosen = accounts.find((a) => a.id === accountId);
  const limitHint = (() => {
    const credit = chosen?.credit;
    if (!chosen || editing || kind !== 'expense' || !credit?.spending_limit || credit.limit_left === null) return null;
    if (txnDate < credit.period_start || txnDate > credit.period_closes) return null;
    const left = centavos(credit.limit_left) - amountCents;
    const ceiling = centavos(credit.spending_limit);
    const tone = left < 0 ? 'text-danger' : left * 5 < ceiling ? 'text-warn' : 'text-ink-2'; // under a fifth left
    const text =
      left < 0
        ? `${formatPHP(fromCentavos(-left))} over your limit on ${chosen.name} this cycle`
        : `${formatPHP(fromCentavos(left))} left on ${chosen.name} this cycle`;
    return { text, tone };
  })();

  const canRepeat = !editing && typed === '0' && ledger.items.some((row) => row.id > 0);

  if (editing?.type === 'adjustment') {
    const loss = editing.direction === 'out';
    return (
      <Sheet open={open} onClose={close} title={loss ? 'Unrecorded loss' : 'Unrecorded gain'}>
        <div className="space-y-3 pb-2">
          <output className="num block pt-2 text-center text-display text-ink">
            {loss ? '' : '+'}
            {formatPHP(loss ? `-${editing.amount}` : editing.amount)}
          </output>
          <p className="text-center text-footnote text-ink-2">
            {[chosen?.name, editing.txn_date].filter(Boolean).join(' · ')}
          </p>
          {editing.notes && <p className="text-center text-body">{editing.notes}</p>}
          <p className="rounded-2xl bg-surface-2 px-4 py-3 text-footnote text-ink-2">
            Recorded when you set this account’s balance. It moves the balance only — your budget stays the same —
            and it can’t be edited; delete it and set the balance again.
          </p>
          {error && <p className="text-footnote text-danger">{error}</p>}
          <Button variant="ghost" block className="text-danger" onClick={() => void remove()} disabled={busy}>
            Delete adjustment
          </Button>
        </div>
      </Sheet>
    );
  }
  const accountChips = (selected: number | null, choose: (id: number) => void, exclude?: number | null) =>
    accounts
      .filter((a) => a.id !== exclude)
      .map((a) => (
        <Chip key={a.id} selected={selected === a.id} onClick={() => choose(a.id)} colour={a.colour}>
          {a.name}
        </Chip>
      ));

  return (
    <Sheet open={open} onClose={close} title={editing ? 'Edit transaction' : 'New transaction'}>
      <div className="space-y-3">
        {(!editing || editing.type !== 'transfer') && (
          <Segmented
            label="Type"
            value={kind}
            onChange={(next) => {
              // A transfer is two rows; the server will not convert one.
              if (editing && (next === 'transfer') !== (editing.type === 'transfer')) return;
              setKind(next);
              setCategoryId(null);
              setSplitting(false);
            }}
            options={[
              { value: 'expense', label: 'Expense' },
              { value: 'income', label: 'Income' },
              ...(!editing ? [{ value: 'transfer' as const, label: 'Transfer' }] : []),
            ]}
          />
        )}

        <output
          aria-live="polite"
          className={`num block pt-2 text-center text-display ${kind === 'income' ? 'text-ok' : 'text-ink'}`}
        >
          {formatPHP(amount)}
        </output>

        {canRepeat && (
          <div className="flex justify-center">
            <button
              type="button"
              onClick={() => void repeat()}
              disabled={busy}
              className="min-h-tap rounded-xl px-3 text-footnote font-semibold text-accent active:bg-accent/10"
            >
              ↻ Repeat last entry
            </button>
          </div>
        )}

        {kind === 'transfer' ? (
          <div className="space-y-2">
            <p className="text-footnote font-semibold text-ink-2">From</p>
            <div className="no-scrollbar -mx-5 flex gap-2 overflow-x-auto px-5">
              {accountChips(accountId, setAccountId)}
            </div>
            <p className="text-footnote font-semibold text-ink-2">To</p>
            <div className="no-scrollbar -mx-5 flex gap-2 overflow-x-auto px-5">
              {accountChips(counterId, setCounterId, accountId)}
            </div>
          </div>
        ) : (
          <>
            {!splitting && (
              <div className="no-scrollbar -mx-5 flex gap-2 overflow-x-auto px-5" role="group" aria-label="Category">
                {chips.map((c) => (
                  <Chip key={c.id} selected={categoryId === c.id} onClick={() => setCategoryId(c.id)} colour={c.colour}>
                    {categoryId !== c.id && <GlyphTile icon={c.icon} colour={c.colour} size={24} />}
                    {c.name}
                  </Chip>
                ))}
                {chips.length === 0 && (
                  <p className="text-footnote text-ink-3">Add a {kind} category first, under More → Categories.</p>
                )}
              </div>
            )}
            <div className="no-scrollbar -mx-5 flex gap-2 overflow-x-auto px-5" role="group" aria-label="Account">
              {accountChips(accountId, setAccountId)}
            </div>
            {limitHint && (
              <p aria-live="polite" className={`num text-footnote font-medium ${limitHint.tone}`}>
                {limitHint.text}
              </p>
            )}
          </>
        )}

        <div className="flex flex-wrap items-center gap-2">
          <input
            type="date"
            value={txnDate}
            onChange={(e) => e.target.value && setTxnDate(e.target.value)}
            aria-label="Date"
            className="min-h-tap rounded-xl bg-surface-2 px-3 text-footnote font-medium text-ink"
          />
          {!showNote && (
            <button type="button" onClick={() => setShowNote(true)}
              className="min-h-tap rounded-xl px-3 text-footnote font-medium text-accent active:bg-accent/10">
              Add note
            </button>
          )}
          {kind !== 'transfer' && tags.length > 0 && !showTags && (
            <button type="button" onClick={() => setShowTags(true)}
              className="min-h-tap rounded-xl px-3 text-footnote font-medium text-accent active:bg-accent/10">
              Tags
            </button>
          )}
          {kind !== 'transfer' && !splitting && (
            <button type="button" onClick={startSplit}
              className="min-h-tap rounded-xl px-3 text-footnote font-medium text-accent active:bg-accent/10">
              Split
            </button>
          )}
        </div>

        {kind !== 'transfer' && showTags && tags.length > 0 && (
          <div className="no-scrollbar -mx-5 flex gap-2 overflow-x-auto px-5" role="group" aria-label="Tags">
            {tags.map((t) => {
              const on = tagIds.includes(t.id);
              return (
                <Chip key={t.id} selected={on} colour={t.colour}
                  onClick={() => setTagIds((ids) => (on ? ids.filter((id) => id !== t.id) : [...ids, t.id]))}>
                  {!on && <span className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: t.colour }} aria-hidden="true" />}
                  {t.name}
                </Chip>
              );
            })}
          </div>
        )}

        {showNote && (
          <input
            type="text"
            value={note}
            onChange={(e) => setNote(e.target.value)}
            maxLength={500}
            placeholder="Note"
            aria-label="Note"
            className="min-h-12 w-full rounded-xl border border-line bg-surface px-3.5 text-body outline-none focus:border-accent"
          />
        )}

        {splitting && kind !== 'transfer' && (
          <div className="space-y-2 rounded-2xl bg-surface-2 p-3">
            {lines.map((line) => (
              <div key={line.key} className="flex items-center gap-2">
                <select
                  value={line.category_id ?? ''}
                  onChange={(e) =>
                    setLines((ls) => ls.map((l) => (l.key === line.key ? { ...l, category_id: Number(e.target.value) || null } : l)))
                  }
                  aria-label="Split category"
                  className="min-h-tap min-w-0 flex-1 rounded-xl bg-surface px-2 text-footnote"
                >
                  <option value="">Category…</option>
                  {chips.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.parent_id ? `  ${c.name}` : c.name}
                    </option>
                  ))}
                </select>
                <input
                  value={line.amount}
                  onChange={(e) =>
                    setLines((ls) => ls.map((l) => (l.key === line.key ? { ...l, amount: sanitizeAmount(e.target.value) } : l)))
                  }
                  inputMode="decimal"
                  placeholder="0.00"
                  aria-label="Split amount"
                  className="num min-h-tap w-28 rounded-xl bg-surface px-3 text-right text-body"
                />
                <button
                  type="button"
                  aria-label="Remove line"
                  onClick={() => setLines((ls) => (ls.length > 1 ? ls.filter((l) => l.key !== line.key) : ls))}
                  className="flex h-10 w-8 items-center justify-center text-ink-3"
                >
                  ×
                </button>
              </div>
            ))}
            <div className="flex items-center justify-between pt-1">
              <button
                type="button"
                onClick={() => setLines((ls) => [...ls, { key: Date.now(), category_id: null, amount: remaining > 0 ? fromCentavos(remaining) : '' }])}
                className="min-h-tap text-footnote font-semibold text-accent"
              >
                + Add a line
              </button>
              <span
                aria-live="polite"
                className={`num text-footnote font-semibold ${remaining === 0 ? 'text-ok' : remaining < 0 ? 'text-danger' : 'text-warn'}`}
              >
                {remaining === 0
                  ? 'All allocated'
                  : remaining > 0
                    ? `${formatPHP(fromCentavos(remaining))} left to allocate`
                    : `${formatPHP(fromCentavos(-remaining))} over`}
              </span>
            </div>
            <button type="button" onClick={() => { setSplitting(false); setLines([]); }}
              className="min-h-tap text-footnote text-ink-2">
              Don’t split
            </button>
          </div>
        )}

        <NumPad onKey={(key: NumPadKey) => setTyped((t) => applyAmountKey(t, key))} onLongBackspace={() => setTyped('0')} />

        {error && <p className="text-footnote text-danger">{error}</p>}

        <Button block size="lg" onClick={() => void save()} disabled={!canSave}>
          {problem ?? (editing ? 'Save changes' : 'Save')}
        </Button>

        {editing && editing.id > 0 && (
          <ReceiptControl transactionId={editing.id} attachmentId={editing.attachment_id ?? null} />
        )}

        {editing && (
          <Button variant="ghost" block className="text-danger" onClick={() => void remove()} disabled={busy}>
            Delete {editing.type === 'transfer' ? 'transfer' : 'transaction'}
          </Button>
        )}
      </div>
    </Sheet>
  );
}
