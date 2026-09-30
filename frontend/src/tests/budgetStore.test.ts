/**
 * The budget store's freshness rules (misc/archive/UX_RESPONSIVENESS_PLAN.md step 4).
 *
 * `/budgets/current` is the slowest call in the app - ~600 ms - and Home asked
 * for it on every single visit. What is guarded here is that it stops doing
 * that WITHOUT ever showing a figure from before a write, or from yesterday.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { BudgetStatus } from '../lib/budgets';

const getStatus = vi.fn<(...args: unknown[]) => Promise<{ status: BudgetStatus | null; alerts: [] }>>();

vi.mock('../lib/budgets', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../lib/budgets')>()),
  getStatus: (...args: unknown[]) => getStatus(...args),
}));

const { useBudgetStore } = await import('../stores/budgetStore');

const status = (isCurrent = true): BudgetStatus =>
  ({
    is_current: isCurrent,
    period: { start: '2026-09-01', end: '2026-09-30' },
    previous_period: { start: '2026-08-01', end: '2026-08-31' },
    next_period: { start: '2026-10-01', end: '2026-10-31' },
    allowance: { daily: '100.00', left_today: '100.00', spent: '0.00', over_by: '0.00' },
    alerts: [],
    categories: [],
  }) as unknown as BudgetStatus;

beforeEach(() => {
  getStatus.mockReset();
  getStatus.mockResolvedValue({ status: status(), alerts: [] });
  useBudgetStore.getState().reset();
});

describe('load', () => {
  it('fetches the first time', async () => {
    await useBudgetStore.getState().load(null);
    expect(getStatus).toHaveBeenCalledTimes(1);
  });

  it('skips a second visit to the same period inside the window', async () => {
    await useBudgetStore.getState().load(null);
    await useBudgetStore.getState().load(null);
    expect(getStatus).toHaveBeenCalledTimes(1);
  });

  it('fetches another period, always - one status is held at a time', async () => {
    await useBudgetStore.getState().load(null);
    await useBudgetStore.getState().load('2026-08-01');
    expect(getStatus).toHaveBeenCalledTimes(2);
  });

  it('fetches again after a minute', async () => {
    await useBudgetStore.getState().load(null);
    vi.setSystemTime(Date.now() + 61_000);
    await useBudgetStore.getState().load(null);
    expect(getStatus).toHaveBeenCalledTimes(2);
    vi.useRealTimers();
  });

  it('always fetches when forced', async () => {
    await useBudgetStore.getState().load(null);
    await useBudgetStore.getState().load(null, { force: true });
    expect(getStatus).toHaveBeenCalledTimes(2);
  });

  it('shares one request between callers that ask together', async () => {
    await Promise.all([
      useBudgetStore.getState().load(null),
      useBudgetStore.getState().load(null),
    ]);
    expect(getStatus).toHaveBeenCalledTimes(1);
  });

  it('asks again on a new day, even inside the window', async () => {
    // The endpoint answers "as of today", so a status cached yesterday is a
    // WRONG figure, not an old one. The freshness key carries the date.
    await useBudgetStore.getState().load(null);
    vi.setSystemTime(new Date(Date.now() + 24 * 60 * 60_000));
    await useBudgetStore.getState().load(null);
    expect(getStatus).toHaveBeenCalledTimes(2);
    vi.useRealTimers();
  });
});

describe('acceptOutcome', () => {
  it('counts as a fetch - the write answered with the current status', async () => {
    useBudgetStore.getState().acceptOutcome(status());
    await useBudgetStore.getState().load(null);
    expect(getStatus).not.toHaveBeenCalled();
  });

  it('does not yank a browsed period back to today', async () => {
    await useBudgetStore.getState().load('2026-08-01');
    const shown = useBudgetStore.getState().status;
    useBudgetStore.getState().acceptOutcome(status());
    expect(useBudgetStore.getState().status).toBe(shown);
  });
});

describe('reset', () => {
  it('drops the status and its marker (SEC-29)', async () => {
    await useBudgetStore.getState().load(null);
    useBudgetStore.getState().reset();
    expect(useBudgetStore.getState().status).toBeNull();
    await useBudgetStore.getState().load(null);
    expect(getStatus).toHaveBeenCalledTimes(2);
  });
});
