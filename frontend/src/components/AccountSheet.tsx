/**
 * Add or edit one account (ACC-01..ACC-30).
 *
 * Things this form does deliberately:
 *
 *  - The TYPE is chosen first and, once the account exists, cannot change.
 *    The type decides what a balance means, so changing it later would
 *    silently reinterpret every transaction already recorded against it. The
 *    server refuses; the form says so rather than letting you try.
 *  - Credit terms and the investment value only appear on the types that have
 *    them. A closing day on a cash account is a field nothing reads.
 *  - An existing account shows its CURRENT balance (ACC-27) - the number people
 *    compare with their bank app - and a card shows it as AMOUNT OWED, the way
 *    its statement does. Saving a different figure asks first (ACC-28): a
 *    balance is never stored, so the change has to be recorded as something -
 *    an unrecorded loss or gain, or a corrected opening balance. Only the first
 *    keeps a trail (ACC-30). Nothing is saved until one is chosen.
 *
 * Amounts are typed as text and sent as text. Nothing here calls Number() on one.
 */
import { useEffect, useState } from 'react';
import { ApiError } from '../lib/api';
import {
  ACCOUNT_KINDS,
  TYPE_HINT,
  TYPE_ICON,
  isOwed,
  kindLabelOf,
  type AccountKind,
  balanceQuestion,
  createAccount,
  setArchived,
  updateAccount,
  type Account,
  type AccountDraft,
  type AccountType,
  type BalanceAction,
  type BalanceQuestion,
  type InterestDraft,
} from '../lib/accounts';
import { flatten, type Category } from '../lib/categories';
import { afterWrite, MONEY } from '../lib/invalidate';
import { ensureCategories } from '../lib/prefetch';
import { InterestFields } from './InterestFields';
import { MoneyField } from './ui/MoneyField';
import { centavos, formatPHP, fromCentavos, toDecimalString, toRateString } from '../lib/money';
import { ColourPicker, GlyphTile, IconPicker } from './StylePicker';
import { ACCOUNT_GLYPHS } from './Glyph';
import { Button } from './ui/Button';
import { Segmented } from './ui/Segmented';
import { Sheet } from './ui/Sheet';
import { TextField } from './ui/TextField';
import { Toggle } from './ui/Toggle';

/** ACC-37. Mirrors account_service.EARNS_INTEREST - where a bank actually pays. */
const EARNS_INTEREST: AccountType[] = ['cash', 'debit', 'savings', 'member'];

/** ACC-38. Mirrors account_service.GIVES_CASHBACK - the accounts you spend FROM. */
const GIVES_CASHBACK: AccountType[] = ['cash', 'debit', 'credit', 'savings', 'member'];

/** Mirrors account_service.COUNTS_IN_CASH_ON_HAND_DEFAULT (ACC-18/31/32). */
const COUNTS_BY_DEFAULT: Record<AccountType, boolean> = {
  cash: true, debit: true, savings: true, credit: true, investment: false, lent: false, borrowed: false, member: true,
};

/**
 * ACC-37. The typed rates as the server wants them: amounts as decimal
 * strings, an empty ceiling on the top band, and nothing turned into a Number.
 */
function cleanInterest(draft: InterestDraft): InterestDraft {
  return {
    ...draft,
    // Rates are not money: four places, never the two-place money formatter.
    tax_rate: toRateString(draft.tax_rate ?? '20'),
    bands: draft.bands.map((band, index) => ({
      rate: toRateString(band.rate ?? ''),
      up_to: index === draft.bands.length - 1 || !band.up_to?.trim() ? null : toDecimalString(band.up_to.trim()),
    })),
  };
}

/** The balance field on an existing account, in the words of what its balance means. */
function balanceWords(type: AccountType): { label: string; hint: string } {
  if (type === 'credit') return { label: 'Amount owed', hint: 'What the card owes right now. Changing it asks how to record the difference.' };
  if (type === 'borrowed') return { label: 'Amount you still owe', hint: 'What is left to pay back. Changing it asks how to record the difference.' };
  if (type === 'lent') return { label: 'Still owed to you', hint: 'What has not come back yet. Changing it asks how to record the difference.' };
  if (type === 'investment') return { label: 'Value today', hint: 'What it is worth right now. Changing it asks how to record the difference — a gain or loss shows in Stats.' };
  return { label: 'Current balance', hint: 'What is really in it right now. Changing it asks how to record the difference.' };
}

/** The first figure on a new account. */
function openingWords(type: AccountType): { label: string; hint: string } {
  if (type === 'investment') return { label: 'Starting value', hint: 'What it was worth when you started tracking it.' };
  if (type === 'credit') return { label: 'Opening balance', hint: 'What you already owe on it, as a minus — −8,420.00.' };
  if (type === 'borrowed') return { label: 'Amount you owe', hint: 'What is left to pay back today. Pay it back later with a transfer into this account.' };
  if (type === 'lent') return { label: 'Amount lent', hint: 'What they still owe you. When it comes back, transfer it out of this account.' };
  if (type === 'member') return { label: 'Load on the card', hint: 'What is on it now. Top it up with a transfer.' };
  return { label: 'Opening balance', hint: 'What was in it before you started tracking.' };
}

/**
 * Keep only what an amount can contain: one leading minus, one decimal point,
 * two places. The minus matters — a card you already owe on opens negative,
 * and stripping it would silently turn a debt into credit.
 */
function clean(input: string): string {
  const negative = input.trimStart().startsWith('-');
  const [whole = '', ...rest] = input.replace(/[^\d.]/g, '').split('.');
  const body = rest.length ? `${whole}.${rest.join('').slice(0, 2)}` : whole;
  return negative ? `-${body}` : body;
}

/** Flip the sign of a decimal string: a card's balance is minus what it owes. */
const negate = (value: string) => toDecimalString(value.startsWith('-') ? value.slice(1) : `-${value}`);

export interface AccountSheetProps {
  open: boolean;
  account: Account | null;
  onClose: () => void;
  onSaved: () => void;
}

export function AccountSheet({ open, account, onClose, onSaved }: AccountSheetProps) {
  const editing = account !== null;
  const [type, setType] = useState<AccountType>('cash');
  const [name, setName] = useState('');
  const [opening, setOpening] = useState('');
  const [current, setCurrent] = useState('');
  const [colour, setColour] = useState('#4A90D9');
  const [icon, setIcon] = useState('cash');
  const [counts, setCounts] = useState(true);
  const [inNetWorth, setInNetWorth] = useState(true);
  /** ACC-14/27 - the same balance read the other way round: limit - owed - plans still to bill. */
  const [leftToSpend, setLeftToSpend] = useState('');
  const [closingDay, setClosingDay] = useState('');
  const [dueDay, setDueDay] = useState('');
  const [limit, setLimit] = useState('');
  const [ownLimit, setOwnLimit] = useState('');
  const [lag, setLag] = useState('3');
  const [question, setQuestion] = useState<BalanceQuestion | null>(null);
  /** A new account: has a kind been picked from the list yet? */
  const [picked, setPicked] = useState(false);
  const [example, setExample] = useState('BPI Debit');
  const [kindLabel, setKindLabel] = useState<{ label: string; hint: string } | null>(null);
  const [subtype, setSubtype] = useState<string | null>(null);
  const [balanceNote, setBalanceNote] = useState('');
  const [interest, setInterest] = useState<InterestDraft | null>(null);
  /** ACC-38 - what this account usually pays back, and where it lands. */
  const [cashbackRate, setCashbackRate] = useState('');
  const [cashbackCategory, setCashbackCategory] = useState<number | null>(null);
  /** REC-35. The interest a card or a loan charges, typed as the bank shows it (user, 2026-09-28). */
  const [debtRate, setDebtRate] = useState('');
  const [debtPer, setDebtPer] = useState<'month' | 'year'>('month');
  /** The income categories both blocks pick from - fetched once, here. */
  const [incomeCategories, setIncomeCategories] = useState<Category[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  /** What the balance field shows for an account: a card's balance as the amount owed. */
  const shownBalance = (a: Account) => (isOwed(a.type) ? negate(a.balance) : a.balance);

  /** Centavos in a typed amount, or 0 while it is half-typed. */
  const cents = (typed: string) => {
    try {
      return centavos(toDecimalString(typed.trim() || '0'));
    } catch {
      return 0;
    }
  };
  const limitCents = cents(limit);
  const unpaidCents = centavos(account?.credit?.unpaid_installments ?? '0.00');
  const typeOwed = (value: string) => {
    setCurrent(value);
    if (limitCents > 0) setLeftToSpend(fromCentavos(limitCents - unpaidCents - cents(value)));
  };
  const typeLeft = (value: string) => {
    setLeftToSpend(value);
    if (limitCents > 0) setCurrent(fromCentavos(limitCents - unpaidCents - cents(value)));
  };

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    void ensureCategories()
      .then((tree) => !cancelled && setIncomeCategories(flatten(tree).filter((c) => c.kind === 'income' && !c.archived)))
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [open]);

  useEffect(() => {
    if (!open) return;
    setError(null);
    setBusy(false);
    setQuestion(null);
    setBalanceNote('');
    setPicked(false);
    setSubtype(account?.subtype ?? null);
    setInNetWorth(account?.counts_in_net_worth ?? true);
    setKindLabel(null);
    if (account) {
      setType(account.type);
      setName(account.name);
      setOpening(account.opening_balance);
      setCurrent(shownBalance(account));
      setLeftToSpend(account.credit?.available ?? '');
      setColour(account.colour);
      setIcon(account.icon);
      setCounts(account.counts_in_cash_on_hand);
      setClosingDay(account.credit ? String(account.credit.statement_closing_day) : '');
      setDueDay(account.credit ? String(account.credit.payment_due_day) : '');
      setLimit(account.credit?.limit ?? '');
      setOwnLimit(account.credit?.spending_limit ?? '');
      setLag(account.credit ? String(account.credit.posting_lag_days) : '3');
      // ACC-37. The terms as stored; the marker and the carry are the server's.
      setInterest(account.interest
        ? {
            bands: account.interest.bands.map((band) => ({ ...band })),
            basis: account.interest.basis,
            tax_rate: account.interest.tax_rate,
            category_id: account.interest.category_id ?? 0,
          }
        : null);
      setCashbackRate(account.cashback ? account.cashback.rate.replace(/0+$/, '').replace(/\.$/, '') : '');
      setCashbackCategory(account.cashback?.category_id ?? null);
      setDebtRate(account.debt_rate ? account.debt_rate.rate.replace(/0+$/, '').replace(/\.$/, '') : '');
      setDebtPer(account.debt_rate?.per ?? 'month');
    } else {
      setType('cash');
      setName('');
      setOpening('');
      setCurrent('');
      setColour('#4A90D9');
      setIcon(TYPE_ICON.cash);
      setCounts(true);
      setClosingDay('20');
      setDueDay('5');
      setLimit('');
      setOwnLimit('');
      setLag('3');
      setInterest(null);
      setCashbackRate('');
      setCashbackCategory(null);
      setDebtRate('');
      setDebtPer('month');
    }
  }, [open, account]);

  const chooseKind = (kind: AccountKind) => {
    setType(kind.type);
    setSubtype(kind.subtype);
    setIcon(kind.icon ?? TYPE_ICON[kind.type]);
    setCounts(COUNTS_BY_DEFAULT[kind.type]);
    setExample(kind.example);
    setKindLabel({ label: kind.label, hint: kind.hint });
    setPicked(true);
  };

  const save = async (action?: BalanceAction) => {
    setBusy(true);
    setError(null);
    try {
      const draft: AccountDraft = {
        name: name.trim(),
        type,
        subtype,
        colour,
        icon,
        counts_in_cash_on_hand: counts,
        counts_in_net_worth: inNetWorth,
        ...(type === 'credit'
          ? {
              statement_closing_day: Number(closingDay) || 1,
              payment_due_day: Number(dueDay) || 1,
              credit_limit: limit.trim() ? toDecimalString(limit.trim()) : null,
              spending_limit: ownLimit.trim() ? toDecimalString(ownLimit.trim()) : null,
              // Empty keeps what the card has (or the default for a new one).
              ...(lag.trim() ? { posting_lag_days: Number(lag) } : {}),
            }
          : {}),
        // ACC-37. Sent whole, or null to turn it off; the server keeps the
        // marker and the carry, so saving the same terms changes nothing.
        ...(EARNS_INTEREST.includes(type)
          ? { interest: interest && interest.category_id ? cleanInterest(interest) : null }
          : {}),
        // ACC-38. A rate with somewhere to land, or nothing at all.
        ...(GIVES_CASHBACK.includes(type)
          ? {
              cashback: cashbackRate.trim() && cashbackCategory
                ? { rate: toRateString(cashbackRate), category_id: cashbackCategory }
                : null,
            }
          : {}),
        // REC-35. As the bank shows it, or null for none.
        ...(isOwed(type)
          ? { debt_rate: debtRate.trim() ? { rate: toRateString(debtRate), per: debtPer } : null }
          : {}),
      };
      if (!account) {
        const typed = toDecimalString(opening.trim() || '0');
        // A loan's opening is typed as what you owe, and stored as the minus it is (ACC-31).
        draft.opening_balance = type === 'borrowed' && !/^-?0+(\.0+)?$/.test(typed) ? negate(typed) : typed;
      } else if (current.trim()) {
        const typed = toDecimalString(current.trim());
        const balance = isOwed(type) ? negate(typed) : typed;
        if (balance !== account.balance) {
          draft.balance = balance;
          if (action) {
            draft.balance_action = action;
            draft.balance_note = balanceNote.trim() || null;
          }
        }
      }
      if (account) await updateAccount(account.id, draft);
      else await createAccount(draft);
      // ACC-29/ACC-12: a typed balance or value can write an unrecorded gain or
      // loss, which belongs on Home, in Stats and in the ledger. Owned here, so
      // no screen opening this sheet has to remember it.
      afterWrite(...MONEY);
      onSaved();
      onClose();
    } catch (e) {
      const asked = balanceQuestion(e);
      if (asked) {
        setQuestion(asked);
      } else {
        // A failure before the request left the browser has no server message;
        // log it so the next one is not invisible.
        if (!(e instanceof ApiError)) console.error('AccountSheet save failed', e);
        setError(e instanceof ApiError ? e.message : 'That did not save. Try again.');
      }
      setBusy(false);
    }
  };

  const cancelQuestion = () => {
    setQuestion(null);
    setBalanceNote('');
    if (account) setCurrent(shownBalance(account));
  };

  const archive = async () => {
    if (!account) return;
    setBusy(true);
    try {
      await setArchived(account.id, !account.archived);
      afterWrite(...MONEY);
      onSaved();
      onClose();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'That did not save. Try again.');
      setBusy(false);
    }
  };

  if (question) {
    // ACC-28. The balance is worked out from transactions, so the change has to be one of these.
    const loss = question.difference.startsWith('-');
    const shown = (v: string) => (isOwed(type) ? negate(v) : v);
    return (
      <Sheet open={open} onClose={onClose} title="Record the difference?">
        <div className="space-y-4 pb-2">
          <div className="rounded-card border-2 border-stroke bg-surface-2 p-4 text-center">
            <p className="text-footnote text-ink-2">
              {name.trim()}
              {isOwed(type) ? ' · amount owed' : ''}
            </p>
            <p className="num mt-1 text-headline">
              {formatPHP(shown(question.before))} → {formatPHP(shown(question.after))}
            </p>
            <p className={`num mt-1 text-footnote font-semibold ${loss ? 'text-danger' : 'text-ok'}`}>
              Difference {formatPHP(question.difference)}
            </p>
          </div>
          <p className="text-footnote text-ink-2">
            A balance is worked out from your transactions, so this change has to be recorded as something.
          </p>
          <TextField
            label="Note (optional)"
            value={balanceNote}
            onChange={(e) => setBalanceNote(e.target.value)}
            maxLength={280}
            placeholder={type === 'cash' ? 'Counted the wallet' : type === 'investment' ? 'Market moved' : 'Matched the bank app'}
          />

          {error && <p className="text-footnote text-danger">{error}</p>}

          <div>
            <Button block size="lg" onClick={() => void save('adjust')} disabled={busy}>
              Record as unrecorded {loss ? 'loss' : 'gain'}
            </Button>
            <p className="mt-1.5 text-center text-footnote text-ink-3">
              On the ledger from today, with a record of before and after. Your budget stays the same.
            </p>
          </div>
          <div>
            <Button variant="secondary" block onClick={() => void save('fix_opening')} disabled={busy}>
              {type === 'investment' ? 'Fix the starting value instead' : 'Fix the opening balance instead'}
            </Button>
            <p className="mt-1.5 text-center text-footnote text-ink-3">
              For a mistake made when you set the account up. Every past balance shifts, and no record is kept.
            </p>
          </div>
          <Button variant="ghost" block onClick={cancelQuestion} disabled={busy}>
            Cancel
          </Button>
        </div>
      </Sheet>
    );
  }

  if (!editing && !picked) {
    // Type first: it decides what everything after means.
    return (
      <Sheet open={open} onClose={onClose} title="Add account">
        <div className="space-y-4 pb-2">
          {ACCOUNT_KINDS.map(({ group, items }) => (
            <section key={group}>
              <h3 className="px-1 pb-1.5 text-footnote font-semibold text-accent-ink">{group}</h3>
              <div className="divide-y divide-stroke/80 overflow-hidden rounded-card border-2 border-stroke bg-surface-2">
                {items.map((kind) => (
                  <button key={kind.subtype} type="button" onClick={() => chooseKind(kind)}
                    className="flex min-h-14 w-full items-center gap-3 px-4 py-2.5 text-left transition active:bg-line">
                    <GlyphTile icon={kind.icon} colour={colour} size={36} />
                    <span className="min-w-0 flex-1">
                      <span className="block text-body">{kind.label}</span>
                      <span className="block truncate text-footnote text-ink-3">{kind.hint}</span>
                    </span>
                  </button>
                ))}
              </div>
            </section>
          ))}
        </div>
      </Sheet>
    );
  }

  return (
    <Sheet open={open} onClose={onClose} title={editing ? 'Edit account' : 'New account'}>
      <div className="space-y-5 pb-2">
        {editing ? (
          <div>
            <p className="mb-1 text-footnote font-semibold text-ink-2">Type · {kindLabelOf(type, subtype)}</p>
            <p className="text-footnote text-ink-3">
              A type cannot change once the account exists — archive it and make a new one.
            </p>
          </div>
        ) : (
          <div className="flex items-center gap-3 rounded-card border-2 border-stroke bg-surface-2 p-3">
            <GlyphTile icon={icon} colour={colour} size={36} />
            <span className="min-w-0 flex-1">
              <span className="block text-body font-medium">{kindLabel?.label ?? kindLabelOf(type, subtype)}</span>
              <span className="block truncate text-footnote text-ink-3">{kindLabel?.hint ?? TYPE_HINT[type]}</span>
            </span>
            <button type="button" onClick={() => setPicked(false)}
              className="min-h-tap rounded-full px-3 text-footnote font-semibold text-accent-ink active:bg-line">
              Change
            </button>
          </div>
        )}

        <TextField
          label="Name"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder={editing ? undefined : example}
          maxLength={60}
          autoComplete="off"
        />

        {editing && type === 'credit' && limitCents > 0 ? (
          // ACC-27. A card is read either way round: what it owes, or what is left to spend on it.
          // Type one and the other follows the limit; both save as the same balance.
          <div className="grid grid-cols-2 gap-3">
            <MoneyField label="Amount owed" value={current} placeholder="0.00" allowNegative onChange={typeOwed} />
            <MoneyField label="Left to spend" value={leftToSpend} placeholder="0.00" allowNegative onChange={typeLeft} />
            <p className="col-span-2 text-footnote text-ink-3">
              Either one — the other follows your {formatPHP(fromCentavos(limitCents))} limit
              {unpaidCents > 0 && `, less the ${formatPHP(fromCentavos(unpaidCents))} of plans still to bill`}. Changing it
              asks how to record the difference.
            </p>
          </div>
        ) : editing ? (
          <MoneyField
            label={balanceWords(type).label}
            value={current}
            onChange={setCurrent}
            allowNegative
            placeholder="0.00"
            hint={balanceWords(type).hint}
          />
        ) : (
          <MoneyField
            label={openingWords(type).label}
            value={opening}
            onChange={setOpening}
            allowNegative={type !== 'borrowed'}
            placeholder="0.00"
            hint={openingWords(type).hint}
          />
        )}

        {type === 'credit' && (
          <div className="space-y-4 rounded-card border-2 border-stroke bg-surface-2 p-4">
            <p className="text-footnote text-ink-2">
              Your card’s cycle runs on its own dates — they have nothing to do with your budget month.
            </p>
            <div className="grid grid-cols-2 gap-3">
              <TextField
                label="Statement closes"
                value={closingDay}
                onChange={(e) => setClosingDay(e.target.value.replace(/\D/g, '').slice(0, 2))}
                inputMode="numeric"
                placeholder="20"
                hint="Day of the month"
              />
              <TextField
                label="Payment due"
                value={dueDay}
                onChange={(e) => setDueDay(e.target.value.replace(/\D/g, '').slice(0, 2))}
                inputMode="numeric"
                placeholder="5"
                hint="Day of the month"
              />
            </div>
            <MoneyField
              label="Credit limit"
              value={limit}
              onChange={(next) => {
                setLimit(next);
                // What is left follows the limit, so a corrected limit does not leave a stale figure.
                const ceiling = cents(next);
                if (ceiling > 0) setLeftToSpend(fromCentavos(ceiling - unpaidCents - cents(current)));
              }}
              placeholder="50000.00"
              hint="What the bank allows. Leave empty if you would rather not track it."
            />
            <MoneyField
              label="Your spending limit"
              value={ownLimit}
              onChange={setOwnLimit}
              placeholder="10000.00"
              hint="Per statement cycle — what you allow yourself. You are warned, never blocked."
            />
            <TextField
              label="Bank posting delay"
              value={lag}
              onChange={(e) => setLag(e.target.value.replace(/\D/g, '').slice(0, 2))}
              inputMode="numeric"
              placeholder="3"
              error={lag.trim() && Number(lag) > 10 ? 'Up to 10 days' : null}
              hint="Days your bank can take to record a purchase, 0–10. When a statement looks short, purchases this close to the closing day are suggested as posted late."
            />
          </div>
        )}

        {type === 'investment' && editing && account && account.valuations.length > 0 && (
          <div className="space-y-2 rounded-card border-2 border-stroke bg-surface-2 p-4">
            <p className="text-footnote text-ink-2">Values typed before — money moved in or out since is added to the last one.</p>
            {(
              <ul className="space-y-1 text-footnote text-ink-2">
                {[...account.valuations].reverse().slice(0, 4).map((entry) => (
                  <li key={`${entry.on}-${entry.value}`} className="flex justify-between">
                    <span>{entry.on}</span>
                    <span className="num">{formatPHP(entry.value)}</span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}

        {EARNS_INTEREST.includes(type) && (
          <InterestFields value={interest} onChange={setInterest} saved={account?.interest ?? null}
            categories={incomeCategories} />
        )}

        {GIVES_CASHBACK.includes(type) && incomeCategories.length > 0 && (
          <div className="space-y-2 rounded-card border-2 border-stroke bg-surface-2 p-4">
            <p className="text-footnote font-semibold text-ink-2">Usual cashback</p>
            <div className="flex items-end gap-2">
              <TextField
                className="w-28"
                label="Rate"
                value={cashbackRate}
                onChange={(e) => setCashbackRate(clean(e.target.value).replace('-', ''))}
                inputMode="decimal"
                placeholder="2"
                trailing={<span className="pr-3.5 text-footnote text-ink-3">%</span>}
              />
              <select
                value={cashbackCategory ?? ''}
                onChange={(e) => setCashbackCategory(Number(e.target.value) || null)}
                aria-label="Cashback category"
                className="min-h-12 min-w-0 flex-1 rounded-xl border-2 border-stroke bg-surface px-3 text-body"
              >
                <option value="">Lands in…</option>
                {incomeCategories.map((c) => (
                  <option key={c.id} value={c.id}>{c.parent_id ? `  ${c.name}` : c.name}</option>
                ))}
              </select>
            </div>
            <p className="text-footnote text-ink-3">
              Only a suggestion: every purchase on this account offers this much back, and you can change or clear it there.
            </p>
          </div>
        )}

        {isOwed(type) && (
          <div className="space-y-2 rounded-card border-2 border-stroke bg-surface-2 p-4">
            <p className="text-footnote font-semibold text-ink-2">Interest it charges</p>
            <div className="flex items-end gap-2">
              <TextField
                className="w-28"
                label="Rate"
                value={debtRate}
                onChange={(e) => setDebtRate(clean(e.target.value).replace('-', ''))}
                inputMode="decimal"
                placeholder={debtPer === 'month' ? '3' : '24'}
                trailing={<span className="pr-3.5 text-footnote text-ink-3">%</span>}
              />
              <div className="min-w-0 flex-1">
                <Segmented<'month' | 'year'>
                  label="Rate per"
                  value={debtPer}
                  onChange={setDebtPer}
                  options={[{ value: 'month', label: 'a month' }, { value: 'year', label: 'a year' }]}
                />
              </div>
            </div>
            <p className="text-footnote text-ink-3">
              As the bank shows it. Only Pay off debts reads it, to put the dearest debt first and estimate the
              interest — nothing is ever charged from it. Leave it empty on an installment plan whose interest is
              already in its payments.
            </p>
          </div>
        )}

        <div>
          <p className="mb-2 text-footnote font-semibold text-ink-2">Colour</p>
          <ColourPicker value={colour} onChange={setColour} />
        </div>

        <div>
          <p className="mb-2 text-footnote font-semibold text-ink-2">Icon</p>
          <IconPicker value={icon} onChange={setIcon} colour={colour} names={ACCOUNT_GLYPHS} />
        </div>

        <Toggle
          checked={counts}
          onChange={setCounts}
          label="Count in cash on hand"
          hint={
            type === 'credit'
              ? 'What you have already spent on the card is subtracted.'
              : type === 'investment'
                ? 'Off by default — money you cannot spend today.'
                : type === 'lent'
                  ? 'Off by default — it is not in your pockets until it comes back.'
                  : type === 'borrowed'
                    ? 'Off by default — like an installment, it is money you owe later.'
                    : 'Include this balance in the headline number.'
          }
        />

        <Toggle
          checked={inNetWorth}
          onChange={setInNetWorth}
          label="Count in net worth"
          hint="Include this account in the grand total. Turn it off for money you don’t want to count on."
        />

        {error && <p className="text-footnote text-danger">{error}</p>}

        <Button
          block
          size="lg"
          onClick={() => void save()}
          disabled={busy || !name.trim() || (type === 'credit' && Number(lag || '0') > 10)}
        >
          {editing ? 'Save changes' : 'Add account'}
        </Button>

        {editing && (
          <>
            <Button variant="ghost" block onClick={() => void archive()} disabled={busy}>
              {account?.archived ? 'Bring back' : 'Archive'}
            </Button>
            <p className="pb-2 text-center text-footnote text-ink-3">
              Accounts are archived, never deleted — your history points at them.
            </p>
          </>
        )}
      </div>
    </Sheet>
  );
}
