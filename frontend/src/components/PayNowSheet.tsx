/**
 * REC-33 - pay a repeating charge's next occurrence now (2026-09-16, user:
 * "my monthly payment for Spotify is in GCash ... there is no button the same
 * as in credit cards to pay it").
 *
 * One confirmation, because it moves money: what is paid, from where, and the
 * promise that makes it safe - the charge will not post again on its own day.
 * The server picks the occurrence (the rule's next one); nothing here works a
 * date out.
 */
import { format, parseISO } from 'date-fns';
import { useEffect, useState } from 'react';
import { ApiError } from '../lib/api';
import { afterWrite, MONEY } from '../lib/invalidate';
import { formatPHP } from '../lib/money';
import { payNow, type Rule } from '../lib/recurring';
import { Button } from './ui/Button';
import { Sheet } from './ui/Sheet';

export interface PayNowSheetProps {
  rule: Rule | null;
  accountName: string;
  onClose: () => void;
}

export function PayNowSheet({ rule, accountName, onClose }: PayNowSheetProps) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setBusy(false);
    setError(null);
  }, [rule?.id]);

  const confirm = async () => {
    if (!rule) return;
    setBusy(true);
    setError(null);
    try {
      await payNow(rule.id);
      afterWrite(...MONEY); // REC-33 - the occurrence posted, with its recurring_on
      onClose();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'That payment did not save. Try again.');
      setBusy(false);
    }
  };

  const due = rule?.next_on ? format(parseISO(rule.next_on), 'd MMM') : null;
  return (
    <Sheet open={rule !== null} onClose={onClose} title={rule ? `Pay ${rule.name} now` : 'Pay now'}>
      {rule && (
        <div className="space-y-4 px-5 pb-6">
          <p className="text-body">
            <span className="num font-semibold">{formatPHP(rule.next_amount ?? rule.amount)}</span> from {accountName}, today
            {due && <> — the payment due <span className="font-semibold">{due}</span></>}.
          </p>
          <p className="text-footnote text-ink-2">
            It will not be charged again on {due ?? 'its day'}; the next one after it stays as scheduled.
          </p>
          {error && <p className="text-footnote text-danger">{error}</p>}
          <div className="grid grid-cols-2 gap-2">
            <Button variant="ghost" onClick={onClose} disabled={busy}>Cancel</Button>
            <Button onClick={() => void confirm()} disabled={busy}>Pay now</Button>
          </div>
        </div>
      )}
    </Sheet>
  );
}
