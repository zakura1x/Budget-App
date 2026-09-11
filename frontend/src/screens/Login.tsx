import { useState, type FormEvent } from 'react';
import { Link } from 'react-router-dom';
import { AuthLayout, FormError } from '../components/AuthLayout';
import { Button } from '../components/ui/Button';
import { TextField } from '../components/ui/TextField';
import { authErrorMessage, useAuthStore } from '../stores/authStore';

export function Login() {
  const login = useAuthStore((s) => s.login);
  const registrationOpen = useAuthStore((s) => s.config?.registration_open ?? false);
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await login(email.trim(), password);
    } catch (err) {
      setError(authErrorMessage(err));
      setPassword('');
    } finally {
      setBusy(false);
    }
  };

  return (
    <AuthLayout
      title="Welcome back"
      subtitle="Sign in to see your budget."
      footer={
        registrationOpen ? (
          <>
            Have an invitation code?{' '}
            <Link to="/register" className="font-semibold text-accent">
              Create an account
            </Link>
          </>
        ) : null
      }
    >
      <form onSubmit={submit} className="space-y-4" noValidate>
        <TextField label="Email" type="email" autoComplete="email" inputMode="email" value={email}
          onChange={(e) => setEmail(e.target.value)} required />
        <TextField label="Password" type="password" autoComplete="current-password" value={password}
          onChange={(e) => setPassword(e.target.value)} required />
        <FormError message={error} />
        <Button type="submit" size="lg" block disabled={busy || !email || !password}>
          {busy ? 'Signing in…' : 'Sign in'}
        </Button>
      </form>
      <p className="mt-6 text-center text-footnote text-ink-2">
        Forgot your password?{' '}
        <Link to="/recover" className="font-semibold text-accent">
          Use your 12 words
        </Link>
      </p>
    </AuthLayout>
  );
}
