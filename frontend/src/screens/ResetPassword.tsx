/**
 * Choose a new password from an emailed link (SEC-30).
 *
 * The token arrives in the URL fragment (#token=...), which a browser never
 * sends to the server - so it never lands in an access log. It is read once,
 * wiped from the address bar, and sent in a JSON body. Success signs in.
 */
import { useEffect, useState, type FormEvent } from 'react';
import { Link } from 'react-router-dom';
import { AuthLayout, FormError } from '../components/AuthLayout';
import { PasswordStrength, passwordMeetsPolicy } from '../components/PasswordStrength';
import { Button } from '../components/ui/Button';
import { TextField } from '../components/ui/TextField';
import { ApiError } from '../lib/api';
import { authErrorMessage, useAuthStore } from '../stores/authStore';

function tokenFromFragment(): string {
  return /(?:^#|&)token=([A-Za-z0-9_-]+)/.exec(window.location.hash)?.[1] ?? '';
}

export function ResetPassword() {
  const resetPassword = useAuthStore((s) => s.resetPassword);
  const policy = useAuthStore((s) => s.config?.password_policy);
  const [token] = useState(tokenFromFragment);
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [expired, setExpired] = useState(false);
  const [busy, setBusy] = useState(false);

  // The token is in state now; take it out of the address bar and history.
  useEffect(() => {
    if (window.location.hash) window.history.replaceState(null, '', window.location.pathname + window.location.search);
  }, []);

  const again = <Link to="/forgot" className="font-semibold text-accent">Send me a new link</Link>;

  if (!token || expired) {
    return (
      <AuthLayout
        title={expired ? 'This link has expired' : 'This link is incomplete'}
        subtitle={expired
          ? 'Reset links work once, for a short time. Ask for a new one - it only takes a moment.'
          : 'Open the link straight from the email, or ask for a new one.'}
        footer={<Link to="/login" className="font-semibold text-accent">Back to sign in</Link>}
      >
        {again}
      </AuthLayout>
    );
  }

  const mismatch = confirm.length > 0 && confirm !== password;
  const ready = policy && passwordMeetsPolicy(password, policy) && password === confirm;

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!ready) return;
    setBusy(true);
    setError(null);
    try {
      await resetPassword(token, password);
    } catch (err) {
      if (err instanceof ApiError && err.code === 'RESET_LINK_INVALID') setExpired(true);
      else setError(authErrorMessage(err));
      setBusy(false);
    }
  };

  return (
    <AuthLayout title="Choose a new password" subtitle="You’ll be signed in straight away, and signed out everywhere else.">
      <form onSubmit={submit} className="space-y-4" noValidate>
        <div>
          <TextField label="New password" type="password" autoComplete="new-password" value={password}
            onChange={(e) => setPassword(e.target.value)} />
          {policy && <PasswordStrength password={password} policy={policy} />}
        </div>
        <TextField label="New password again" type="password" autoComplete="new-password" value={confirm}
          onChange={(e) => setConfirm(e.target.value)} error={mismatch ? 'The passwords do not match' : null} />
        <FormError message={error} />
        <Button type="submit" size="lg" block disabled={busy || !ready}>
          {busy ? 'Saving…' : 'Save and sign in'}
        </Button>
      </form>
    </AuthLayout>
  );
}
