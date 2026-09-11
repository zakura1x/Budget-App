/**
 * More - the menu for everything that is not a main tab. In Phase 1 it also
 * proves the whole pipe works: the status rows call /health through api.ts,
 * past the CSP, through the Vite proxy in dev and same-origin in production.
 */
import { useEffect, useState } from 'react';
import { getHealth, type HealthStatus } from '../lib/api';
import { GearIcon, RepeatIcon, ServerIcon, ShieldIcon, TagIcon, WalletIcon } from '../components/Icons';
import { ScreenHeader } from '../components/ScreenHeader';
import { SectionTitle } from '../components/ui/Card';
import { ListGroup, ListRow } from '../components/ui/ListRow';

function YesNo({ ok, loading }: { ok?: boolean; loading: boolean }) {
  if (loading) return <span className="text-ink-3">checking…</span>;
  return <span className={ok ? 'text-ok' : 'text-danger'}>{ok ? 'Yes' : 'No'}</span>;
}

export function More() {
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    getHealth(controller.signal)
      .then(setHealth)
      .catch((e: Error) => e.name !== 'AbortError' && setError(e.message));
    return () => controller.abort();
  }, []);

  const loading = !health && !error;
  const soon = <span className="text-footnote text-ink-3">soon</span>;

  return (
    <>
      <ScreenHeader title="More" />

      <SectionTitle>Money</SectionTitle>
      <ListGroup>
        <ListRow icon={<WalletIcon size={20} />} title="Accounts" subtitle="Cash, cards, savings" trailing={soon} />
        <ListRow icon={<TagIcon size={20} />} title="Categories" trailing={soon} />
        <ListRow icon={<RepeatIcon size={20} />} title="Recurring & installments" trailing={soon} />
      </ListGroup>

      <SectionTitle>App</SectionTitle>
      <ListGroup>
        <ListRow icon={<GearIcon size={20} />} title="Settings" trailing={soon} />
        <ListRow icon={<ShieldIcon size={20} />} title="About your encryption" trailing={soon} />
      </ListGroup>

      <SectionTitle>Server status</SectionTitle>
      <ListGroup>
        <ListRow
          icon={<ServerIcon size={20} />}
          iconTone="bg-surface-2 text-ink-2"
          title="Database reachable"
          trailing={<YesNo loading={loading} ok={health?.checks.database.reachable} />}
        />
        <ListRow
          icon={<ServerIcon size={20} />}
          iconTone="bg-surface-2 text-ink-2"
          title="Schema ZBDGT present"
          trailing={<YesNo loading={loading} ok={health?.checks.database.schema_present} />}
        />
        <ListRow
          icon={<ShieldIcon size={20} />}
          iconTone="bg-surface-2 text-ink-2"
          title="Encryption key loaded"
          trailing={<YesNo loading={loading} ok={health?.checks.encryption.master_key_loaded} />}
        />
      </ListGroup>
      {error && <p className="px-1 pt-2 text-footnote text-danger">Could not reach the server: {error}</p>}
      {health && (
        <p className="px-1 pt-2 text-footnote text-ink-3">
          {health.app} v{health.version}
        </p>
      )}
    </>
  );
}
