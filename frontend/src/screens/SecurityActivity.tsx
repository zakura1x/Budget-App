/**
 * Settings → Security → Signed-in devices (SEC-32) and passkeys (SEC-12).
 *
 *   This device and every other one signed in now - the browser and system it
 *   said it was at sign-in, when it started and was last used - each with
 *   "Sign out"; and "Sign out everywhere else".
 *
 *   The last month of sign-ins: password sign-ins, unlocks and resets, right
 *   or wrong. The server keeps IPs only hashed, so the most it can say is "this
 *   network" - never where.
 *
 *   Passkeys: unlock the lock screen with Face ID or a fingerprint instead of
 *   the PIN. Adding one asks for the password, as changing the PIN does. A
 *   passkey decides whether the server unlocks - it is never a key to the data.
 */
import { useQuery } from '@tanstack/react-query';
import { format, formatDistanceToNowStrict, parseISO } from 'date-fns';
import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { ScreenHeader } from '../components/ScreenHeader';
import { Button } from '../components/ui/Button';
import { Card, SectionTitle } from '../components/ui/Card';
import { ListGroup } from '../components/ui/ListRow';
import { Sheet } from '../components/ui/Sheet';
import { TextField } from '../components/ui/TextField';
import { ApiError } from '../lib/api';
import { afterWrite } from '../lib/invalidate';
import { addPasskey, passkeyCancelled, passkeysSupported, removePasskey } from '../lib/passkeys';
import { keys, STALE } from '../lib/queryKeys';
import { endOtherSessions, endSession, getActivity, type SignIn } from '../lib/security';
import { useAuthStore } from '../stores/authStore';

/** Server timestamps are UTC without a zone. */
const ago = (stamp: string) => formatDistanceToNowStrict(parseISO(`${stamp}Z`), { addSuffix: true });
const KIND: Record<SignIn['kind'], string> = { login: 'Signed in', unlock: 'Unlocked with password', reset: 'Reset the password' };

export function SecurityActivity() {
  const navigate = useNavigate();
  const refreshSession = useAuthStore((s) => s.refreshSession);
  const { data, isPending, error: loadError } = useQuery({
    queryKey: keys.activity(),
    queryFn: ({ signal }) => getActivity(signal),
    staleTime: STALE.health,
  });
  const [supported, setSupported] = useState(false);
  const [adding, setAdding] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);

  useEffect(() => {
    void passkeysSupported().then(setSupported);
  }, []);

  const run = async (action: () => Promise<unknown>, done?: string) => {
    setBusy(true);
    setError(null);
    setNote(null);
    try {
      await action();
      afterWrite('security');
      if (done) setNote(done);
    } catch (e) {
      // A cancelled Face ID prompt is not an error worth a red line.
      if (e instanceof DOMException && e.name === 'InvalidStateError') setError('This device is already set up.');
      else if (!passkeyCancelled(e)) setError(e instanceof ApiError ? e.message : 'That did not work.');
    }
    setBusy(false);
  };

  return (
    <>
      <ScreenHeader title="Security"
        subtitle={<button type="button" className="text-accent-ink" onClick={() => navigate('/settings')}>‹ Settings</button>} />

      {isPending && <p className="py-6 text-center text-footnote text-ink-3">Loading…</p>}
      {loadError && <p className="py-6 text-center text-footnote text-danger">Could not load your devices.</p>}
      {error && <p className="mb-3 text-footnote text-danger">{error}</p>}
      {note && <p className="mb-3 rounded-card border-2 border-ok bg-ok/10 px-4 py-3 text-footnote font-semibold text-ok">✓ {note}</p>}

      {data && (
        <>
          <SectionTitle>Signed in now</SectionTitle>
          <ListGroup>
            {data.sessions.map((s) => (
              <div key={s.id} className="flex min-h-14 items-center gap-3 px-4 py-2.5">
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-body">
                    {s.device ?? 'Unknown device'}
                    {s.current && <span className="label ml-2 rounded-md bg-highlight px-1.5 py-0.5 text-ink">This device</span>}
                  </span>
                  <span className="block truncate text-footnote text-ink-2">
                    {Math.abs(parseISO(s.last_active).getTime() - parseISO(s.started).getTime()) < 60_000
                      ? `Signed in ${ago(s.started)}`
                      : `Used ${ago(s.last_active)} · since ${format(parseISO(`${s.started}Z`), 'd MMM')}`}
                  </span>
                </span>
                {!s.current && (
                  <Button variant="secondary" disabled={busy}
                    onClick={() => void run(() => endSession(s.id), 'That device is signed out.')}>
                    Sign out
                  </Button>
                )}
              </div>
            ))}
          </ListGroup>
          {data.sessions.length > 1 && (
            <Button className="mt-3" variant="secondary" block disabled={busy}
              onClick={() => void run(async () => {
                const { ended } = await endOtherSessions();
                setNote(`${ended} other device${ended === 1 ? ' was' : 's were'} signed out.`);
              })}>
              Sign out everywhere else
            </Button>
          )}

          {data.passkey_enabled && (
            <>
              <SectionTitle>Face ID and fingerprint</SectionTitle>
              <Card className="space-y-3">
                <p className="text-footnote text-ink-2">
                  Unlock the lock screen with this phone’s own Face ID or fingerprint instead of typing the PIN.
                  It only unlocks a device that is already signed in, and the PIN always still works.
                </p>
                {data.passkeys.length > 0 && (
                  <ul className="divide-y divide-stroke/80 rounded-card border-2 border-stroke bg-surface-2">
                    {data.passkeys.map((k) => (
                      <li key={k.id} className="flex items-center gap-3 px-3 py-2">
                        <span className="min-w-0 flex-1">
                          <span className="block truncate text-body">{k.label ?? 'Passkey'}</span>
                          <span className="block truncate text-caption text-ink-3">
                            Added {ago(k.created)}{k.last_used ? ` · used ${ago(k.last_used)}` : ''}
                          </span>
                        </span>
                        <Button variant="ghost" disabled={busy}
                          onClick={() => void run(async () => {
                            await removePasskey(k.id);
                            await refreshSession();
                          }, 'Removed. That device unlocks with the PIN again.')}>
                          Remove
                        </Button>
                      </li>
                    ))}
                  </ul>
                )}
                {supported ? (
                  <Button block variant={data.passkeys.length ? 'secondary' : 'primary'} disabled={busy} onClick={() => setAdding(true)}>
                    {data.passkeys.length ? 'Add another' : 'Set up on this device'}
                  </Button>
                ) : (
                  <p className="text-caption text-ink-3">This browser cannot use Face ID or a fingerprint here.</p>
                )}
              </Card>
            </>
          )}

          <SectionTitle>Sign-ins this month</SectionTitle>
          {data.sign_ins.length === 0 ? (
            <p className="text-footnote text-ink-3">None in the last 30 days.</p>
          ) : (
            <ListGroup>
              {data.sign_ins.map((s, i) => (
                <div key={`${s.at}-${i}`} className="flex min-h-12 items-center gap-3 px-4 py-2">
                  <span className="min-w-0 flex-1">
                    <span className={`block truncate text-body ${s.success ? '' : 'text-danger'}`}>
                      {s.success ? KIND[s.kind] : `Wrong password${s.kind === 'login' ? '' : ` (${KIND[s.kind].toLowerCase()})`}`}
                    </span>
                    <span className="block truncate text-footnote text-ink-2">
                      {ago(s.at)} · {s.same_network ? 'this network' : 'a different network'}
                    </span>
                  </span>
                </div>
              ))}
            </ListGroup>
          )}
          <p className="mt-2 text-caption text-ink-3">
            Where a sign-in came from is never stored - only whether it was the network you are on now.
          </p>
        </>
      )}

      <AddPasskeySheet open={adding} onClose={() => setAdding(false)}
        onAdd={(password) => run(async () => {
          await addPasskey(password);
          await refreshSession();
        }, 'Added. The lock screen now offers Face ID or your fingerprint.').then(() => setAdding(false))} busy={busy} />
    </>
  );
}

function AddPasskeySheet({ open, onClose, onAdd, busy }: {
  open: boolean;
  onClose: () => void;
  onAdd: (password: string) => Promise<void>;
  busy: boolean;
}) {
  const [password, setPassword] = useState('');
  useEffect(() => {
    if (open) setPassword('');
  }, [open]);


  return (
    <Sheet open={open} onClose={onClose} title="Face ID or fingerprint">
      <div className="space-y-4 pb-2">
        <p className="text-footnote text-ink-2">Enter your password, then your phone asks for your face or fingerprint.</p>
        <TextField label="Password" type="password" autoComplete="current-password" value={password}
          onChange={(e) => setPassword(e.target.value)} />
        <Button block size="lg" disabled={busy || !password} onClick={() => void onAdd(password)}>Continue</Button>
      </div>
    </Sheet>
  );
}
