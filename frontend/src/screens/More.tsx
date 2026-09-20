/**
 * More - the menu for everything that is not a main tab. It opens on who is
 * signed in; Accounts moved to a tab of its own on 2026-09-15. The status rows
 * still prove the whole pipe works: they call /health through api.ts, past the
 * CSP, through the Vite proxy in dev and same-origin in production.
 */
import { useQuery } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { getHealth } from '../lib/api';
import { keys, STALE } from '../lib/queryKeys';
import { CalendarIcon, GearIcon, LockIcon, LogoutIcon, RepeatIcon, ServerIcon, ShieldIcon, StatsIcon, TagIcon, WalletIcon } from '../components/Icons';
import { useAuthStore } from '../stores/authStore';
import { ScreenHeader } from '../components/ScreenHeader';
import { SectionTitle } from '../components/ui/Card';
import { ListGroup, ListRow } from '../components/ui/ListRow';

function YesNo({ ok, loading }: { ok?: boolean; loading: boolean }) {
  if (loading) return <span className="text-ink-3">checking…</span>;
  return <span className={ok ? 'text-ok' : 'text-danger'}>{ok ? 'Yes' : 'No'}</span>;
}

export function More() {
  const { data: health, error } = useQuery({
    queryKey: keys.health(),
    queryFn: ({ signal }) => getHealth(signal),
    staleTime: STALE.health,
  });

  const loading = !health && !error;
  const navigate = useNavigate();
  const session = useAuthStore((s) => s.session);
  const lock = useAuthStore((s) => s.lock);
  const logout = useAuthStore((s) => s.logout);
  const name = session?.user.display_name || session?.user.email || 'You';

  return (
    <>
      <ScreenHeader title="More" />

      <section className="flex items-center gap-4 rounded-card bg-accent p-5 text-on-accent shadow-raised" aria-label="Signed in">
        <span className="flex h-14 w-14 shrink-0 items-center justify-center rounded-full bg-surface text-title font-black text-ink shadow-edge" aria-hidden="true">
          {name.slice(0, 1).toUpperCase()}
        </span>
        <span className="min-w-0 flex-1">
          <span className="block truncate text-headline">{name}</span>
          {session?.user.email && <span className="block truncate text-footnote opacity-80">{session.user.email}</span>}
        </span>
        <button type="button" onClick={() => void lock()} aria-label="Lock now"
          className="press flex h-tap w-tap shrink-0 items-center justify-center rounded-full bg-surface text-ink">
          <LockIcon size={20} />
        </button>
      </section>

      <SectionTitle>Money</SectionTitle>
      <ListGroup>
        <ListRow icon={<StatsIcon size={20} />} title="Budget" subtitle="Amount, period and categories"
          chevron onClick={() => navigate('/budget')} />
        <ListRow icon={<TagIcon size={20} />} title="Categories" subtitle="What your spending is sorted into"
          chevron onClick={() => navigate('/categories')} />
        <ListRow icon={<TagIcon size={20} />} title="Tags" subtitle="Trips and projects, across categories"
          chevron onClick={() => navigate('/tags')} />
        <ListRow icon={<RepeatIcon size={20} />} title="Recurring" subtitle="Bills, pay, subscriptions, installments"
          chevron onClick={() => navigate('/recurring')} />
        <ListRow icon={<WalletIcon size={20} />} title="Savings goals" subtitle="Targets that follow an account's balance"
          chevron onClick={() => navigate('/goals')} />
        <ListRow icon={<CalendarIcon size={20} />} title="Months ahead" subtitle="Cash on hand by month, card statements"
          chevron onClick={() => navigate('/projection')} />
      </ListGroup>

      <SectionTitle>App</SectionTitle>
      <ListGroup>
        <ListRow icon={<GearIcon size={20} />} title="Settings" subtitle="Carry-over, daily allowance, alerts"
          chevron onClick={() => navigate('/settings')} />
        <ListRow icon={<ServerIcon size={20} />} title="Backup & data" subtitle="Encrypted backups, restore, CSV"
          chevron onClick={() => navigate('/backup')} />
        <ListRow icon={<ShieldIcon size={20} />} title="About your encryption" subtitle="What is protected, and what is not"
          chevron onClick={() => navigate('/about-encryption')} />
        {session?.user.is_admin && (
          <ListRow icon={<ServerIcon size={20} />} title="Admin" subtitle="Accounts on this server - never their data"
            chevron onClick={() => navigate('/admin')} />
        )}
      </ListGroup>

      <SectionTitle>Session</SectionTitle>
      <ListGroup>
        <ListRow icon={<LockIcon size={20} />} title="Lock now"
          subtitle={session?.pin_set ? 'Unlock with your PIN' : 'Unlock with your password'} onClick={() => void lock()} />
        <ListRow icon={<LogoutIcon size={20} />} iconTone="bg-danger/10 text-danger" title="Sign out"
          onClick={() => void logout()} />
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
      {error && <p className="px-1 pt-2 text-footnote text-danger">Could not reach the server: {error.message}</p>}
      {health && (
        <p className="px-1 pt-2 text-footnote text-ink-3">
          {health.app} v{health.version}
        </p>
      )}
    </>
  );
}
