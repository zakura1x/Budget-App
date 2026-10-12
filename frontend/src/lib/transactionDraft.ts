/**
 * What the add / edit sheet (TransactionSheet) holds while you type, and the
 * two pure steps around it: where a fresh sheet STARTS, and how the cashback
 * part leaves for the server (TXN-22).
 *
 * Every field of the form is in `Draft`, so a sheet that opens is set in one
 * assignment and a field cannot be left over from the last time it was open
 * (architecture review 2026-10-12, pass 2 E: "Recurring" chosen once stayed
 * on, and the next Edit opened on the repeat choices instead of the entry).
 * A new field must be added here, where `startDraft` has to answer for it.
 */
import { centavos, toDecimalString } from './money';
import type { CashbackDraft, EntryType, Transaction } from './transactions';
import type { AddPreset } from '../stores/uiStore';

export interface SplitLine {
  key: number;
  category_id: number | null;
  amount: string;
}

export interface Draft {
  kind: EntryType;
  /** REC-31: "Recurring" chosen - the sheet shows what can repeat instead of the numpad. */
  repeating: boolean;
  typed: string;
  categoryId: number | null;
  accountId: number | null;
  counterId: number | null;
  txnDate: string;
  note: string;
  showNote: boolean;
  /** TXN-24. */
  merchant: string;
  showMerchant: boolean;
  tagIds: number[];
  showTags: boolean;
  splitting: boolean;
  lines: SplitLine[];
  /** TXN-22. What this purchase pays back, typed or suggested by the card's own rate. */
  cashback: string;
  cashbackOn: string | null;
  cashbackTo: number | null;
  cashbackCategory: number | null;
  cashbackRate: string | null;
  showCashback: boolean;
}

/** Centavos in a typed amount, or 0 while it is still half-typed. */
export function cents(typed: string): number {
  try {
    return centavos(toDecimalString(typed || '0'));
  } catch {
    return 0;
  }
}

/** The typed form of a stored amount: "150.00" -> "150", "12.50" -> "12.50". */
export function typedFrom(amount: string): string {
  return amount.endsWith('.00') ? amount.slice(0, -3) : amount;
}

/**
 * The sheet as it opens: the entry being edited, or a new one from what the
 * screen that opened it knows (`preset`, the day tapped). A new entry's
 * accounts start empty - the sheet picks them once the account list is in.
 */
export function startDraft(editing: Transaction | null, preset: AddPreset | null, on: string | null, today: string): Draft {
  if (!editing) {
    return {
      kind: preset?.type ?? 'expense',
      repeating: false,
      typed: preset?.amount ? typedFrom(preset.amount) : '0',
      categoryId: preset?.categoryId ?? null,
      accountId: null,
      counterId: null,
      txnDate: on ?? today,
      note: preset?.note ?? '',
      showNote: Boolean(preset?.note),
      merchant: preset?.merchant ?? '',
      showMerchant: Boolean(preset?.merchant),
      tagIds: [],
      showTags: false,
      splitting: false,
      lines: [],
      cashback: '',
      cashbackOn: null,
      cashbackTo: null,
      cashbackCategory: null,
      cashbackRate: null,
      showCashback: false,
    };
  }
  // A transfer is edited from its out leg's point of view, whichever leg was tapped.
  const out = editing.direction !== 'in';
  const transfer = editing.type === 'transfer';
  const multi = editing.splits.length > 1;
  return {
    kind: editing.type === 'adjustment' ? 'expense' : editing.type,
    repeating: false,
    typed: typedFrom(editing.amount),
    categoryId: editing.splits[0]?.category_id ?? null,
    accountId: transfer && !out ? editing.counter_account_id : editing.account_id,
    counterId: transfer ? (out ? editing.counter_account_id : editing.account_id) : null,
    txnDate: editing.txn_date,
    note: editing.notes ?? '',
    showNote: Boolean(editing.notes),
    merchant: editing.merchant ?? '',
    showMerchant: Boolean(editing.merchant),
    tagIds: editing.tag_ids ?? [],
    showTags: (editing.tag_ids ?? []).length > 0,
    splitting: multi,
    lines: multi ? editing.splits.map((s, i) => ({ key: i, category_id: s.category_id, amount: typedFrom(s.amount) })) : [],
    cashback: editing.cashback ? typedFrom(editing.cashback.amount) : '',
    cashbackOn: editing.cashback?.on ?? null,
    cashbackTo: editing.cashback?.account_id ?? null,
    cashbackCategory: editing.cashback?.category_id ?? null,
    cashbackRate: editing.cashback?.rate ?? null,
    showCashback: Boolean(editing.cashback),
  };
}

/**
 * TXN-22. The cashback part of what is sent: the block when this expense pays
 * money back; null only when the entry HAD cashback and no longer does - that
 * is what takes the credit row away; nothing at all otherwise, which an edit
 * reads as "keep it".
 */
export function cashbackPart(draft: Draft, hadCashback: boolean): { cashback?: CashbackDraft | null } {
  if (draft.kind === 'expense' && draft.showCashback && cents(draft.cashback) > 0) {
    return {
      cashback: {
        amount: toDecimalString(draft.cashback),
        category_id: draft.cashbackCategory as number,
        ...(draft.cashbackTo !== null ? { account_id: draft.cashbackTo } : {}),
        ...(draft.cashbackOn ? { on: draft.cashbackOn } : {}),
        ...(draft.cashbackRate ? { rate: draft.cashbackRate } : {}),
      },
    };
  }
  return hadCashback ? { cashback: null } : {};
}
