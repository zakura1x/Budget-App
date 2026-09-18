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
import { useEffect, useState } from 'react';
import { type Account, type Credit } from '../lib/accounts';
import { getProjection, listRules, type Projection, type Rule } from '../lib/recurring';
import { useLedgerStore } from '../stores/ledgerStore';
import { AccountPayments } from './AccountPayments';
import { AccountPlans } from './AccountPlans';
import { CardBills } from './CardBills';

export function CardPayments({ account }: { account: Account }) {
  const credit = account.credit as Credit;
  const version = useLedgerStore((s) => s.version);
  const [rules, setRules] = useState<Rule[] | null>(null);
  const [projection, setProjection] = useState<Projection | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    Promise.all([listRules(undefined, controller.signal), getProjection(12, controller.signal)])
      .then(([found, ahead]) => {
        setRules(found);
        setProjection(ahead);
      })
      .catch((e: Error) => e.name !== 'AbortError' && setError(e.message));
    return () => controller.abort();
  }, [account.id, version]);

  if (rules === null && !error) return <div className="skeleton mt-3 h-40 rounded-card" aria-hidden="true" />;

  return (
    <div className="mt-3 space-y-3">
      {error && <p className="rounded-2xl border-2 border-danger bg-danger/10 px-4 py-3 text-footnote text-danger">{error}</p>}

      <CardBills account={account} />

      <AccountPlans account={account} rules={rules} alwaysShow />

      <AccountPayments account={account} rules={rules} projection={projection} startOn={credit.payment_due} />
    </div>
  );
}
