/**
 * The ledger store's freshness rules (misc/UX_RESPONSIVENESS_PLAN.md step 4).
 *
 * Every test here counts CALLS, not results. A guard that skips a fetch it
 * should have made does not throw - it shows yesterday's figure, which is the
 * failure mode this whole plan is about. The duplicate-fetch bug these cover
 * was found in logs/app.jsonl, not by reading the diff.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { Page, Transaction } from '../lib/transactions';

const listTransactions = vi.fn<(...args: unknown[]) => Promise<Page>>();

vi.mock('../lib/transactions', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../lib/transactions')>()),
  listTransactions: (...args: unknown[]) => listTransactions(...args),
}));

const { useLedgerStore } = await import('../stores/ledgerStore');

const row = (id: number): Transaction => ({
  id,
  type: 'expense',
  txn_date: '2026-09-20',
  amount: '100.00',
  account_id: 1,
  splits: [{ category_id: 1, amount: '100.00', note: null }],
  merchant: null,
  notes: null,
  direction: null,
  counter_account_id: null,
  pair_id: null,
  tag_ids: [],
  created_at: null,
});

const page = (items: Transaction[] = [row(1)]): Page => ({
  items,
  days: [],
  next_cursor: null,
  total_count: items.length,
});

beforeEach(() => {
  listTransactions.mockReset();
  listTransactions.mockResolvedValue(page());
  useLedgerStore.getState().reset();
});

describe('load', () => {
  it('fetches the first time', async () => {
    await useLedgerStore.getState().load({});
    expect(listTransactions).toHaveBeenCalledTimes(1);
    expect(useLedgerStore.getState().items).toHaveLength(1);
  });

  it('skips the second time, with the same filters, inside the window', async () => {
    await useLedgerStore.getState().load({});
    await useLedgerStore.getState().load({});
    expect(listTransactions).toHaveBeenCalledTimes(1);
  });

  it('fetches again once the answer is a minute old', async () => {
    await useLedgerStore.getState().load({});
    vi.setSystemTime(Date.now() + 61_000);
    await useLedgerStore.getState().load({});
    expect(listTransactions).toHaveBeenCalledTimes(2);
    vi.useRealTimers();
  });

  it('fetches when the filters differ', async () => {
    await useLedgerStore.getState().load({});
    await useLedgerStore.getState().load({ account: 3 });
    expect(listTransactions).toHaveBeenCalledTimes(2);
  });

  it('always fetches when forced - a write is what makes fresh wrong', async () => {
    await useLedgerStore.getState().load({});
    await useLedgerStore.getState().load(undefined, { force: true });
    expect(listTransactions).toHaveBeenCalledTimes(2);
  });

  it('shares one request between callers that ask together', async () => {
    // The step 5 regression: prefetch on tab press, then the screen mounts
    // 100 ms later. Neither answer has landed, so neither sees the other's
    // marker - and the app asked twice (logs/app.jsonl, 2026-09-20).
    await Promise.all([
      useLedgerStore.getState().load({}),
      useLedgerStore.getState().load({}),
      useLedgerStore.getState().load({}),
    ]);
    expect(listTransactions).toHaveBeenCalledTimes(1);
  });

  it('runs a forced reload after the one already in flight, never beside it', async () => {
    const order: string[] = [];
    listTransactions
      .mockImplementationOnce(async () => {
        order.push('first');
        return page([row(1)]);
      })
      .mockImplementationOnce(async () => {
        order.push('forced');
        return page([row(2)]);
      });
    const first = useLedgerStore.getState().load({});
    const forced = useLedgerStore.getState().load({}, { force: true });
    await Promise.all([first, forced]);
    expect(order).toEqual(['first', 'forced']);
    // The rows on screen are the ones read AFTER the write, not before it.
    expect(useLedgerStore.getState().items[0]?.id).toBe(2);
  });

  it('keeps the rows on screen when a refresh fails', async () => {
    await useLedgerStore.getState().load({});
    listTransactions.mockRejectedValueOnce(new Error('offline'));
    await useLedgerStore.getState().load(undefined, { force: true });
    expect(useLedgerStore.getState().items).toHaveLength(1);
    expect(useLedgerStore.getState().error).toBe('offline');
  });
});

describe('reset', () => {
  it('drops the freshness marker, so the next load really fetches', async () => {
    await useLedgerStore.getState().load({});
    useLedgerStore.getState().reset();
    await useLedgerStore.getState().load({});
    expect(listTransactions).toHaveBeenCalledTimes(2);
  });

  it('empties the rows - they must not outlive the key (SEC-29)', async () => {
    await useLedgerStore.getState().load({});
    useLedgerStore.getState().reset();
    expect(useLedgerStore.getState().items).toEqual([]);
  });
});

describe('the write paths', () => {
  it('bumps the version so the account trail reloads', async () => {
    await useLedgerStore.getState().load({});
    const before = useLedgerStore.getState().version;
    useLedgerStore.getState().removeIds([1], undefined);
    expect(useLedgerStore.getState().version).toBe(before + 1);
  });

  it('takes a pending row back out when the write fails', () => {
    const id = useLedgerStore.getState().addPending({ ...row(0), id: undefined } as never);
    expect(useLedgerStore.getState().items.some((r) => r.id === id)).toBe(true);
    useLedgerStore.getState().failPending(id);
    expect(useLedgerStore.getState().items.some((r) => r.id === id)).toBe(false);
  });
});
