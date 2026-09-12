/**
 * Add or edit one account (ACC-01..ACC-18).
 *
 * Two things this form does deliberately:
 *
 *  - The TYPE is chosen first and, once the account exists, cannot change.
 *    The type decides what a balance means, so changing it later would
 *    silently reinterpret every transaction already recorded against it. The
 *    server refuses; the form says so rather than letting you try.
 *  - Credit terms and the investment value only appear on the types that have
 *    them. A closing day on a cash account is a field nothing reads.
 *
 * Amounts are typed as text and sent as text. Nothing here calls Number().
 */
import { useEffect, useState } from 'react';
import { ApiError } from '../lib/api';
import {
  TYPE_HINT,
  TYPE_ICON,
  TYPE_LABEL,
  addValuation,
  createAccount,
  setArchived,
  updateAccount,
  type Account,
  type AccountType,
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

/** Keep only what an amount can contain, and only one decimal point. */
function clean(input: string): string {
  const [whole = '', ...rest] = input.replace(/[^\d.]/g, '').split('.');
  return rest.length ? `${whole}.${rest.join('').slice(0, 2)}` : whole;
}

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
  const [colour, setColour] = useState('#4A90D9');
  const [icon, setIcon] = useState('cash');
  const [counts, setCounts] = useState(true);
  const [closingDay, setClosingDay] = useState('');
  const [dueDay, setDueDay] = useState('');
  const [limit, setLimit] = useState('');
  const [value, setValue] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!open) return;
    setError(null);
    setBusy(false);
    setValue('');
    if (account) {
      setType(account.type);
      setName(account.name);
      setOpening(account.opening_balance);
      setColour(account.colour);
      setIcon(account.icon);
      setCounts(account.counts_in_cash_on_hand);
      setClosingDay(account.credit ? String(account.credit.statement_closing_day) : '');
      setDueDay(account.credit ? String(account.credit.payment_due_day) : '');
      setLimit(account.credit?.limit ?? '');
    } else {
      setType('cash');
      setName('');
      setOpening('');
      setColour('#4A90D9');
      setIcon(TYPE_ICON.cash);
      setCounts(true);
      setClosingDay('20');
      setDueDay('5');
      setLimit('');
    }
  }, [open, account]);

  const chooseType = (next: AccountType) => {
    setType(next);
    setIcon(TYPE_ICON[next]);
    setCounts(COUNTS_BY_DEFAULT[next]);
  };

  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      const draft = {
        name: name.trim(),
        type,
        opening_balance: toDecimalString(opening.trim() || '0'),
        colour,
        icon,
        counts_in_cash_on_hand: counts,
        ...(type === 'credit'
          ? {
              statement_closing_day: Number(closingDay) || 1,
              payment_due_day: Number(dueDay) || 1,
              credit_limit: limit.trim() ? toDecimalString(limit.trim()) : null,
            }
          : {}),
      };
      if (account) await updateAccount(account.id, draft);
      else await createAccount(draft);
      onSaved();
      onClose();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'That did not save. Try again.');
      setBusy(false);
    }
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

        <TextField
          label={type === 'investment' ? 'Starting value' : 'Opening balance'}
          value={opening}
          onChange={(e) => setOpening(clean(e.target.value))}
          inputMode="decimal"
          placeholder="0.00"
          hint={
            type === 'investment'
              ? 'What it was worth when you started tracking it.'
              : 'What was in it before you started tracking.'
          }
        />

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
              hint="Leave empty if you would rather not track it."
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

        <Button block size="lg" onClick={() => void save()} disabled={busy || !name.trim()}>
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
