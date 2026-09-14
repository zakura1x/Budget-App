/**
 * One transaction, as the ledger and Home show it.
 *
 * The title is what you would call it out loud: the merchant if there is
 * one, otherwise the category. A split says so rather than picking one of
 * its categories to pretend to be. A transfer reads as a movement - "BDO →
 * Wallet" - and its amount carries no sign, because no money left you.
 * A balance adjustment says what it is - an unrecorded loss or gain (ACC-29) -
 * and is signed, because the balance did move, but never green: it is not income.
 */
import type { Lookups } from '../hooks/useLookups';
import { formatPHP } from '../lib/money';
import type { Transaction } from '../lib/transactions';
import { isPending } from '../stores/ledgerStore';
import { GlyphTile } from './StylePicker';

const NEUTRAL = '#8E8E93';

export function TransactionRow({ row, lookups }: { row: Transaction; lookups: Lookups }) {
  const account = lookups.accountById.get(row.account_id);
  const first = row.splits[0];
  const category = first?.category_id != null ? lookups.categoryById.get(first.category_id) : undefined;
  const split = row.splits.length > 1;

  let title: string;
  let subtitle: string;
  let icon = category?.icon ?? 'tag';
  let colour = category?.colour ?? NEUTRAL;

  if (row.type === 'transfer') {
    const counter = row.counter_account_id != null ? lookups.accountById.get(row.counter_account_id) : undefined;
    const [from, to] = row.direction === 'in' ? [counter, account] : [account, counter];
    title = `${from?.name ?? 'Account'} → ${to?.name ?? 'Account'}`;
    subtitle = row.notes ?? 'Transfer';
    icon = 'undo';
    colour = NEUTRAL;
  } else if (row.type === 'adjustment') {
    title = row.direction === 'out' ? 'Unrecorded loss' : 'Unrecorded gain';
    subtitle = [account?.name, row.notes ?? 'Balance adjustment'].filter(Boolean).join(' · ');
    icon = 'tools';
    colour = NEUTRAL;
  } else {
    const label = split ? `Split · ${row.splits.length} categories` : category?.name ?? 'Uncategorised';
    title = row.merchant ?? (split ? 'Split' : category?.name ?? 'Transaction');
    subtitle = [row.merchant ? label : null, account?.name, row.notes].filter(Boolean).join(' · ');
  }

  const amount =
    row.type === 'expense' || (row.type === 'adjustment' && row.direction === 'out') ? `-${row.amount}` : row.amount;
  const gain = row.type === 'adjustment' && row.direction === 'in';

  return (
    <span className={`flex min-h-14 w-full items-center gap-3 px-4 py-2.5 text-left ${isPending(row) ? 'opacity-60' : ''}`}>
      <GlyphTile icon={icon} colour={colour} size={40} />
      <span className="min-w-0 flex-1">
        <span className="block truncate text-body">{title}</span>
        {subtitle && <span className="block truncate text-footnote text-ink-2">{subtitle}</span>}
      </span>
      <span
        className={`num shrink-0 text-body font-semibold ${
          row.type === 'income' ? 'text-ok' : row.type === 'transfer' ? 'text-ink-2' : 'text-ink'
        }`}
      >
        {row.type === 'income' || gain ? '+' : ''}
        {formatPHP(amount)}
      </span>
    </span>
  );
}
