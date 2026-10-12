/**
 * lib/transactionDraft - where the add / edit sheet starts, and the cashback
 * part it sends (architecture review 2026-10-12, pass 2 E).
 */
import { describe, expect, it } from 'vitest';
import { cashbackPart, startDraft, type Draft } from '../lib/transactionDraft';
import type { Transaction } from '../lib/transactions';

const TODAY = '2026-10-12';

const row = (over: Partial<Transaction>): Transaction => ({
  id: 7, type: 'expense', txn_date: '2026-10-01', amount: '150.00', account_id: 1,
  splits: [{ category_id: 3, amount: '150.00', note: null }], merchant: null, notes: null,
  direction: null, counter_account_id: null, pair_id: null, tag_ids: [],
  ...over,
} as Transaction);

describe('startDraft', () => {
  it('never opens on the repeat choices, whatever was open before', () => {
    // The bug: "Recurring" chosen while adding stayed on for the next Edit.
    expect(startDraft(row({}), null, null, TODAY).repeating).toBe(false);
    expect(startDraft(null, null, null, TODAY).repeating).toBe(false);
  });

  it('opens a new entry from what the screen knows', () => {
    const d = startDraft(null, { type: 'income', amount: '250.00', categoryId: 9, note: 'lunch' }, '2026-10-05', TODAY);
    expect(d).toMatchObject({ kind: 'income', typed: '250', categoryId: 9, txnDate: '2026-10-05', note: 'lunch', showNote: true });
    expect(startDraft(null, null, null, TODAY).txnDate).toBe(TODAY);
  });

  it('edits a transfer from its out leg, whichever leg was tapped', () => {
    const inLeg = row({ type: 'transfer', direction: 'in', account_id: 2, counter_account_id: 1 });
    expect(startDraft(inLeg, null, null, TODAY)).toMatchObject({ kind: 'transfer', accountId: 1, counterId: 2 });
    const outLeg = row({ type: 'transfer', direction: 'out', account_id: 1, counter_account_id: 2 });
    expect(startDraft(outLeg, null, null, TODAY)).toMatchObject({ accountId: 1, counterId: 2 });
  });

  it('opens a split entry on its lines, and an adjustment as an expense', () => {
    const split = row({ splits: [{ category_id: 3, amount: '100.00', note: null }, { category_id: 4, amount: '50.50', note: null }] });
    const d = startDraft(split, null, null, TODAY);
    expect(d.splitting).toBe(true);
    expect(d.lines.map((l) => [l.category_id, l.amount])).toEqual([[3, '100'], [4, '50.50']]);
    expect(startDraft(row({ type: 'adjustment' }), null, null, TODAY).kind).toBe('expense');
  });
});

describe('cashbackPart', () => {
  const base = startDraft(null, null, null, TODAY);
  const withBack: Draft = { ...base, showCashback: true, cashback: '12.5', cashbackCategory: 4, cashbackRate: '2.0000' };

  it('sends the block when an expense pays money back', () => {
    expect(cashbackPart(withBack, false)).toEqual({ cashback: { amount: '12.50', category_id: 4, rate: '2.0000' } });
  });

  it('sends null only to take away cashback the entry had', () => {
    expect(cashbackPart({ ...withBack, cashback: '' }, true)).toEqual({ cashback: null });
    expect(cashbackPart({ ...withBack, cashback: '' }, false)).toEqual({});
  });

  it('never sends cashback on income or a transfer', () => {
    expect(cashbackPart({ ...withBack, kind: 'income' }, false)).toEqual({});
  });
});
