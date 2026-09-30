/**
 * Assistant - ask about your own money (misc/AI, Phase A2: AI-10, AI-16, AI-50).
 *
 * Three states. Switched off on the server: a note, nothing else. Not opted
 * in: what is sent, to whom, and a button - figures leave the app only after
 * the user has read this (AI-50). Opted in: the conversation.
 *
 * Each reply is a card with the sentence, a "Based on" list of the facts it
 * was built from and links to the screens they came from, and follow-up
 * questions. A reply the model did not phrase (off, failed, or its figures
 * did not check out) says so in one quiet line - the figures are the app's
 * own either way (AI-08). The thread lives in assistantStore, in memory, and
 * goes on lock.
 */
import { useQuery } from '@tanstack/react-query';
import { useEffect, useRef, useState, type FormEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import { ScreenHeader } from '../components/ScreenHeader';
import { Button } from '../components/ui/Button';
import { Card } from '../components/ui/Card';
import { getAssistantStatus, PLAIN_SKILLS, type AssistantReply, type Tone } from '../lib/assistant';
import { afterWrite } from '../lib/invalidate';
import { keys, STALE } from '../lib/queryKeys';
import { useAssistantStore } from '../stores/assistantStore';
import { usePreferencesStore } from '../stores/preferencesStore';

const MAX_CHARS = 500;

// ok / warn / danger are money state - exactly what a reply's tone is (CLAUDE.md, Design)
const TONES: Record<Tone, { label: string; className: string }> = {
  ok: { label: 'Looks fine', className: 'border-ok bg-ok/10 text-ok' },
  warn: { label: 'Heads up', className: 'border-warn bg-warn/10 text-warn' },
  danger: { label: 'Needs attention', className: 'border-danger bg-danger/10 text-danger' },
};

function Chips({ items, onPick, disabled }: { items: string[]; onPick: (q: string) => void; disabled?: boolean }) {
  if (items.length === 0) return null;
  return (
    <div className="flex flex-wrap gap-2">
      {items.map((q) => (
        <button key={q} type="button" disabled={disabled} onClick={() => onPick(q)}
          className="press rounded-full bg-surface px-3 py-2 text-left text-footnote font-semibold text-ink disabled:opacity-40">
          {q}
        </button>
      ))}
    </div>
  );
}

function Question({ text }: { text: string }) {
  return (
    <div className="flex justify-end">
      <p className="max-w-[85%] whitespace-pre-wrap break-words rounded-card bg-accent px-4 py-2.5 text-body text-on-accent shadow-edge">
        {text}
      </p>
    </div>
  );
}

function Reply({ reply, onAsk, busy }: { reply: AssistantReply; onAsk: (q: string) => void; busy: boolean }) {
  const navigate = useNavigate();
  const tone = reply.tone ? TONES[reply.tone] : null;
  const plain = PLAIN_SKILLS.has(reply.skill);
  return (
    <Card className="space-y-3">
      {tone && (
        <span className={`label inline-block rounded-full border-2 px-2.5 py-0.5 ${tone.className}`}>
          {reply.label ?? tone.label}
        </span>
      )}
      <p className="whitespace-pre-wrap break-words text-body text-ink">{reply.text}</p>
      {!reply.ai_phrased && !plain && (
        <p className="text-footnote text-ink-3">Answered straight from your figures.</p>
      )}

      {reply.facts.length > 0 && (
        <details className="group rounded-xl bg-surface-2 px-3 py-2">
          <summary className="label cursor-pointer select-none text-ink-2">Based on · {reply.title}</summary>
          <ul className="mt-2 space-y-1.5">
            {reply.facts.map((fact) => (
              <li key={fact} className="num text-footnote text-ink-2">{fact}</li>
            ))}
          </ul>
          {reply.sources.length > 0 && (
            <p className="mt-2 text-footnote text-ink-3">
              From{' '}
              {reply.sources.map((s, i) => (
                <span key={s.route}>
                  {i > 0 && ', '}
                  <button type="button" className="font-semibold text-accent-ink underline underline-offset-2"
                    onClick={() => navigate(s.route)}>
                    {s.label}
                  </button>
                </span>
              ))}
            </p>
          )}
        </details>
      )}

      {reply.actions.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {reply.actions.map((a) => (
            <Button key={a.route + a.label} variant="secondary" onClick={() => navigate(a.route)}>{a.label}</Button>
          ))}
        </div>
      )}
      <Chips items={reply.follow_ups} onPick={onAsk} disabled={busy} />
    </Card>
  );
}

function Thinking() {
  return (
    <Card className="flex items-center gap-2" aria-live="polite">
      <span className="flex gap-1" aria-hidden="true">
        {[0, 1, 2].map((i) => (
          <span key={i} className="h-2 w-2 animate-pulse rounded-full bg-ink-3" style={{ animationDelay: `${i * 150}ms` }} />
        ))}
      </span>
      <span className="text-footnote text-ink-2">Looking at your figures…</span>
    </Card>
  );
}

function OptIn({ onTurnOn, busy }: { onTurnOn: () => void; busy: boolean }) {
  return (
    <Card className="space-y-4">
      <h2 className="text-headline">Before you turn it on</h2>
      <p className="text-body text-ink-2">
        The assistant answers questions about your own budget - what's left, where your money went, what's due.
        To do that, it sends some of your figures to an AI model.
      </p>
      <ul className="space-y-2 text-body">
        <li>
          <span className="font-bold">What is sent:</span> your question, and only the figures that answer it -
          amounts, dates, and your category, account and goal names. Never your email, your notes or a receipt.
        </li>
        <li>
          <span className="font-bold">Where it goes:</span> IBM watsonx.ai in a US data centre, through the company's
          AI account - the same service the company's other apps use.
        </li>
        <li>
          <span className="font-bold">What is kept:</span> nothing. Budget App holds the conversation in memory only;
          it is gone when the app locks.
        </li>
        <li>
          <span className="font-bold">What it can do:</span> read and explain. It never adds, changes or deletes
          anything.
        </li>
      </ul>
      <Button block size="lg" disabled={busy} onClick={onTurnOn}>Turn on the assistant</Button>
      <p className="text-footnote text-ink-3">You can turn it off again at the bottom of this screen.</p>
    </Card>
  );
}

export function Assistant() {
  const { data: status, error: statusError } = useQuery({
    queryKey: keys.assistantStatus(),
    queryFn: ({ signal }) => getAssistantStatus(signal),
    staleTime: STALE.assistant,
  });
  const turns = useAssistantStore((s) => s.turns);
  const pending = useAssistantStore((s) => s.pending);
  const error = useAssistantStore((s) => s.error);
  const ask = useAssistantStore((s) => s.ask);
  const clear = useAssistantStore((s) => s.clear);
  const changePrefs = usePreferencesStore((s) => s.change);
  const [draft, setDraft] = useState('');
  const [saving, setSaving] = useState(false);
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (turns.length || pending) endRef.current?.scrollIntoView({ block: 'end', behavior: 'smooth' });
  }, [turns.length, pending]);

  const setOptIn = async (on: boolean) => {
    setSaving(true);
    try {
      await changePrefs({ assistant: on });
      if (!on) clear();
    } finally {
      setSaving(false);
      afterWrite('assistant', 'preferences');
    }
  };

  const send = (question: string) => {
    if (!question.trim() || pending) return;
    setDraft('');
    void ask(question);
  };
  const submit = (e: FormEvent) => {
    e.preventDefault();
    send(draft);
  };

  const left = status?.questions_left_today;
  const header = <ScreenHeader title="Assistant" subtitle="Ask about your money" />;

  if (!status) {
    return (
      <>
        {header}
        {statusError
          ? <p className="text-footnote text-danger">Couldn't reach the assistant: {statusError.message}</p>
          : <div className="skeleton h-48 rounded-card" aria-hidden="true" />}
      </>
    );
  }

  if (!status.enabled) {
    return (
      <>
        {header}
        <Card><p className="text-body text-ink-2">The assistant is switched off on this server.</p></Card>
      </>
    );
  }

  if (!status.opted_in) {
    return (
      <>
        {header}
        <OptIn onTurnOn={() => void setOptIn(true)} busy={saving} />
      </>
    );
  }

  return (
    <>
      <ScreenHeader
        title="Assistant"
        subtitle="Ask about your money"
        action={turns.length > 0
          ? <Button variant="ghost" onClick={clear} disabled={Boolean(pending)}>New chat</Button>
          : undefined}
      />

      <div className="space-y-3">
        {turns.length === 0 && !pending && (
          <Card className="space-y-3">
            <p className="text-body text-ink-2">
              Ask whether you can afford something, or about your budget, spending, cash, bills, cards and
              goals - in English or Taglish.
            </p>
            <Chips items={status.suggestions} onPick={send} />
          </Card>
        )}

        {turns.map((reply, i) => (
          <div key={`${reply.conversation_id}-${i}`} className="space-y-3">
            <Question text={reply.question} />
            <Reply reply={reply} onAsk={send} busy={Boolean(pending)} />
          </div>
        ))}

        {pending && (
          <>
            <Question text={pending} />
            <Thinking />
          </>
        )}
        {error && (
          <p className="rounded-card border-2 border-danger bg-danger/10 px-4 py-3 text-footnote font-semibold text-danger" role="alert">
            {error}
          </p>
        )}
        <div ref={endRef} />
      </div>

      <form onSubmit={submit}
        className="sticky bottom-[calc(theme(spacing.tabbar)+env(safe-area-inset-bottom)+0.75rem)] z-10 mt-4 flex items-end gap-2 rounded-card bg-surface p-2 shadow-card">
        <label htmlFor="assistant-question" className="sr-only">Your question</label>
        <input
          id="assistant-question"
          value={draft}
          maxLength={MAX_CHARS}
          onChange={(e) => setDraft(e.target.value)}
          placeholder={left === 0 ? 'Back tomorrow' : 'Ask about your money…'}
          disabled={left === 0}
          autoComplete="off"
          enterKeyHint="send"
          className="min-h-12 min-w-0 flex-1 rounded-xl bg-transparent px-3 text-body text-ink outline-none placeholder:text-ink-3"
        />
        <Button type="submit" disabled={!draft.trim() || Boolean(pending) || left === 0}>Ask</Button>
      </form>

      <p className="px-1 pt-3 text-footnote text-ink-3">
        {left != null && `${left} ${left === 1 ? 'question' : 'questions'} left today. `}
        Answers use your own figures; the assistant only reads.{' '}
        <button type="button" className="font-semibold text-accent-ink underline underline-offset-2"
          disabled={saving} onClick={() => void setOptIn(false)}>
          Turn the assistant off
        </button>
      </p>
    </>
  );
}
