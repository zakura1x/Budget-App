/**
 * The 12 words, shown ONCE, straight after sign-up (SEC-14).
 *
 *   1. the words, large and numbered, with the warning
 *   2. an explicit "I have written them down"
 *   3. re-enter three randomly chosen words - proof they were written down,
 *      not just scrolled past
 *
 * The phrase lives only in memory (authStore.pendingPhrase) and is dropped the
 * moment step 3 passes. The server never had a copy to begin with.
 */
import { useMemo, useState, type FormEvent } from 'react';
import { AuthLayout, FormError } from '../components/AuthLayout';
import { Button } from '../components/ui/Button';
import { TextField } from '../components/ui/TextField';
import { useAuthStore } from '../stores/authStore';

function pickPositions(count: number, total: number): number[] {
  const picked = new Set<number>();
  const random = new Uint32Array(1);
  while (picked.size < count) {
    crypto.getRandomValues(random);
    picked.add((random[0] ?? 0) % total);
  }
  return [...picked].sort((a, b) => a - b);
}

export function RecoveryPhraseSetup() {
  const words = useAuthStore((s) => s.pendingPhrase) ?? [];
  const confirmPhrase = useAuthStore((s) => s.confirmPhrase);
  const [step, setStep] = useState<'show' | 'confirm'>('show');
  const [acknowledged, setAcknowledged] = useState(false);
  const positions = useMemo(() => pickPositions(3, words.length || 12), [words.length]);
  const [answers, setAnswers] = useState<string[]>(['', '', '']);
  const [error, setError] = useState<string | null>(null);

  const check = (e: FormEvent) => {
    e.preventDefault();
    const wrong = positions.filter((p, i) => (answers[i] ?? '').trim().toLowerCase() !== words[p]);
    if (wrong.length) {
      setError(`Word ${wrong.map((p) => p + 1).join(' and ')} ${wrong.length > 1 ? 'do' : 'does'} not match. Check your paper.`);
      return;
    }
    confirmPhrase();
  };

  if (step === 'show') {
    return (
      <AuthLayout title="Your recovery phrase" subtitle="These 12 words are a second key to all of your data.">
        <ol className="grid grid-cols-2 gap-2" aria-label="Recovery phrase">
          {words.map((word, i) => (
            <li key={i} className="flex items-baseline gap-2 rounded-xl bg-surface px-3 py-2.5 shadow-card">
              <span className="num w-5 text-right text-footnote text-ink-3">{i + 1}</span>
              <span className="text-headline tracking-wide">{word}</span>
            </li>
          ))}
        </ol>
        <div className="mt-5 rounded-2xl bg-warn/10 p-4 text-footnote text-ink">
          <p className="font-semibold">Write these on paper. Store them away from this device, and away from your
            .env backup.</p>
          <p className="mt-1.5 text-ink-2">Anyone holding them can read all of your data. If you lose both your
            password and these words, nobody - not even the admin - can get your data back. You will not see
            them again.</p>
        </div>
        <label className="mt-5 flex min-h-tap cursor-pointer items-start gap-3">
          <input type="checkbox" checked={acknowledged} onChange={(e) => setAcknowledged(e.target.checked)}
            className="mt-0.5 h-5 w-5 shrink-0 accent-[rgb(var(--c-accent))]" />
          <span className="text-body">I have written all 12 words down, in order.</span>
        </label>
        <Button size="lg" block className="mt-4" disabled={!acknowledged} onClick={() => setStep('confirm')}>
          Continue
        </Button>
      </AuthLayout>
    );
  }

  return (
    <AuthLayout title="Check your paper" subtitle="Type these three words from what you wrote down.">
      <form onSubmit={check} className="space-y-4" noValidate>
        {positions.map((p, i) => (
          <TextField key={p} label={`Word ${p + 1}`} value={answers[i] ?? ''} autoComplete="off" autoCapitalize="off"
            spellCheck={false}
            onChange={(e) => setAnswers((a) => a.map((v, j) => (j === i ? e.target.value : v)))} />
        ))}
        <FormError message={error} />
        <Button type="submit" size="lg" block disabled={answers.some((a) => !a.trim())}>Confirm</Button>
        <Button variant="ghost" block onClick={() => { setStep('show'); setError(null); }}>
          Show the words again
        </Button>
      </form>
    </AuthLayout>
  );
}
