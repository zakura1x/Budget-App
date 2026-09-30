/**
 * `afterWrite` and the key table (misc/archive/UX_RESPONSIVENESS_PLAN.md §2.3/§2.4).
 *
 * This is the file that decides whether a write reaches the rest of the app.
 * Eleven call sites used to answer that question for themselves and six of
 * them got it wrong, which is the audit in Part 3 of the plan. What is guarded
 * here is the fan-out itself: the right cached answers go stale, the two
 * hand-rolled stores are reloaded, and neither happens for a write that did
 * not touch them.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { afterWrite, MONEY, EVERYTHING } from '../lib/invalidate';
import { keys, GROUP_KEYS } from '../lib/queryKeys';
import { queryClient } from '../lib/queryClient';
import { useBudgetStore } from '../stores/budgetStore';
import { useLedgerStore } from '../stores/ledgerStore';

// The real stores, with just their `load` swapped for a spy - zustand keeps
// actions in state, so this needs no module mocking and leaves everything
// else (the version counter, reset) genuinely real.
const load = vi.fn(() => Promise.resolve());
const budgetLoad = vi.fn(() => Promise.resolve());

/** Put an answer in the cache as though a screen had fetched it. */
const cache = (key: readonly unknown[]) => queryClient.setQueryData(key, { cached: true });
const isStale = (key: readonly unknown[]) =>
  queryClient.getQueryState(key as unknown[])?.isInvalidated === true;

beforeEach(() => {
  load.mockClear();
  budgetLoad.mockClear();
  queryClient.clear();
  useLedgerStore.setState({ load });
  useBudgetStore.setState({ load: budgetLoad });
});

describe('afterWrite', () => {
  it('reloads the ledger, forced, when transactions moved', () => {
    afterWrite('transactions');
    expect(load).toHaveBeenCalledWith(undefined, { force: true });
  });

  it('reloads the budget, forced and on the current period', () => {
    afterWrite('budget');
    expect(budgetLoad).toHaveBeenCalledWith(null, { force: true });
  });

  it('leaves both stores alone for a write that touched neither', () => {
    // Renaming a category changes every row's label, not the rows themselves.
    afterWrite('categories');
    expect(load).not.toHaveBeenCalled();
    expect(budgetLoad).not.toHaveBeenCalled();
  });

  it('marks the matching cached answers stale', () => {
    cache(keys.categories());
    cache(keys.accounts());
    afterWrite('categories');
    expect(isStale(keys.categories())).toBe(true);
    expect(isStale(keys.accounts())).toBe(false);
  });

  it('matches by prefix, so every range of a key goes at once', () => {
    cache(keys.stats({ span: 'month', on: '2026-09-01' }));
    cache(keys.stats({ from: '2026-08-01', to: '2026-08-31' }));
    afterWrite('stats');
    expect(isStale(keys.stats({ span: 'month', on: '2026-09-01' }))).toBe(true);
    expect(isStale(keys.stats({ from: '2026-08-01', to: '2026-08-31' }))).toBe(true);
  });

  it('bumps the version the account trail reads', () => {
    const before = useLedgerStore.getState().version;
    afterWrite('accounts');
    expect(useLedgerStore.getState().version).toBe(before + 1);
  });

  it('reaches every money-shaped answer at once', () => {
    for (const key of [keys.accounts(), keys.calendar(2026, 9), keys.rules(),
                       keys.projection(12), keys.goals(), keys.budgetShape()]) cache(key);
    afterWrite(...MONEY);
    for (const key of [keys.accounts(), keys.calendar(2026, 9), keys.rules(),
                       keys.projection(12), keys.goals(), keys.budgetShape()]) {
      expect(isStale(key), String(key)).toBe(true);
    }
  });

  it('a restore reaches the lookups too, which MONEY deliberately does not', () => {
    cache(keys.categories());
    afterWrite(...MONEY);
    expect(isStale(keys.categories())).toBe(false);
    afterWrite(...EVERYTHING);
    expect(isStale(keys.categories())).toBe(true);
  });
});

describe('the key table', () => {
  it('gives every group a real set of keys', () => {
    for (const group of [...EVERYTHING]) expect(GROUP_KEYS[group]).toBeDefined();
  });

  it('carries today in every key whose endpoint answers "as of today"', () => {
    // A response cached yesterday is a wrong figure, not an old one.
    const today = new Date();
    const stamp = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}-${String(today.getDate()).padStart(2, '0')}`;
    for (const key of [keys.accounts(), keys.goals(), keys.rules(), keys.projection(12),
                       keys.cardLookahead(), keys.budgetShape(), keys.stats({ span: 'month', on: stamp })]) {
      expect(key, String(key)).toContain(stamp);
    }
  });

  it('keeps the lookups off the date - they do not change with it', () => {
    expect(keys.categories()).toEqual(['categories']);
    expect(keys.tags()).toEqual(['tags']);
  });

  it('counts a statement as money, so a posted charge restates it', () => {
    expect(MONEY).toContain('statements');
  });
});
