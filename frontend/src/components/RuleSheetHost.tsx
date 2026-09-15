/**
 * The rule sheet anywhere in the app (REC-31, 2026-09-15): the + button's
 * "Recurring" and a credit card's page open it through uiStore.openRuleSheet,
 * so setting up a bill never needs a trip to More -> Recurring. Saving bumps
 * the ledger version (RuleSheet does), and every screen showing money reloads.
 */
import { useEffect, useState } from 'react';
import { useLookups } from '../hooks/useLookups';
import { useUiStore, type RuleSheetRequest } from '../stores/uiStore';
import { RuleSheet } from './RuleSheet';

export function RuleSheetHost() {
  const request = useUiStore((s) => s.ruleSheet);
  const close = useUiStore((s) => s.closeRuleSheet);
  const lookups = useLookups();
  // Keep the last request while the sheet slides away, so its title does not change mid-animation.
  const [shown, setShown] = useState<RuleSheetRequest | null>(request);
  useEffect(() => {
    if (request) setShown(request);
  }, [request]);

  return (
    <RuleSheet
      open={request !== null}
      rule={shown?.rule ?? null}
      kind={shown?.kind ?? 'standard'}
      prefill={shown?.prefill ?? null}
      lookups={lookups}
      onClose={close}
      onSaved={() => undefined}
    />
  );
}
