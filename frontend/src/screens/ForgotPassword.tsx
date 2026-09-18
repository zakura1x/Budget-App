/**
 * Forgot password (SEC-30). Asks for the email and always gives the same
 * answer, so the form cannot be used to learn who has an account.
 */
import { useState, type FormEvent } from 'react';
import { Link } from 'react-router-dom';
import { AuthLayout, FormError } from '../components/AuthLayout';
import { Button } from '../components/ui/Button';
import { TextField } from '../components/ui/TextField';
import { authApi } from '../lib/auth';
import { authErrorMessage, useAuthStore } from '../stores/authStore';

export function ForgotPassword() {
  const config = useAuthStore((s) => s.config);
  const [email, setEmail] = useState('');
  const [sentTo, setSentTo] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const minutes = config?.reset_link_minutes ?? 30;

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await authApi.forgotPassword(email.trim());
      setSentTo(email.trim());
    } catch (err) {
      setError(authErrorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const back = <Link to="/login" className="font-semibold text-accent-ink">Back to sign in</Link>;

  if (config && !config.password_reset_enabled) {
    return (
      <AuthLayout title="Reset by email is off" subtitle="This server can’t send email yet. Ask whoever runs this app for help.">
        {back}
      </AuthLayout>
    );
  }

  if (sentTo) {
    return (
      <AuthLayout
        title="Check your email"
        subtitle={<>If <span className="font-semibold text-ink">{sentTo}</span> has an account here, a link to choose a new password is on its way.</>}
        footer={back}
      >
        <div className="space-y-2 text-footnote text-ink-2">
          <p>The link works once, for {minutes} minutes, on this device or any other.</p>
          <p>Nothing yet? Look in spam, or ask again in a minute.</p>
        </div>
        <Button variant="secondary" block className="mt-6" onClick={() => setSentTo(null)}>
          Use a different email
        </Button>
      </AuthLayout>
    );
  }

  return (
    <AuthLayout
      title="Forgot your password?"
      subtitle="Enter the email you sign in with, and we’ll send a link to choose a new one."
      footer={back}
    >
      <form onSubmit={submit} className="space-y-4" noValidate>
        <TextField label="Email" type="email" autoComplete="email" inputMode="email" value={email}
          onChange={(e) => setEmail(e.target.value)} required />
        <FormError message={error} />
        <Button type="submit" size="lg" block disabled={busy || !email.includes('@')}>
          {busy ? 'Sending…' : 'Send me the link'}
        </Button>
      </form>
      <p className="mt-6 text-center text-footnote text-ink-3">
        Your budget isn’t locked to your password, so nothing in it changes.
      </p>
    </AuthLayout>
  );
}
