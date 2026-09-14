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
  TYPE_HINT,
  TYPE_ICON,
  TYPE_LABEL,
  addValuation,
  balanceQuestion,
  createAccount,
  setArchived,
  updateAccount,
  type Account,
  type AccountDraft,
  type AccountType,
  type BalanceAction,
  type BalanceQuestion,
} from '../lib/accounts';
import { formatPHP, toDecimalString } from '../lib/money';
import { ColourPicker, GlyphTile, IconPicker } from './StylePicker';
import { ACCOUNT_GLYPHS } from './Glyph';
import { Button } from './ui/Button';
import { Sheet } from './ui/Sheet';
import { TextField } from './ui/TextField';
import { Toggle } from './ui/Toggle';

const TYPES: AccountType[] = ['cash', 'debit', 'credit', 'savings', 'investment'];

const COUNTS_BY_DEFAULT: Record<AccountType, boolean> = {
  cash: true, debit: true, savings: true, credit: true, investment: false,
};

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
  const [closingDay, setClosingDay] = useState('');
  const [dueDay, setDueDay] = useState('');
  const [limit, setLimit] = useState('');
  const [ownLimit, setOwnLimit] = useState('');
  const [lag, setLag] = useState('3');
  const [value, setValue] = useState('');
  const [question, setQuestion] = useState<BalanceQuestion | null>(null);
  const [balanceNote, setBalanceNote] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  /** What the balance field shows for an account: a card's balance as the amount owed. */
  const shownBalance = (a: Account) => (a.type === 'credit' ? negate(a.balance) : a.balance);

  useEffect(() => {
    if (!open) return;
    setError(null);
    setBusy(false);
    setValue('');
    setQuestion(null);
    setBalanceNote('');
    if (account) {
      setType(account.type);
      setName(account.name);
      setOpening(account.opening_balance);
      setCurrent(shownBalance(account));
      setColour(account.colour);
      setIcon(account.icon);
      setCounts(account.counts_in_cash_on_hand);
      setClosingDay(account.credit ? String(account.credit.statement_closing_day) : '');
      setDueDay(account.credit ? String(account.credit.payment_due_day) : '');
      setLimit(account.credit?.limit ?? '');
      setOwnLimit(account.credit?.spending_limit ?? '');
      setLag(account.credit ? String(account.credit.posting_lag_days) : '3');
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
    }
  }, [open, account]);

  const chooseType = (next: AccountType) => {
    setType(next);
    setIcon(TYPE_ICON[next]);
    setCounts(COUNTS_BY_DEFAULT[next]);
  };

  const save = async (action?: BalanceAction) => {
    setBusy(true);
    setError(null);
    try {
      const draft: AccountDraft = {
        name: name.trim(),
        type,
        colour,
        icon,
        counts_in_cash_on_hand: counts,
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
      };
      if (!account || type === 'investment') {
        draft.opening_balance = toDecimalString(opening.trim() || '0');
      } else if (current.trim()) {
        const typed = toDecimalString(current.trim());
        const balance = type === 'credit' ? negate(typed) : typed;
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
      onSaved();
      onClose();
    } catch (e) {
      const asked = balanceQuestion(e);
      if (asked) {
        setQuestion(asked);
      } else {
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
      onSaved();
      onClose();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'That did not save. Try again.');
      setBusy(false);
    }
  };

  const recordValue = async () => {
    if (!account || !value.trim()) return;
    setBusy(true);
    setError(null);
    try {
      await addValuation(account.id, toDecimalString(value.trim()));
      setValue('');
      onSaved();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'That did not save. Try again.');
    }
    setBusy(false);
  };

  if (question) {
    // ACC-28. The balance is worked out from transactions, so the change has to be one of these.
    const loss = question.difference.startsWith('-');
    const shown = (v: string) => (type === 'credit' ? negate(v) : v);
    return (
      <Sheet open={open} onClose={onClose} title="Record the difference?">
        <div className="space-y-4 pb-2">
          <div className="rounded-2xl bg-surface-2 p-4 text-center">
            <p className="text-footnote text-ink-2">
              {name.trim()}
              {type === 'credit' ? ' · amount owed' : ''}
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
            placeholder={type === 'cash' ? 'Counted the wallet' : 'Matched the bank app'}
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
              Fix the opening balance instead
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

  return (
    <Sheet open={open} onClose={onClose} title={editing ? 'Edit account' : 'New account'}>
      <div className="space-y-5 pb-2">
        {/* Type first: it decides what everything below means. */}
        <fieldset disabled={editing}>
          <legend className="mb-2 text-footnote font-semibold text-ink-2">
            {editing ? `Type · ${TYPE_LABEL[type]}` : 'What kind of account?'}
          </legend>
          {editing ? (
            <p className="text-footnote text-ink-3">
              A type cannot change once the account exists — archive it and make a new one.
            </p>
          ) : (
            <div className="grid grid-cols-5 gap-2">
              {TYPES.map((option) => (
                <button
                  key={option}
                  type="button"
                  onClick={() => chooseType(option)}
                  aria-pressed={type === option}
                  className={[
                    'flex flex-col items-center gap-1.5 rounded-xl py-2.5 transition',
                    type === option ? 'bg-accent-soft text-accent' : 'bg-surface-2 text-ink-2 active:bg-line',
                  ].join(' ')}
                >
                  <GlyphTile icon={TYPE_ICON[option]} colour={type === option ? colour : '#8E8E93'} size={32} />
                  <span className="text-caption leading-tight">{TYPE_LABEL[option]}</span>
                </button>
              ))}
            </div>
          )}
          {!editing && <p className="mt-2 text-footnote text-ink-3">{TYPE_HINT[type]}</p>}
        </fieldset>

        <TextField
          label="Name"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="BPI Debit"
          maxLength={60}
          autoComplete="off"
        />

        {editing && type !== 'investment' ? (
          <TextField
            label={type === 'credit' ? 'Amount owed' : 'Current balance'}
            value={current}
            onChange={(e) => setCurrent(clean(e.target.value))}
            inputMode="decimal"
            placeholder="0.00"
            hint={
              type === 'credit'
                ? 'What the card owes right now. Changing it asks how to record the difference.'
                : 'What is really in it right now. Changing it asks how to record the difference.'
            }
          />
        ) : (
          <TextField
            label={type === 'investment' ? 'Starting value' : 'Opening balance'}
            value={opening}
            onChange={(e) => setOpening(clean(e.target.value))}
            inputMode="decimal"
            placeholder="0.00"
            hint={
              type === 'investment'
                ? 'What it was worth when you started tracking it.'
                : type === 'credit'
                  ? 'What you already owe on it, as a minus — −8,420.00.'
                  : 'What was in it before you started tracking.'
            }
          />
        )}

        {type === 'credit' && (
          <div className="space-y-4 rounded-2xl bg-surface-2 p-4">
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
            <TextField
              label="Credit limit"
              value={limit}
              onChange={(e) => setLimit(clean(e.target.value))}
              inputMode="decimal"
              placeholder="50,000.00"
              hint="What the bank allows. Leave empty if you would rather not track it."
            />
            <TextField
              label="Your spending limit"
              value={ownLimit}
              onChange={(e) => setOwnLimit(clean(e.target.value).replace('-', ''))}
              inputMode="decimal"
              placeholder="10,000.00"
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

        {type === 'investment' && editing && (
          <div className="space-y-3 rounded-2xl bg-surface-2 p-4">
            <p className="text-footnote text-ink-2">
              Type what it is worth today. Each value is kept with its date, and none of it counts as income.
            </p>
            <TextField
              label="Value today"
              value={value}
              onChange={(e) => setValue(clean(e.target.value))}
              inputMode="decimal"
              placeholder={account?.current_value ?? '0.00'}
            />
            <Button variant="secondary" block onClick={() => void recordValue()} disabled={busy || !value.trim()}>
              Record value
            </Button>
            {account && account.valuations.length > 0 && (
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
                : 'Include this balance in the headline number.'
          }
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
