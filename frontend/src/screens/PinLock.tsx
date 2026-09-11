/**
 * The lock screen - shown for the auto-lock, the lock button, AND after the
 * server restarted (SEC-27). The screens behind it are unmounted, not just
 * covered, so nothing decrypted stays in the page while it is up.
 *
 * PIN by default; password if no PIN is set, or on request. Five wrong PINs
 * end the session (the server decides) and send you to the sign-in screen.
 */
import { useState, type FormEvent } from 'react';
import { FormError } from '../components/AuthLayout';
import { ShieldIcon } from '../components/Icons';
import { PinPad } from '../components/PinPad';
import { Button } from '../components/ui/Button';
import { TextField } from '../components/ui/TextField';
import { ApiError } from '../lib/api';
import { authErrorMessage, useAuthStore } from '../stores/authStore';

export function PinLock() {
  const session = useAuthStore((s) => s.session);
  const length = useAuthStore((s) => s.config?.pin_length ?? 6);
  const unlockWithPin = useAuthStore((s) => s.unlockWithPin);
  const unlockWithPassword = useAuthStore((s) => s.unlockWithPassword);
  const logout = useAuthStore((s) => s.logout);
  const markSignedOut = useAuthStore((s) => s.markSignedOut);
  const pinSet = session?.pin_set ?? false;

  const [mode, setMode] = useState<'pin' | 'password'>(pinSet ? 'pin' : 'password');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [errorKey, setErrorKey] = useState(0);
  const [busy, setBusy] = useState(false);

  const handle = async (action: () => Promise<void>) => {
    setBusy(true);
    setError(null);
    try {
      await action();
    } catch (err) {
      if (err instanceof ApiError && (err.code === 'SESSION_REVOKED' || err.code === 'AUTH_REQUIRED')) {
        markSignedOut();
        return;
      }
      setError(authErrorMessage(err));
      setErrorKey((k) => k + 1);
    } finally {
      setBusy(false);
    }
  };

  const submitPassword = (e: FormEvent) => {
    e.preventDefault();
    void handle(() => unlockWithPassword(password)).then(() => setPassword(''));
  };

  return (
    <div className="mx-auto flex min-h-dvh max-w-app flex-col items-center px-safe pb-safe pt-safe">
      <div className="flex w-full flex-1 flex-col items-center justify-center py-8">
        <span className="mb-4 flex h-14 w-14 items-center justify-center rounded-full bg-accent-soft text-accent">
          <ShieldIcon size={28} />
        </span>
        <h1 className="text-title">Budget is locked</h1>
        <p className="mb-8 mt-1 text-footnote text-ink-2">
          {mode === 'pin' ? 'Enter your PIN' : 'Enter your password to unlock'}
        </p>

        {mode === 'pin' ? (
          <>
            <div className="mb-4 min-h-6"><FormError message={error} /></div>
            <PinPad length={length} busy={busy} errorKey={errorKey}
              onComplete={(pin) => void handle(() => unlockWithPin(pin))} />
          </>
        ) : (
          <form onSubmit={submitPassword} className="w-full space-y-4" noValidate>
            <TextField label="Password" type="password" autoComplete="current-password" value={password}
              onChange={(e) => setPassword(e.target.value)} autoFocus />
            <FormError message={error} />
            <Button type="submit" size="lg" block disabled={busy || !password}>
              {busy ? 'Unlocking…' : 'Unlock'}
            </Button>
          </form>
        )}
      </div>
      <div className="flex w-full justify-between pb-6">
        {pinSet ? (
          <Button variant="ghost" onClick={() => { setMode(mode === 'pin' ? 'password' : 'pin'); setError(null); }}>
            {mode === 'pin' ? 'Use password' : 'Use PIN'}
          </Button>
        ) : <span />}
        <Button variant="ghost" onClick={() => void logout()}>Sign out</Button>
      </div>
    </div>
  );
}
