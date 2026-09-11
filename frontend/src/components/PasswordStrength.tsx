/**
 * Live password meter against the server's policy (12+ chars, upper, digit,
 * symbol by default). It shows the rules, not a made-up "strength score": the
 * rules are what the server will actually enforce.
 */
import { policyChecks, type PasswordPolicy } from '../lib/auth';

export function PasswordStrength({ password, policy }: { password: string; policy: PasswordPolicy }) {
  const checks = policyChecks(password, policy);
  const met = checks.filter((c) => c.ok).length;
  const tone = met === checks.length ? 'bg-ok' : met >= checks.length - 1 ? 'bg-warn' : 'bg-danger';
  return (
    <div className="mt-2" aria-live="polite">
      <div className="flex gap-1.5" aria-hidden="true">
        {checks.map((c, i) => (
          <span key={c.label} className={`h-1.5 flex-1 rounded-full ${i < met && password ? tone : 'bg-surface-2'}`} />
        ))}
      </div>
      <ul className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1">
        {checks.map((c) => (
          <li key={c.label} className={`text-caption ${c.ok ? 'text-ok' : 'text-ink-3'}`}>
            {c.ok ? '✓' : '○'} {c.label}
          </li>
        ))}
      </ul>
    </div>
  );
}

export const passwordMeetsPolicy = (password: string, policy: PasswordPolicy) =>
  policyChecks(password, policy).every((c) => c.ok);
