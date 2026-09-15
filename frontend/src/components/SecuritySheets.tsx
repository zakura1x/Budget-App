/**
 * The account's own security, as sheets (SEC-21..24; FEATURES.md §17).
 *
 * Every one asks for the password again. Rotating the key says plainly what it
 * cannot reach - a copy already downloaded - and it ends every other session
 * and replaces the backups kept on the server.
 */
import { useEffect, useState } from 'react';
import { ApiError } from '../lib/api';
import { changePassword, deleteAccount, rotateKey } from '../lib/security';
import { authErrorMessage, useAuthStore } from '../stores/authStore';
import { PasswordStrength, passwordMeetsPolicy } from './PasswordStrength';
import { PinPad } from './PinPad';
import { Button } from './ui/Button';
import { Sheet } from './ui/Sheet';
import { TextField } from './ui/TextField';

const message = (e: unknown) => (e instanceof ApiError ? e.message : authErrorMessage(e));

export function ChangePasswordSheet({ open, onClose }: { open: boolean; onClose: () => void }) {
  const policy = useAuthStore((s) => s.config?.password_policy);
  const [current, setCurrent] = useState('');
  const [next, setNext] = useState('');
  const [done, setDone] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (open) {
      setCurrent('');
      setNext('');
      setDone(null);
      setError(null);
    }
  }, [open]);

  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      const result = await changePassword(current, next);
      setDone(result.sessions_ended ? `Changed. ${result.sessions_ended} other session${result.sessions_ended === 1 ? ' was' : 's were'} signed out.` : 'Changed.');
    } catch (e) {
      setError(message(e));
    }
    setBusy(false);
  };

  return (
    <Sheet open={open} onClose={onClose} title="Change password">
      <div className="space-y-4 pb-2">
        {done ? (
          <>
            <p className="rounded-2xl bg-ok/10 px-4 py-3 text-footnote font-semibold text-ok">✓ {done}</p>
            <Button block onClick={onClose}>Done</Button>
          </>
        ) : (
          <>
            <TextField label="Current password" type="password" autoComplete="current-password" value={current}
              onChange={(e) => setCurrent(e.target.value)} />
            <TextField label="New password" type="password" autoComplete="new-password" value={next}
              onChange={(e) => setNext(e.target.value)} />
            {policy && <PasswordStrength password={next} policy={policy} />}
            <p className="text-footnote text-ink-3">Your data is not re-encrypted - the password guards sign-in, not the key. Every other session is signed out.</p>
            {error && <p className="text-footnote text-danger">{error}</p>}
            <Button block size="lg" disabled={busy || !current || !policy || !passwordMeetsPolicy(next, policy)} onClick={() => void save()}>
              Change password
            </Button>
          </>
        )}
      </div>
    </Sheet>
  );
}

export function ChangePinSheet({ open, onClose }: { open: boolean; onClose: () => void }) {
  const length = useAuthStore((s) => s.config?.pin_length ?? 6);
  const hasPin = useAuthStore((s) => s.session?.pin_set ?? false);
  const setPin = useAuthStore((s) => s.setPin);
  const [password, setPassword] = useState('');
  const [first, setFirst] = useState<string | null>(null);
  const [step, setStep] = useState<'password' | 'pin' | 'done'>('password');
  const [error, setError] = useState<string | null>(null);
  const [errorKey, setErrorKey] = useState(0);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (open) {
      setPassword('');
      setFirst(null);
      setStep(hasPin ? 'password' : 'pin');
      setError(null);
    }
  }, [open, hasPin]);

  const onComplete = async (pin: string) => {
    if (first === null) {
      setFirst(pin);
      setError(null);
      return;
    }
    if (pin !== first) {
      setFirst(null);
      setError('The two PINs did not match. Start again.');
      setErrorKey((k) => k + 1);
      return;
    }
    setBusy(true);
    try {
      await setPin(pin, hasPin ? password : undefined);
      setStep('done');
    } catch (e) {
      setFirst(null);
      setError(message(e));
      setErrorKey((k) => k + 1);
      if (e instanceof ApiError && e.code === 'INVALID_CREDENTIALS') setStep('password');
    }
    setBusy(false);
  };

  return (
    <Sheet open={open} onClose={onClose} title={hasPin ? 'Change PIN' : 'Set a PIN'}>
      <div className="space-y-4 pb-2">
        {step === 'password' && (
          <>
            <TextField label="Your password" type="password" autoComplete="current-password" value={password}
              onChange={(e) => setPassword(e.target.value)} />
            {error && <p className="text-footnote text-danger">{error}</p>}
            <Button block disabled={!password} onClick={() => { setError(null); setStep('pin'); }}>Continue</Button>
          </>
        )}
        {step === 'pin' && (
          <>
            <p className="text-center text-body">{first === null ? `Choose ${length} digits` : 'Enter them again'}</p>
            {error && <p className="text-center text-footnote text-danger">{error}</p>}
            <PinPad key={first === null ? 'first' : 'second'} length={length} onComplete={onComplete} busy={busy} errorKey={errorKey} />
          </>
        )}
        {step === 'done' && (
          <>
            <p className="rounded-2xl bg-ok/10 px-4 py-3 text-footnote font-semibold text-ok">✓ PIN saved.</p>
            <Button block onClick={onClose}>Done</Button>
          </>
        )}
      </div>
    </Sheet>
  );
}

export function RotateKeySheet({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [password, setPassword] = useState('');
  const [done, setDone] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (open) {
      setPassword('');
      setDone(null);
      setError(null);
      setBusy(false);
    }
  }, [open]);

  const run = async () => {
    setBusy(true);
    setError(null);
    try {
      const result = await rotateKey(password);
      setDone([
        'Everything you have is now encrypted under a new key.',
        result.sessions_ended ? `${result.sessions_ended} other session${result.sessions_ended === 1 ? ' was' : 's were'} signed out.` : '',
        result.backups_replaced
          ? 'The backups kept on the server were replaced with a fresh one. Copies you downloaded earlier still open with the old key - delete them.'
          : 'Old backups could not be replaced automatically - delete them under Backup & data.',
      ].filter(Boolean).join(' '));
    } catch (e) {
      setError(message(e));
    }
    setBusy(false);
  };

  return (
    <Sheet open={open} onClose={onClose} title="Rotate my encryption key">
      <div className="space-y-4 pb-2">
        {done ? (
          <>
            <p className="rounded-2xl bg-ok/10 px-4 py-3 text-footnote font-semibold text-ok">✓ {done}</p>
            <Button block onClick={onClose}>Done</Button>
          </>
        ) : (
          <>
            <p className="text-body">
              Makes a new key and re-encrypts every account, transaction, receipt and note under it. Anyone holding your
              old key is locked out.
            </p>
            <p className="rounded-2xl bg-warn/10 px-4 py-3 text-footnote text-ink">
              It cannot reach a copy someone already exported or downloaded. It takes a few seconds, and it all happens
              at once or not at all.
            </p>
            <TextField label="Your password" type="password" autoComplete="current-password" value={password}
              onChange={(e) => setPassword(e.target.value)} />
            {error && <p className="text-footnote text-danger">{error}</p>}
            <Button block size="lg" variant="danger" disabled={busy || !password} onClick={() => void run()}>
              {busy ? 'Working…' : 'Rotate the key'}
            </Button>
          </>
        )}
      </div>
    </Sheet>
  );
}

export function DeleteAccountSheet({ open, onClose }: { open: boolean; onClose: () => void }) {
  const email = useAuthStore((s) => s.session?.user.email ?? '');
  const markSignedOut = useAuthStore((s) => s.markSignedOut);
  const [typed, setTyped] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (open) {
      setTyped('');
      setPassword('');
      setError(null);
    }
  }, [open]);

  const matches = typed.trim().toLowerCase() === email.trim().toLowerCase() && email !== '';
  const run = async () => {
    setBusy(true);
    setError(null);
    try {
      await deleteAccount(password, typed);
      onClose();
      markSignedOut();
    } catch (e) {
      setError(message(e));
      setBusy(false);
    }
  };

  return (
    <Sheet open={open} onClose={onClose} title="Delete my account">
      <div className="space-y-4 pb-2">
        <div className="space-y-2 rounded-2xl bg-danger/10 px-4 py-3 text-footnote text-danger">
          <p className="font-semibold">This cannot be undone.</p>
          <p>
            Every account, transaction, receipt, budget and backup kept on this server is destroyed, with your key.
            There is no copy anywhere on our side - not even for the admin.
          </p>
          <p>A backup you downloaded yourself can still be restored into a new account by whoever runs this server. Keep one first if you might want this back.</p>
        </div>
        <TextField label={`Type ${email || 'your email'} to confirm`} value={typed} autoComplete="off" autoCapitalize="none"
          spellCheck={false} onChange={(e) => setTyped(e.target.value)} />
        <TextField label="Your password" type="password" autoComplete="current-password" value={password}
          onChange={(e) => setPassword(e.target.value)} />
        {error && <p className="text-footnote text-danger">{error}</p>}
        <Button block size="lg" variant="danger" disabled={busy || !matches || !password} onClick={() => void run()}>
          Delete everything
        </Button>
      </div>
    </Sheet>
  );
}
