/**
 * Admin (UX-20, SEC-18) - accounts, and nothing in them.
 *
 * The admin sees each account by number: active or not, when it was made and
 * last used. Never an email, a name or a figure - those are under each user's
 * own key. Disabling signs someone out everywhere at once; deleting needs the
 * account's number typed and the admin's password.
 */
import { format, parseISO } from 'date-fns';
import { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { ScreenHeader } from '../components/ScreenHeader';
import { Button } from '../components/ui/Button';
import { Card, SectionTitle } from '../components/ui/Card';
import { Sheet } from '../components/ui/Sheet';
import { TextField } from '../components/ui/TextField';
import { Toggle } from '../components/ui/Toggle';
import { ApiError } from '../lib/api';
import { adminStatus, adminUsers, deleteUser, setUserActive, type AdminStatus, type AdminUser } from '../lib/security';
import { useAuthStore } from '../stores/authStore';

const when = (iso: string | null) => (iso ? format(parseISO(iso), 'd MMM yyyy') : 'never');

export function Admin() {
  const navigate = useNavigate();
  const me = useAuthStore((s) => s.session?.user.id);
  const [users, setUsers] = useState<AdminUser[] | null>(null);
  const [status, setStatus] = useState<AdminStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [doomed, setDoomed] = useState<AdminUser | null>(null);
  const [typed, setTyped] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => Promise.all([adminUsers(), adminStatus()])
    .then(([u, s]) => { setUsers(u); setStatus(s); setError(null); })
    .catch((e: Error) => setError(e.message)), []);

  useEffect(() => void load(), [load]);

  const act = async (action: () => Promise<unknown>) => {
    setBusy(true);
    setError(null);
    try {
      await action();
      await load();
      return true;
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'That did not work.');
      return false;
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <ScreenHeader title="Admin" subtitle={<button type="button" className="text-accent" onClick={() => navigate('/more')}>‹ More</button>} />
      {error && <p className="mb-3 rounded-2xl bg-danger/10 px-4 py-3 text-footnote text-danger">{error}</p>}

      {status && (
        <Card className="num space-y-1 text-footnote text-ink-2">
          <p><span className="text-ink">{status.active_users}</span> active of {status.users} accounts · limit {status.max_users}</p>
          <p>Master key version {status.master_key_version} ({status.master_key_versions_loaded} loaded)</p>
          <p>{status.unlocked_sessions} unlocked sessions · {status.cached_users} in memory</p>
          <p>{Object.entries(status.rows).filter(([, n]) => n > 0).map(([t, n]) => `${t} ${n}`).join(' · ')}</p>
          {Object.keys(status.key_fingerprints).length > 0 && (
            <div className="mt-2 space-y-1 border-t border-line pt-2">
              <p className="text-ink">Key fingerprints</p>
              {Object.entries(status.key_fingerprints).map(([name, value]) => (
                <p key={name} className="flex justify-between gap-3">
                  <span className="min-w-0 truncate">{name}</span>
                  <span className="shrink-0">{value}</span>
                </p>
              ))}
              <p className="text-caption text-ink-3">
                Compare with the offline copy of .env using scripts/env_fingerprint.py. These are short hashes — they
                can’t be turned back into keys.
              </p>
            </div>
          )}
        </Card>
      )}

      <SectionTitle>Accounts</SectionTitle>
      <div className="space-y-3">
        {(users ?? []).map((u) => (
          <Card key={u.id}>
            <div className="flex items-baseline justify-between">
              <p className="text-headline">Account #{u.id}{u.id === me ? ' · you' : ''}</p>
              {u.is_admin && <span className="text-caption font-semibold text-ink-2">Admin</span>}
            </div>
            <p className="text-footnote text-ink-3">
              Made {when(u.created_at)} · last sign-in {when(u.last_login_at)} · key v{u.key_version}
            </p>
            {u.id !== me && (
              <div className="mt-2 border-t border-line pt-2">
                <Toggle checked={u.is_active} disabled={busy} label="Can sign in"
                  onChange={(value) => void act(() => setUserActive(u.id, value))} />
                <Button variant="ghost" block className="text-danger" disabled={busy}
                  onClick={() => { setDoomed(u); setTyped(''); setPassword(''); }}>
                  Delete account #{u.id}
                </Button>
              </div>
            )}
          </Card>
        ))}
      </div>
      <p className="px-1 pt-2 text-footnote text-ink-3">
        Emails, names and figures are encrypted under each person’s own key. No key here opens them — including yours.
      </p>

      {doomed && (
        <Sheet open onClose={() => setDoomed(null)} title={`Delete account #${doomed.id}`}>
          <div className="space-y-4 pb-2">
            <p className="rounded-2xl bg-danger/10 px-4 py-3 text-footnote text-danger">
              Everything in it, its receipts and its backups on this server are destroyed. It cannot be undone, and there is no copy.
            </p>
            <TextField label={`Type ${doomed.id} to confirm`} inputMode="numeric" value={typed} onChange={(e) => setTyped(e.target.value)} />
            <TextField label="Your password" type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} />
            <Button block size="lg" variant="danger" disabled={busy || typed !== String(doomed.id) || !password}
              onClick={() => void act(() => deleteUser(doomed.id, Number(typed), password)).then((ok) => ok && setDoomed(null))}>
              Delete everything
            </Button>
          </div>
        </Sheet>
      )}
    </>
  );
}
