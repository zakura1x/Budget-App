/**
 * The add-transaction sheet - the most important screen in the app (TXN-01).
 *
 * The target is two taps and a number: the sheet opens with the numpad up and
 * the account already chosen, so an expense is a category chip and the digits.
 * Everything else is one tap away and never in the way:
 *
 *  - Category chips scroll sideways, most-used first (TXN-05). MAIN categories
 *    only: choose one and its sub-categories appear under it, to take or leave.
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
 *
 * MERCHANT (TXN-08/24, 2026-09-28, user: a Merchant tile beside Add note) is
 * an extra like the rest. Typing offers the merchants used before, most used
 * first; picking one fills the category it was filed under LAST time - but
 * only when no category is chosen yet, so a suggestion never overrides you.
 * An edit sends the merchant back as shown, so an imported or recurring
 * entry's merchant is no longer wiped by saving it.
 */
import { useEffect, useMemo, useRef, useState } from 'react';
import { ApiError } from '../lib/api';
import { untracked, untrackedCash, visible, UNTRACKED_ID, type Account } from '../lib/accounts';
import { flatten, type Category } from '../lib/categories';
import { ensureAccounts, ensureCategories, ensureMerchants, ensureTags } from '../lib/prefetch';
import {
  applyAmountKey,
  centavos,
  formatPHP,
  fromCentavos,
  percentOf,
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
  type Merchant,
  type TransactionDraft,
} from '../lib/transactions';
import { afterWrite, MONEY } from '../lib/invalidate';
import { convertPurchase, createPurchaseWithPlan } from '../lib/recurring';
import { type Tag } from '../lib/tags';
import { useLedgerStore } from '../stores/ledgerStore';
import { useUiStore, type RuleSheetRequest } from '../stores/uiStore';
import { EMPTY_CHOICE, InstallmentFields, termsOf, type InstallmentChoice } from './InstallmentFields';
import { CashbackIcon, CloseIcon, InstallmentsIcon, NoteIcon, SplitIcon, StoreIcon, TagIcon } from './Icons';
import { ReceiptControl } from './ReceiptControl';
import { DEFAULT_COLOUR, GlyphTile, PALETTE } from './StylePicker';
import { offerUndo } from './UndoToast';
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

/**
 * One of the sheet's optional extras - Add note, Tags, Split, Installments,
 * Cashback, Repeat last entry.
 *
 * They used to be coloured TEXT, and read as labels rather than as things you
 * could tap (user, 2026-09-20: "the add note, split, cashback does not feel
 * like a button - it's like a text in the design"). Every one is now an
 * outlined tile on a hard offset shadow that sinks when pressed - the same
 * neo-brutalist control as every other button in the app (`press`).
 */
function SheetAction({
  label,
  icon,
  onClick,
  children,
  tone = 'accent',
}: {
  /** What it does, for the screen reader and the long-press tooltip - the icon carries it visually. */
  label: string;
  icon: React.ReactNode;
  onClick: () => void;
  /** Text worth keeping beside the icon - the cashback figure, the two wordy actions. */
  children?: React.ReactNode;
  /**
   * `quiet` is the way OUT of something you opened - close the note, clear the
   * tags, stop splitting, remove the cashback. It is the same tile, so it can
   * be seen and hit (user, 2026-09-20: "the buttons of close or remove of that
   * data is not much visible" - they were bare grey words); only the ink is
   * calmer, so a cancel never competes with the action beside it.
   */
  tone?: 'accent' | 'quiet';
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={label}
      title={label}
      className={[
        'press flex h-tap shrink-0 items-center justify-center gap-1.5 rounded-xl bg-surface',
        tone === 'quiet' ? 'text-ink-2' : 'text-accent-ink',
        children ? 'px-3 text-footnote font-bold' : 'w-tap',
      ].join(' ')}
    >
      {icon}
      {children}
    </button>
  );
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
        // A stored colour is a bright fill made for a black label (StylePicker's set, 2026-09-18).
        selected ? `${colour ? 'text-black' : 'bg-accent text-on-accent'} font-bold shadow-edge` : 'bg-surface text-ink-2 shadow-edge active:bg-surface-2',
      ].join(' ')}
      style={selected && colour ? { backgroundColor: colour } : undefined}
    >
      {children}
    </button>
  );
}

/**
 * REC-31. What "Recurring" on the + button offers. Each opens the rule sheet
 * already set up - on the account the sheet was opened for, and a card
 * payment as a monthly transfer into the first card.
 */
function RepeatingChoices({
  accounts,
  accountId,
  onChoose,
}: {
  accounts: Account[];
  accountId: number | null;
  onChoose: (request: RuleSheetRequest) => void;
}) {
  const active = accounts.filter((a) => !a.archived);
  const chosen = active.find((a) => a.id === accountId);
  const card = chosen?.type === 'credit' ? chosen : active.find((a) => a.type === 'credit');
  const payer = active.find((a) => a.type !== 'credit' && a.type !== 'borrowed' && a.type !== 'lent');
  const on = chosen?.id ?? payer?.id;
  const choices: { title: string; hint: string; icon: string; colour: string; request: RuleSheetRequest }[] = [
    { title: 'Bill or income', hint: 'Rent, salary, an allowance, a monthly transfer', icon: 'home', colour: PALETTE[5] ?? DEFAULT_COLOUR,
      request: { kind: 'standard', rule: null, prefill: { kind: 'standard', type: 'expense', account_id: on } } },
    { title: 'Subscription', hint: 'Netflix, Spotify, a gym — with a reminder', icon: 'play', colour: PALETTE[8] ?? DEFAULT_COLOUR,
      request: { kind: 'subscription', rule: null, prefill: { kind: 'subscription', type: 'expense', account_id: on } } },
    { title: 'Installment', hint: 'A purchase paid over months, like a phone on a card', icon: 'credit-card', colour: PALETTE[6] ?? DEFAULT_COLOUR,
      request: { kind: 'installment', rule: null, prefill: { kind: 'installment', type: 'expense', account_id: card?.id ?? on } } },
  ];
  if (card && payer) {
    choices.push({
      title: 'Credit card payment', hint: `What you pay ${card.name} every month`, icon: 'undo', colour: PALETTE[3] ?? DEFAULT_COLOUR,
      request: { kind: 'standard', rule: null, prefill: {
        kind: 'standard', type: 'transfer', name: `${card.name} payment`, account_id: payer.id,
        counter_account_id: card.id, frequency: 'monthly', start: card.credit?.payment_due ?? localToday(),
      } },
    });
  }
  return (
    <div className="space-y-2 pb-2">
      <p className="px-1 text-footnote text-ink-2">Set it up once — it records itself on its day, and shows in Months ahead.</p>
      <div className="divide-y divide-stroke/80 overflow-hidden rounded-card border-2 border-stroke bg-surface-2">
        {choices.map((choice) => (
          <button key={choice.title} type="button" onClick={() => onChoose(choice.request)}
            className="flex min-h-14 w-full items-center gap-3 px-4 py-3 text-left transition active:bg-line">
            <GlyphTile icon={choice.icon} colour={choice.colour} size={40} />
            <span className="min-w-0 flex-1">
              <span className="block text-body font-medium">{choice.title}</span>
              <span className="block truncate text-footnote text-ink-3">{choice.hint}</span>
            </span>
          </button>
        ))}
      </div>
    </div>
  );
}

export function TransactionSheet() {
  const open = useUiStore((s) => s.addSheetOpen);
  const editing = useUiStore((s) => s.editing);
  const close = useUiStore((s) => s.closeAddSheet);
  const addOn = useUiStore((s) => s.addOn);
  const addPreset = useUiStore((s) => s.addPreset);
  const ledger = useLedgerStore();

  const [kind, setKind] = useState<EntryType>('expense');
  /** REC-31: "Recurring" chosen - the sheet shows what can repeat instead of the numpad. */
  const [repeating, setRepeating] = useState(false);
  const openRuleSheet = useUiStore((s) => s.openRuleSheet);
  const [typed, setTyped] = useState('0');
  const [categoryId, setCategoryId] = useState<number | null>(null);
  const [accountId, setAccountId] = useState<number | null>(null);
  const [counterId, setCounterId] = useState<number | null>(null);
  const [txnDate, setTxnDate] = useState(localToday());
  const [note, setNote] = useState('');
  const [showNote, setShowNote] = useState(false);
  /** TXN-24. The merchant, and the ones typed before that it can be picked from. */
  const [merchant, setMerchant] = useState('');
  const [showMerchant, setShowMerchant] = useState(false);
  const [merchants, setMerchants] = useState<Merchant[]>([]);
  /** Focused when the tile is TAPPED - not when an edit opens with a merchant, or the keyboard would cover the numpad. */
  const merchantInput = useRef<HTMLInputElement>(null);
  const [splitting, setSplitting] = useState(false);
  const [lines, setLines] = useState<SplitLine[]>([]);
  const [accounts, setAccounts] = useState<Account[]>([]);
  /** ACC-39. The wallet, if it has been made; null until the first loan is saved from it. */
  const [wallet, setWallet] = useState<Account | null>(null);
  const [tree, setTree] = useState<Category[]>([]);
  const [tags, setTags] = useState<Tag[]>([]);
  const [tagIds, setTagIds] = useState<number[]>([]);
  const [showTags, setShowTags] = useState(false);
  /** TXN-22. What this purchase pays back, typed or suggested by the card's own rate. */
  const [cashback, setCashback] = useState('');
  const [cashbackOn, setCashbackOn] = useState<string | null>(null);
  const [cashbackTo, setCashbackTo] = useState<number | null>(null);
  const [cashbackCategory, setCashbackCategory] = useState<number | null>(null);
  const [cashbackRate, setCashbackRate] = useState<string | null>(null);
  const [showCashback, setShowCashback] = useState(false);
  /** REC-34. This purchase paid in installments instead: the plan replaces it. */
  const [showPlan, setShowPlan] = useState(false);
  const [plan, setPlan] = useState<InstallmentChoice>(EMPTY_CHOICE);
  const [planReady, setPlanReady] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // Load what the chips need, and set the sheet up, every time it opens.
  useEffect(() => {
    if (!open) return;
    setError(null);
    setBusy(false);
    setShowPlan(false);
    setPlan(EMPTY_CHOICE);
    setPlanReady(false);
    let cancelled = false;
    // From the cache when it is warm, which after an unlock it always is: the
    // [+] button used to cost three requests every time it was tapped.
    // TXN-24. Suggestions are a convenience: if they cannot be had, the sheet works without them.
    Promise.all([ensureAccounts(), ensureCategories(), ensureTags(), ensureMerchants().catch(() => [] as Merchant[])])
      .then(([accountList, categories, tagList, merchantList]) => {
        if (cancelled) return;
        setMerchants(merchantList);
        // ACC-39. The wallet is not one of the accounts this sheet offers ANYWHERE
        // - not a chip, not a cashback destination, not a rule's payer. It is
        // reached only by leaving a loan's side blank.
        const active = visible(accountList.accounts).filter((a) => !a.archived || a.id === editing?.account_id);
        setAccounts(active);
        const theWallet = untracked(accountList.accounts);
        setWallet(theWallet);
        if (editing && theWallet) {
          // ACC-39. A leg already on the wallet reads back as BLANK, because
          // that is how it was typed: the row shows nothing picked and the line
          // under it says why. Saving sends it straight back to the wallet.
          const blank = (id: number | null) => (id === theWallet.id ? null : id);
          setAccountId(blank);
          setCounterId(blank);
        }
        setTree(categories);
        setTags(tagList);
        if (!editing) {
          // The screen that opened the sheet may know the account ("a purchase I
          // forgot" on a card); otherwise the account you used last is the one.
          const preset = addPreset?.accountId;
          const into = active.some((a) => a.id === addPreset?.counterAccountId) ? addPreset?.counterAccountId : undefined;
          // ACC-31/39. Lend more, Paid back, Borrow more, Pay back: the side the
          // page knows is filled and the OTHER side starts BLANK (user,
          // 2026-09-20 - "much better to be default than picking the last-used").
          // A guessed account here is a withdrawal from an account you never
          // chose, and the money for a loan often comes from cash instead.
          const lending = [preset, into].some((id) => {
            const type = active.find((a) => a.id === id)?.type;
            return type === 'lent' || type === 'borrowed';
          });
          const recent = ledger.items.find((row) => row.id > 0)?.account_id;
          const chosen = [preset, recent].find((id) => id !== undefined && id !== into && active.some((a) => a.id === id));
          const known = active.some((a) => a.id === preset) ? preset ?? null : null;
          const from = lending ? known : chosen ?? active.find((a) => a.id !== into)?.id ?? null;
          setAccountId(from);
          setCounterId(into ?? (lending ? null : active.find((a) => a.id !== from)?.id ?? null));
        }
      })
      .catch((e: Error) => !cancelled && setError(e.message));

    if (editing) {
      setKind(editing.type === 'adjustment' ? 'expense' : editing.type);
      setTyped(typedFrom(editing.amount));
      setTxnDate(editing.txn_date);
      setNote(editing.notes ?? '');
      setShowNote(Boolean(editing.notes));
      setMerchant(editing.merchant ?? '');
      setShowMerchant(Boolean(editing.merchant));
      setTagIds(editing.tag_ids ?? []);
      setShowTags((editing.tag_ids ?? []).length > 0);
      setCashback(editing.cashback ? typedFrom(editing.cashback.amount) : '');
      setCashbackOn(editing.cashback?.on ?? null);
      setCashbackTo(editing.cashback?.account_id ?? null);
      setCashbackCategory(editing.cashback?.category_id ?? null);
      setCashbackRate(editing.cashback?.rate ?? null);
      setShowCashback(Boolean(editing.cashback));
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
      setKind(addPreset?.type ?? 'expense');
      setRepeating(false);
      setTyped(addPreset?.amount ? typedFrom(addPreset.amount) : '0');
      setCategoryId(null);
      setTxnDate(addOn ?? localToday());
      setNote('');
      setShowNote(false);
      setMerchant('');
      setShowMerchant(false);
      setTagIds([]);
      setShowTags(false);
      setSplitting(false);
      setLines([]);
      setCashback('');
      setCashbackOn(null);
      setCashbackTo(null);
      setCashbackCategory(null);
      setCashbackRate(null);
      setShowCashback(false);
    }
    return () => {
      cancelled = true;
    };
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

  /**
   * TXN-05. The row offers MAIN categories only; the sub-categories of the one
   * chosen appear under it, and picking one is optional - a main category on
   * its own is a complete answer. Ordered by how much the whole branch is used,
   * so a main whose children you use constantly comes first.
   */
  const mains = useMemo(() => {
    if (kind === 'transfer') return [];
    return tree
      .filter((c) => c.kind === kind && !c.archived)
      .map((c, order) => ({ c, order, used: c.usage + c.children.reduce((sum, child) => sum + child.usage, 0) }))
      .sort((a, b) => b.used - a.used || a.order - b.order)
      .map(({ c }) => c);
  }, [tree, kind]);
  /**
   * TXN-24. The merchants worth offering: this kind only (the same shop is
   * rarely both), matching what is typed anywhere in the name, most used first
   * - the server's order. Empty field: the most used. The one already typed
   * exactly is not offered back.
   */
  const merchantMatches = useMemo(() => {
    if (!showMerchant || kind === 'transfer') return [];
    const needle = merchant.trim().toLowerCase();
    return merchants
      .filter((m) => m.type === kind && m.name.toLowerCase() !== needle && (!needle || m.name.toLowerCase().includes(needle)))
      .slice(0, 6);
  }, [showMerchant, kind, merchant, merchants]);

  const pickMerchant = (m: Merchant) => {
    setMerchant(m.name);
    // Only into an empty choice - never over a category you picked yourself.
    if (categoryId === null && !splitting && m.category_id !== null && chips.some((c) => c.id === m.category_id)) {
      setCategoryId(m.category_id);
    }
  };

  const chosenCategory = categoryId !== null ? chips.find((c) => c.id === categoryId) : undefined;
  // A sub-category keeps its main selected, so editing an old entry opens on both rows.
  const mainId = chosenCategory ? chosenCategory.parent_id ?? chosenCategory.id : null;
  const main = mains.find((c) => c.id === mainId);
  const subs = (main?.children ?? []).filter((c) => !c.archived);

  const amount = toDecimalString(typed);
  const amountCents = cents(typed);
  const allocated = lines.reduce((sum, line) => sum + cents(line.amount), 0);
  const remaining = amountCents - allocated;

  /**
   * TXN-22. The account's own rate (ACC-38), if it has one - what the Cashback
   * button offers and what fills the field in. The amount is a suggestion:
   * whatever is in the field when you save is what is recorded.
   */
  const cashbackRule = accounts.find((a) => a.id === accountId)?.cashback ?? null;
  const incomeCategories = useMemo(
    () => flatten(tree).filter((c) => c.kind === 'income' && !c.archived),
    [tree],
  );
  /**
   * TXN-22. Where money back lands, without asking: the account's own rule
   * (ACC-38) if it has one, else the income category that is plainly for this -
   * Cashback, Rebates, Refunds. The ACCOUNT is not asked either: the server
   * files it on the account the purchase was made on, which is what a card
   * actually does. Both are only defaults - the credit is an ordinary income
   * row, so moving it afterwards is an ordinary edit.
   *
   * The picker comes back only when there is nothing sensible to guess, because
   * then a silent answer would file the money under something like Salary.
   */
  const cashbackHome = useMemo(
    () => incomeCategories.find((c) => /cashback|rebate|refund/i.test(c.name)) ?? null,
    [incomeCategories],
  );
  const suggestion = cashbackRule && amountCents > 0 ? percentOf(amount, cashbackRule.rate) : null;

  const cashbackCategoryName =
    incomeCategories.find((c) => c.id === cashbackCategory)?.name ?? null;

  const openCashback = () => {
    setShowCashback(true);
    if (cashback.trim()) return;
    setCashbackCategory(cashbackRule?.category_id ?? cashbackHome?.id ?? null);
    setCashbackRate(cashbackRule?.rate ?? null);
    if (suggestion && suggestion !== '0.00') setCashback(typedFrom(suggestion));
  };

  /** ACC-31. A lent or borrowed account - the two transfers that may come from, or go to, untracked cash. */
  const isLoan = (id: number | null) => {
    const type = accounts.find((a) => a.id === id)?.type;
    return type === 'lent' || type === 'borrowed';
  };

  const startSplit = () => {
    setSplitting(true);
    setLines([
      { key: 1, category_id: categoryId, amount: typed === '0' ? '' : typed },
      { key: 2, category_id: null, amount: '' },
    ]);
  };

  /**
   * ACC-39. On a loan's transfer, LEAVING A SIDE BLANK means the wallet -
   * cash the user does not track (user, 2026-09-20: "if the user did not pick
   * anything from the From options, it will automatically recognize that it
   * comes from My wallet"). Lending out of a pocket is the normal case and
   * naming an account is the exception, so the normal case costs no taps.
   *
   * Only the side OPPOSITE a lent or borrowed account may be blank: everywhere
   * else the money really did leave, or land in, an account you track, and a
   * forgotten chip would be a real mistake rather than an answer.
   */
  const fromIsWallet = kind === 'transfer' && accountId === null && isLoan(counterId);
  const toIsWallet = kind === 'transfer' && counterId === null && isLoan(accountId);

  const problem = (() => {
    if (amountCents <= 0) return 'Type an amount';
    if (accountId === null && !fromIsWallet) return 'Choose an account';
    if (kind === 'transfer') {
      if (counterId === null && !toIsWallet) return 'Choose where the money goes';
      if (counterId !== null && counterId === accountId) return 'Pick two different accounts';
      return null;
    }
    if (splitting) {
      if (lines.some((l) => l.category_id === null || cents(l.amount) <= 0)) return 'Each line needs a category and an amount';
      if (remaining !== 0) return null; // shown live under the lines instead
      return null;
    }
    if (categoryId === null) return 'Choose a category';
    // TXN-22. Only reachable when nothing could be guessed and the picker showed.
    if (showCashback && cents(cashback) > 0 && cashbackCategory === null) return 'Choose where the cashback lands';
    return null;
  })();
  // REC-34. Only a purchase on a card or a loan can be spread - and not one that is already a plan's payment.
  const spreadable = kind === 'expense'
    && ['credit', 'borrowed'].includes(accounts.find((a) => a.id === accountId)?.type ?? '')
    && (!editing || (editing.id > 0 && editing.recurring_id == null));
  const spreading = showPlan && spreadable;
  const canSave = !busy && problem === null && (!splitting || kind === 'transfer' || remaining === 0)
    && (!spreading || planReady);

  const draft = (): TransactionDraft => {
    // ACC-39. A blank side leaves as the wallet's sentinel; `save` turns it into
    // the real hidden account, making it on the server if this is the first one.
    const from = accountId ?? (fromIsWallet ? UNTRACKED_ID : null);
    const to = counterId ?? (toIsWallet ? UNTRACKED_ID : null);
    const base = { type: kind, amount, account_id: from as number, txn_date: txnDate, notes: note.trim() || null };
    if (kind === 'transfer') return { ...base, counter_account_id: to as number };
    // Only ids that still exist - a tag deleted while the sheet was open would be refused.
    const tagged = {
      ...base,
      merchant: merchant.trim() || null,
      tag_ids: tagIds.filter((id) => tags.some((t) => t.id === id)),
    };
    const withCashback = {
      ...tagged,
      // Sent as null only when this entry HAD cashback and no longer does -
      // that is what takes the credit row away (TXN-22).
      ...(kind === 'expense' && showCashback && cents(cashback) > 0
        ? {
            cashback: {
              amount: toDecimalString(cashback),
              category_id: cashbackCategory as number,
              ...(cashbackTo !== null ? { account_id: cashbackTo } : {}),
              ...(cashbackOn ? { on: cashbackOn } : {}),
              ...(cashbackRate ? { rate: cashbackRate } : {}),
            },
          }
        : editing?.cashback
          ? { cashback: null }
          : {}),
    };
    if (splitting) {
      return {
        ...withCashback,
        splits: lines.map((l) => ({ category_id: l.category_id as number, amount: toDecimalString(l.amount) })),
      };
    }
    return { ...withCashback, category_id: categoryId as number };
  };

  /** Everything that shows money reloads: the plan posted payments and hid the purchase. */
  const refreshMoney = () => afterWrite(...MONEY);

  const save = async () => {
    if (!canSave) return;
    let body = draft();

    // ACC-39. The wallet is made on the server the FIRST time a loan is saved
    // from it - never by tapping the chip, so a sheet that is cancelled leaves
    // no account behind. Before the optimistic row, so the ledger never holds
    // an id the server does not know.
    if (body.account_id === UNTRACKED_ID || body.counter_account_id === UNTRACKED_ID) {
      setBusy(true);
      setError(null);
      try {
        const made = await untrackedCash();
        setWallet(made);
        body = {
          ...body,
          account_id: body.account_id === UNTRACKED_ID ? made.id : body.account_id,
          ...(body.counter_account_id === UNTRACKED_ID ? { counter_account_id: made.id } : {}),
        };
      } catch (e) {
        setError(e instanceof ApiError ? e.message : 'That did not save. Try again.');
        setBusy(false);
        return;
      }
      setBusy(false);
    }

    if (spreading) {
      // REC-34. Not optimistic: the purchase becomes a plan, and the server decides what posts.
      setBusy(true);
      setError(null);
      try {
        if (editing) {
          await updateTransaction(editing.id, body); // any edit first, so the plan takes the purchase as shown
          await convertPurchase(editing.id, termsOf(plan));
        } else {
          const { cashback: _dropped, ...purchase } = body as TransactionDraft & { cashback?: unknown };
          await createPurchaseWithPlan(purchase, termsOf(plan));
        }
        refreshMoney();
        close();
      } catch (e) {
        setError(e instanceof ApiError ? e.message : 'That did not save. Try again.');
        setBusy(false);
      }
      return;
    }

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
        merchant: body.merchant ?? null,
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
      offerUndo(editing); // TXN-25
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
          <p className="rounded-card border-2 border-stroke bg-surface-2 px-4 py-3 text-footnote text-ink-2">
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

  /**
   * TXN-01. The screen that opened the sheet often already named the account -
   * the + on SeaBank's own page - and then a row of every account you own is
   * noise below the categories (user, 2026-09-20: "it should already know
   * which account it was being used; I think it is redundant").
   *
   * So it is stated, not asked: one line saying which account this lands on,
   * with Change to bring the row back. A transfer is untouched (its two rows
   * ARE the entry), and an edit always shows the row, because there the
   * account is part of what you came to change.
   */
  /**
   * TXN-01 / ACC-31. The side the screen that opened the sheet already named -
   * hidden, not asked. Paid back and Borrow more know the FROM (this account);
   * Lend more and Pay back know the TO. Showing a picker for the account whose
   * page you are standing on is a row you read past (user, 2026-09-20).
   *
   * Only while it still holds what that screen set: change it and the row
   * comes back, because then it is a choice again.
   */
  const knownAccount =
    !editing && addPreset?.accountId != null && accountId === addPreset.accountId
      ? accounts.find((a) => a.id === accountId)
      : undefined;
  const knownCounter =
    !editing && addPreset?.counterAccountId != null && counterId === addPreset.counterAccountId
      ? accounts.find((a) => a.id === counterId)
      : undefined;
  return (
    <Sheet open={open} onClose={close} title={editing ? 'Edit transaction' : repeating ? 'Something that repeats' : 'New transaction'}>
      <div className="space-y-3">
        {(!editing || editing.type !== 'transfer') && (
          <Segmented<EntryType | 'recurring'>
            label="Type"
            compact={!editing}
            value={repeating ? 'recurring' : kind}
            onChange={(next) => {
              if (next === 'recurring') {
                setRepeating(true);
                return;
              }
              setRepeating(false);
              // A transfer is two rows; the server will not convert one.
              if (editing && (next === 'transfer') !== (editing.type === 'transfer')) return;
              setKind(next);
              setCategoryId(null);
              setSplitting(false);
            }}
            options={[
              { value: 'expense', label: 'Expense' },
              { value: 'income', label: 'Income' },
              ...(!editing ? [{ value: 'transfer' as const, label: 'Transfer' }, { value: 'recurring' as const, label: 'Recurring' }] : []),
            ]}
          />
        )}

        {repeating ? (
          <RepeatingChoices
            accounts={accounts}
            accountId={addPreset?.accountId ?? accountId}
            onChoose={(request) => openRuleSheet(request)}
          />
        ) : (
        <>
        <output
          aria-live="polite"
          className={`num block pt-2 text-center text-display ${kind === 'income' ? 'text-ok' : 'text-ink'}`}
        >
          {formatPHP(amount)}
        </output>

        {canRepeat && (
          <div className="flex justify-center">
            <SheetAction
              label="Repeat last entry"
              icon={<span aria-hidden="true" className="text-body leading-none">↻</span>}
              onClick={() => void repeat()}
            >
              Repeat last entry
            </SheetAction>
          </div>
        )}

        {kind === 'transfer' ? (
          <div className="space-y-2">
            {!knownAccount && (
              <>
                <p className="text-footnote font-semibold text-ink-2">From</p>
                <div className="no-scrollbar -mx-5 flex gap-2 overflow-x-auto px-5 py-1">
                  {/* ACC-39. Tapping the chosen account again clears it - the way a
                      sub-category chip works - so an answer given by mistake can go
                      back to blank, which is the wallet. */}
                  {accountChips(
                    accountId,
                    (id) => setAccountId(accountId === id && isLoan(counterId) ? null : id),
                    counterId,
                  )}
                </div>
              </>
            )}
            {/* ACC-39. The blank answer, spelled out where it is being given -
                never a surprise, and one tap on a chip takes it back. */}
            {fromIsWallet && (
              <p className="text-footnote text-ink-3">
                Nothing picked, so it comes from <span className="font-semibold text-ink-2">
                {wallet?.name ?? 'my wallet'}</span> — cash you don’t track. Only the loan moves.
              </p>
            )}
            {!knownCounter && (
              <>
                <p className="text-footnote font-semibold text-ink-2">To</p>
                <div className="no-scrollbar -mx-5 flex gap-2 overflow-x-auto px-5 py-1">
                  {accountChips(
                    counterId,
                    (id) => setCounterId(counterId === id && isLoan(accountId) ? null : id),
                    accountId,
                  )}
                </div>
              </>
            )}
            {toIsWallet && (
              <p className="text-footnote text-ink-3">
                Nothing picked, so it goes back into <span className="font-semibold text-ink-2">
                {wallet?.name ?? 'my wallet'}</span> — cash you don’t track. Only the loan moves.
              </p>
            )}
          </div>
        ) : (
          <>
            {!splitting && (
              <>
                <div className="no-scrollbar -mx-5 flex gap-2 overflow-x-auto px-5 py-1" role="group" aria-label="Category">
                  {mains.map((c) => (
                    <Chip key={c.id} selected={mainId === c.id} onClick={() => setCategoryId(c.id)} colour={c.colour}>
                      {mainId !== c.id && <GlyphTile icon={c.icon} colour={c.colour} size={24} />}
                      {c.name}
                    </Chip>
                  ))}
                  {mains.length === 0 && (
                    <p className="text-footnote text-ink-3">Add a {kind} category first, under More → Categories.</p>
                  )}
                </div>
                {subs.length > 0 && (
                  <div className="no-scrollbar -mx-5 flex items-center gap-2 overflow-x-auto px-5 py-1"
                    role="group" aria-label={`In ${main?.name}`}>
                    <span className="shrink-0 text-footnote text-ink-3" aria-hidden="true">↳</span>
                    {subs.map((c) => (
                      <Chip
                        key={c.id}
                        selected={categoryId === c.id}
                        colour={c.colour}
                        // Tapping the chosen one again goes back to the main category alone.
                        onClick={() => setCategoryId(categoryId === c.id ? (mainId as number) : c.id)}
                      >
                        {categoryId !== c.id && <GlyphTile icon={c.icon} colour={c.colour} size={24} />}
                        {c.name}
                      </Chip>
                    ))}
                  </div>
                )}
              </>
            )}
            {/* TXN-01. Nothing at all when the screen that opened the sheet named
                the account (user, 2026-09-20): the + on SeaBank's page is for
                SeaBank, and saying so again is a row you read past. The [+] in
                the tab bar is the way in when you want to choose. */}
            {!knownAccount && (
              <div className="no-scrollbar -mx-5 flex gap-2 overflow-x-auto px-5 py-1" role="group" aria-label="Account">
                {accountChips(accountId, setAccountId)}
              </div>
            )}
            {limitHint && (
              <p aria-live="polite" className={`num text-footnote font-medium ${limitHint.tone}`}>
                {limitHint.text}
              </p>
            )}
          </>
        )}

        {/* The date on a line of its own, and the extras on the next (2026-09-28): with the Merchant tile
            (TXN-24) the row no longer fitted a phone, and Cashback dropped to a second line on its own. */}
        <input
          type="date"
          value={txnDate}
          onChange={(e) => e.target.value && setTxnDate(e.target.value)}
          aria-label="Date"
          className="block min-h-tap w-full rounded-xl border-2 border-stroke bg-surface px-3 text-footnote font-medium text-ink"
        />
        <div className="flex flex-wrap items-center gap-2">
          {kind !== 'transfer' && !showMerchant && (
            <SheetAction
              label="Merchant"
              icon={<StoreIcon size={20} />}
              onClick={() => {
                setShowMerchant(true);
                window.requestAnimationFrame(() => merchantInput.current?.focus());
              }}
            />
          )}
          {!showNote && (
            <SheetAction label="Add note" icon={<NoteIcon size={20} />} onClick={() => setShowNote(true)} />
          )}
          {kind !== 'transfer' && tags.length > 0 && !showTags && (
            <SheetAction label="Tags" icon={<TagIcon size={20} />} onClick={() => setShowTags(true)} />
          )}
          {kind !== 'transfer' && !splitting && (
            <SheetAction label="Split" icon={<SplitIcon size={20} />} onClick={startSplit} />
          )}
          {spreadable && !showPlan && (
            <SheetAction label="Installments" icon={<InstallmentsIcon size={20} />} onClick={() => setShowPlan(true)} />
          )}
          {kind === 'expense' && !showCashback && !spreading && incomeCategories.length > 0 && (
            // The suggested amount is worth its width (ACC-38); the word "Cashback" is not.
            <SheetAction label="Cashback" icon={<CashbackIcon size={20} />} onClick={openCashback}>
              {suggestion && suggestion !== '0.00' ? formatPHP(suggestion) : undefined}
            </SheetAction>
          )}
        </div>

        {kind !== 'transfer' && showTags && tags.length > 0 && (
          <div className="flex items-center gap-2">
          <div className="no-scrollbar -ml-5 flex flex-1 gap-2 overflow-x-auto py-1 pl-5" role="group" aria-label="Tags">
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
          <SheetAction
            label="Clear tags"
            icon={<CloseIcon size={18} />}
            tone="quiet"
            onClick={() => { setTagIds([]); setShowTags(false); }}
          />
          </div>
        )}

        {spreading && accountId !== null && (
          <div className="space-y-1">
            <InstallmentFields accountId={accountId} amount={amount} txnDate={txnDate}
              cardPostedOn={editing?.card_posted_on ?? null} choice={plan} onChange={setPlan}
              onPreview={(found) => setPlanReady(found !== null)} />
            <button type="button" onClick={() => setShowPlan(false)} className="min-h-tap text-footnote text-ink-2">
              Pay it in one go
            </button>
          </div>
        )}

        {kind === 'expense' && showCashback && !spreading && (
          <div className="space-y-2 rounded-card border-2 border-stroke bg-surface-2 p-3" role="group" aria-label="Cashback">
            <div className="flex items-center gap-2">
              <span className="shrink-0 text-footnote font-semibold text-ink-2">Cashback</span>
              <input
                value={cashback}
                onChange={(e) => { setCashback(sanitizeAmount(e.target.value)); setCashbackRate(null); }}
                inputMode="decimal"
                placeholder="0.00"
                aria-label="Cashback amount"
                className="num min-h-11 w-28 rounded-xl bg-surface px-3 text-right text-body outline-none"
              />
              {suggestion && suggestion !== '0.00' && cents(cashback) !== cents(suggestion) && (
                <SheetAction
                  label={`Use the usual ${Number(cashbackRule?.rate)}%`}
                  icon={<CashbackIcon size={18} />}
                  onClick={() => { setCashback(typedFrom(suggestion)); setCashbackRate(cashbackRule?.rate ?? null); }}
                >
                  {formatPHP(suggestion)}
                </SheetAction>
              )}
              <SheetAction
                label="Remove cashback"
                icon={<CloseIcon size={18} />}
                tone="quiet"
                onClick={() => { setShowCashback(false); setCashback(''); }}
              />
            </div>
            <div className="flex flex-wrap items-center gap-2">
              {/* Only when nothing could be guessed - otherwise it is decided, and said below. */}
              {!cashbackHome && !cashbackRule && (
                <select
                  value={cashbackCategory ?? ''}
                  onChange={(e) => setCashbackCategory(Number(e.target.value) || null)}
                  aria-label="Cashback category"
                  className="min-h-11 min-w-0 flex-1 rounded-xl border-2 border-stroke bg-surface px-2 text-footnote"
                >
                  <option value="">Lands in…</option>
                  {incomeCategories.map((c) => (
                    <option key={c.id} value={c.id}>{c.parent_id ? `  ${c.name}` : c.name}</option>
                  ))}
                </select>
              )}
              <input
                type="date"
                value={cashbackOn ?? txnDate}
                onChange={(e) => e.target.value && setCashbackOn(e.target.value)}
                aria-label="Cashback lands on"
                className="min-h-11 rounded-xl border-2 border-stroke bg-surface px-2 text-footnote"
              />
            </div>
            <p className="text-caption text-ink-3">
              The purchase keeps its full amount — this is its own income entry
              {cashbackCategoryName ? ` in ${cashbackCategoryName}` : ''}, on this account, dated the day the money
              arrives.
            </p>
          </div>
        )}

        {kind !== 'transfer' && showMerchant && (
          <div className="space-y-2">
            <div className="flex items-center gap-2">
              <input
                ref={merchantInput}
                type="text"
                value={merchant}
                onChange={(e) => setMerchant(e.target.value)}
                maxLength={80}
                placeholder={kind === 'income' ? 'Who paid' : 'Where you paid'}
                aria-label="Merchant"
                autoComplete="off"
                className="min-h-12 min-w-0 flex-1 rounded-xl border-2 border-stroke bg-surface px-3.5 text-body outline-none focus:shadow-[var(--lift)_var(--lift)_0_0_rgb(var(--c-shadow))]"
              />
              <SheetAction
                label="Remove merchant"
                icon={<CloseIcon size={18} />}
                tone="quiet"
                onClick={() => { setMerchant(''); setShowMerchant(false); }}
              />
            </div>
            {merchantMatches.length > 0 && (
              <div className="no-scrollbar -mx-5 flex gap-2 overflow-x-auto px-5 py-1" role="group" aria-label="Merchants used before">
                {merchantMatches.map((m) => (
                  <Chip key={m.name} selected={false} onClick={() => pickMerchant(m)}>
                    {m.name}
                  </Chip>
                ))}
              </div>
            )}
          </div>
        )}

        {showNote && (
          <div className="flex items-center gap-2">
            <input
              type="text"
              value={note}
              onChange={(e) => setNote(e.target.value)}
              maxLength={500}
              placeholder="Note"
              aria-label="Note"
              className="min-h-12 min-w-0 flex-1 rounded-xl border-2 border-stroke bg-surface px-3.5 text-body outline-none focus:shadow-[var(--lift)_var(--lift)_0_0_rgb(var(--c-shadow))]"
            />
            {/* There was no way back at all before this: once opened, the note stayed. */}
            <SheetAction
              label="Remove note"
              icon={<CloseIcon size={18} />}
              tone="quiet"
              onClick={() => { setNote(''); setShowNote(false); }}
            />
          </div>
        )}

        {splitting && kind !== 'transfer' && (
          <div className="space-y-2 rounded-card border-2 border-stroke bg-surface-2 p-3">
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
              <SheetAction
                label="Add a line"
                icon={<span aria-hidden="true" className="text-body font-extrabold leading-none">+</span>}
                onClick={() => setLines((ls) => [...ls, { key: Date.now(), category_id: null, amount: remaining > 0 ? fromCentavos(remaining) : '' }])}
              >
                Add a line
              </SheetAction>
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
            <SheetAction
              label="Don’t split"
              icon={<CloseIcon size={18} />}
              tone="quiet"
              onClick={() => { setSplitting(false); setLines([]); }}
            >
              Don’t split
            </SheetAction>
          </div>
        )}

        <NumPad onKey={(key: NumPadKey) => setTyped((t) => applyAmountKey(t, key))} onLongBackspace={() => setTyped('0')} />

        {error && <p className="text-footnote text-danger">{error}</p>}

        <Button block size="lg" onClick={() => void save()} disabled={!canSave}>
          {problem ?? (spreading
            ? `${editing ? 'Convert to' : 'Save as'} ${plan.payments} monthly payment${plan.payments === 1 ? '' : 's'}`
            : editing ? 'Save changes' : 'Save')}
        </Button>

        {editing && editing.id > 0 && (
          <ReceiptControl transactionId={editing.id} attachmentId={editing.attachment_id ?? null} />
        )}

        {editing && (
          <Button variant="secondary" block className="text-danger" onClick={() => void remove()} disabled={busy}>
            Delete {editing.type === 'transfer' ? 'transfer' : 'transaction'}
          </Button>
        )}
        </>
        )}
      </div>
    </Sheet>
  );
}
