/**
 * Sign-up. Needs the invitation code from REGISTRATION_CODE (SEC-19) - there
 * is no open registration on a shared company host.
 */
import { useState, type FormEvent } from 'react';
import { Link } from 'react-router-dom';
import { AuthLayout, FormError } from '../components/AuthLayout';
import { PasswordStrength, passwordMeetsPolicy } from '../components/PasswordStrength';
import { Button } from '../components/ui/Button';
import { TextField } from '../components/ui/TextField';
import { authErrorMessage, useAuthStore } from '../stores/authStore';

export function Register() {
  const register = useAuthStore((s) => s.register);
  const config = useAuthStore((s) => s.config);
  const [form, setForm] = useState({ email: '', name: '', password: '', confirm: '', code: '' });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const policy = config?.password_policy;

  const update = (field: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setForm((f) => ({ ...f, [field]: e.target.value }));

  const mismatch = form.confirm.length > 0 && form.confirm !== form.password;
  const ready =
    form.email.includes('@') && form.code.trim() && policy && passwordMeetsPolicy(form.password, policy) &&
    form.password === form.confirm;

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!ready) return;
    setBusy(true);
    setError(null);
    try {
      await register({
        email: form.email.trim(),
        password: form.password,
        registration_code: form.code.trim(),
        display_name: form.name.trim() || undefined,
      });
    } catch (err) {
      setError(authErrorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  if (config && !config.registration_open) {
    return (
      <AuthLayout title="Sign-up is closed" subtitle="This server is not taking new accounts right now.">
        <Link to="/login" className="font-semibold text-accent-ink">Back to sign in</Link>
      </AuthLayout>
    );
  }

  return (
    <AuthLayout
      title="Create your account"
      subtitle="Everything you enter is encrypted before it reaches the database."
      footer={
        <>
          Already have an account?{' '}
          <Link to="/login" className="font-semibold text-accent-ink">Sign in</Link>
        </>
      }
    >
      <form onSubmit={submit} className="space-y-4" noValidate>
        <TextField label="Invitation code" value={form.code} onChange={update('code')} autoComplete="off"
          autoCapitalize="off" spellCheck={false} hint="From whoever runs this app." />
        <TextField label="Email" type="email" inputMode="email" autoComplete="email" value={form.email}
          onChange={update('email')} />
        <TextField label="Your name (optional)" autoComplete="given-name" value={form.name} onChange={update('name')}
          maxLength={60} />
        <div>
          <TextField label="Password" type="password" autoComplete="new-password" value={form.password}
            onChange={update('password')} />
          {policy && <PasswordStrength password={form.password} policy={policy} />}
        </div>
        <TextField label="Password again" type="password" autoComplete="new-password" value={form.confirm}
          onChange={update('confirm')} error={mismatch ? 'The passwords do not match' : null} />
        <FormError message={error} />
        <Button type="submit" size="lg" block disabled={busy || !ready}>
          {busy ? 'Creating your keys…' : 'Create account'}
        </Button>
      </form>
    </AuthLayout>
  );
}
