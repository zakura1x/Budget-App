/**
 * Recover access with the 12 words and set a new password (SEC-15).
 *
 * One box per word, with suggestions from the BIP-39 list as you type, so a
 * misspelt word is caught here instead of costing one of the three attempts
 * the server allows per hour. Pasting the whole phrase into any box fills all
 * twelve. No email needed - the words themselves find the account.
 */
import { useEffect, useRef, useState, type FormEvent } from 'react';
import { Link } from 'react-router-dom';
import { AuthLayout, FormError } from '../components/AuthLayout';
import { PasswordStrength, passwordMeetsPolicy } from '../components/PasswordStrength';
import { Button } from '../components/ui/Button';
import { TextField } from '../components/ui/TextField';
import { ApiError } from '../lib/api';
import { authErrorMessage, useAuthStore } from '../stores/authStore';

const COUNT = 12;

export function RecoveryPhraseEnter() {
  const recover = useAuthStore((s) => s.recover);
  const policy = useAuthStore((s) => s.config?.password_policy);
  const [words, setWords] = useState<string[]>(Array(COUNT).fill(''));
  const [focused, setFocused] = useState<number | null>(null);
  const [list, setList] = useState<{ words: readonly string[]; set: ReadonlySet<string> } | null>(null);
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [badPositions, setBadPositions] = useState<number[]>([]);
  const [busy, setBusy] = useState(false);
  const inputs = useRef<(HTMLInputElement | null)[]>([]);

  useEffect(() => {
    // Only this screen needs the 2,048-word list; it is a separate chunk.
    void import('../lib/bip39').then((m) => setList({ words: m.BIP39_WORDS, set: m.BIP39_SET }));
  }, []);

  const clean = (w: string) => w.trim().toLowerCase();
  const isUnknown = (i: number) => {
    const w = clean(words[i] ?? '');
    return Boolean(list && w && !list.set.has(w) && focused !== i);
  };
  const current = focused !== null ? clean(words[focused] ?? '') : '';
  const suggestions =
    list && current.length >= 1 && !list.set.has(current)
      ? list.words.filter((w) => w.startsWith(current)).slice(0, 4)
      : [];

  const setWord = (i: number, value: string) => {
    const parts = value.trim().split(/[\s,]+/).filter(Boolean);
    if (parts.length > 1) {
      // A pasted phrase: spread it across the boxes from here on.
      setWords((ws) => ws.map((w, j) => (j >= i && j - i < parts.length ? (parts[j - i] ?? '').toLowerCase() : w)));
      inputs.current[Math.min(i + parts.length, COUNT - 1)]?.focus();
      return;
    }
    setWords((ws) => ws.map((w, j) => (j === i ? value.replace(/\s/g, '') : w)));
    setBadPositions((b) => b.filter((p) => p !== i + 1));
  };

  const choose = (i: number, word: string) => {
    setWords((ws) => ws.map((w, j) => (j === i ? word : w)));
    if (i < COUNT - 1) inputs.current[i + 1]?.focus();
    else inputs.current[i]?.blur();
  };

  const allKnown = Boolean(list) && words.every((w) => list?.set.has(clean(w)));
  const ready = allKnown && policy && passwordMeetsPolicy(password, policy) && password === confirm;

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!ready) return;
    setBusy(true);
    setError(null);
    try {
      await recover(words.map(clean).join(' '), password);
    } catch (err) {
      if (err instanceof ApiError && Array.isArray(err.body.positions)) setBadPositions(err.body.positions as number[]);
      setError(authErrorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <AuthLayout
      title="Recover your account"
      subtitle="Enter your 12 words in order, then choose a new password."
      footer={<Link to="/login" className="font-semibold text-accent">Back to sign in</Link>}
    >
      <form onSubmit={submit} className="space-y-5" noValidate>
        <div className="grid grid-cols-2 gap-2">
          {words.map((word, i) => {
            const bad = isUnknown(i) || badPositions.includes(i + 1);
            return (
              <label key={i} className={`flex items-center gap-2 rounded-xl border bg-surface px-2.5 transition
                focus-within:border-accent ${bad ? 'border-danger' : 'border-line'}`}>
                <span className="num w-5 text-right text-footnote text-ink-3">{i + 1}</span>
                <input
                  ref={(el) => { inputs.current[i] = el; }}
                  value={word}
                  aria-label={`Word ${i + 1}`}
                  aria-invalid={bad}
                  autoComplete="off" autoCapitalize="off" autoCorrect="off" spellCheck={false}
                  onFocus={() => setFocused(i)}
                  onBlur={() => setFocused((f) => (f === i ? null : f))}
                  onChange={(e) => setWord(i, e.target.value)}
                  onKeyDown={(e) => {
                    if ((e.key === ' ' || e.key === 'Enter') && word) {
                      e.preventDefault();
                      if (suggestions.length === 1 && suggestions[0]) choose(i, suggestions[0]);
                      else inputs.current[Math.min(i + 1, COUNT - 1)]?.focus();
                    }
                  }}
                  className="min-h-11 w-full min-w-0 bg-transparent text-body outline-none"
                />
              </label>
            );
          })}
        </div>

        {suggestions.length > 0 && focused !== null && (
          <div className="flex flex-wrap gap-2" aria-label="Suggestions">
            {suggestions.map((s) => (
              <button key={s} type="button" onPointerDown={(e) => e.preventDefault()} onClick={() => choose(focused, s)}
                className="min-h-9 rounded-full bg-accent-soft px-3.5 text-footnote font-semibold text-accent">
                {s}
              </button>
            ))}
          </div>
        )}

        <div>
          <TextField label="New password" type="password" autoComplete="new-password" value={password}
            onChange={(e) => setPassword(e.target.value)} />
          {policy && <PasswordStrength password={password} policy={policy} />}
        </div>
        <TextField label="New password again" type="password" autoComplete="new-password" value={confirm}
          onChange={(e) => setConfirm(e.target.value)}
          error={confirm && confirm !== password ? 'The passwords do not match' : null} />
        <FormError message={error} />
        <Button type="submit" size="lg" block disabled={busy || !ready}>
          {busy ? 'Recovering…' : 'Recover my account'}
        </Button>
      </form>
    </AuthLayout>
  );
}
