/**
 * A credit card's bills, plans and monthly payment, on the card's own page
 * (ACC-34/35, 2026-09-15):
 *
 *  - BILLS - typed from the card's own app (CardBills, ACC-35).
 *
 *  - PLANS ON THIS CARD - every installment on it, what each still has to go,
 *    and the other charges that repeat here (AccountPlans, shared with every
 *    account that carries a plan).
 *
 *  - YOU PAY IT EACH MONTH - the recurring transfer into the card and when it
 *    reaches zero at that pace (AccountPayments, shared with loans and
 *    borrowed accounts).
 *
 * "Does it balance?" was removed on 2026-09-16 at the user's request: checking
 * the app against the bank is Check statement's job (ACC-24), correcting what
 * the card owes is the account sheet's (ACC-27/28), and the banner already
 * shows owed with plans beside what is billed (REC-14). On a card with typed
 * bills it could only ever agree with itself.
 */
import { useQuery } from '@tanstack/react-query';
import { type Account, type Credit } from '../lib/accounts';
import { keys, STALE } from '../lib/queryKeys';
import { getProjection, listRules } from '../lib/recurring';
import { AccountPayments } from './AccountPayments';
import { AccountPlans } from './AccountPlans';
import { CardBills } from './CardBills';

export function CardPayments({ account }: { account: Account }) {
  const credit = account.credit as Credit;

  // Fetched once here and handed down, so the two cards below do not each ask;
  // they read the same keys anyway, which is what makes that safe.
  const { data: rules = null, error } = useQuery({
    queryKey: keys.rules(),
    queryFn: ({ signal }) => listRules(undefined, signal),
    staleTime: STALE.derived,
  });
  const { data: projection = null } = useQuery({
    queryKey: keys.projection(12),
    queryFn: ({ signal }) => getProjection(12, signal),
    staleTime: STALE.derived,
  });

  if (rules === null && !error) return <div className="skeleton mt-3 h-40 rounded-card" aria-hidden="true" />;

  return (
    <div className="mt-3 space-y-3">
      {error && <p className="rounded-2xl border-2 border-danger bg-danger/10 px-4 py-3 text-footnote text-danger">{error.message}</p>}

      <CardBills account={account} />

      <AccountPlans account={account} rules={rules} alwaysShow />

      <AccountPayments account={account} rules={rules} projection={projection} startOn={credit.payment_due} />
    </div>
  );
}
