/**
 * The receipt on a saved transaction (TXN-15): attach a photo or PDF, look at
 * it, replace or remove it. Only on an entry that already exists - a new one
 * saves first, so the two-taps-and-a-number flow never waits on an upload.
 *
 * The file is decrypted by the server and held here as an object URL for as
 * long as it is on screen, then revoked.
 */
import { useEffect, useRef, useState } from 'react';
import { ApiError } from '../lib/api';
import { ACCEPTED, attachReceipt, getReceipt, removeReceipt } from '../lib/attachments';
import { useLedgerStore } from '../stores/ledgerStore';
import { Button } from './ui/Button';

export function ReceiptControl({ transactionId, attachmentId, readOnly = false }: {
  transactionId: number; attachmentId: number | null;
  /** REC-34: a plan shows the receipt of the purchase it replaced - to look at, not to change. */
  readOnly?: boolean;
}) {
  const [current, setCurrent] = useState<number | null>(attachmentId);
  const [url, setUrl] = useState<string | null>(null);
  const [kind, setKind] = useState<string>('');
  const [showing, setShowing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => setCurrent(attachmentId), [attachmentId]);
  useEffect(() => () => {
    if (url) URL.revokeObjectURL(url);
  }, [url]);

  const refresh = () => useLedgerStore.setState((s) => ({ version: s.version + 1 }));

  const show = async () => {
    if (!current) return;
    if (showing) {
      setShowing(false);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const blob = await getReceipt(current);
      setKind(blob.type);
      setUrl(URL.createObjectURL(blob));
      setShowing(true);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'The receipt did not load.');
    }
    setBusy(false);
  };

  const attach = async (file: File | undefined) => {
    if (!file) return;
    setBusy(true);
    setError(null);
    try {
      const made = await attachReceipt(transactionId, file);
      setCurrent(made.id);
      setShowing(false);
      setUrl(null);
      refresh();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'The receipt did not upload.');
    }
    setBusy(false);
    if (input.current) input.current.value = '';
  };

  const remove = async () => {
    setBusy(true);
    setError(null);
    try {
      await removeReceipt(transactionId);
      setCurrent(null);
      setShowing(false);
      setUrl(null);
      refresh();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'The receipt was not removed.');
    }
    setBusy(false);
  };

  return (
    <div className="space-y-2 rounded-card border-2 border-stroke bg-surface-2 p-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="flex-1 text-footnote font-semibold text-ink-2">{current ? 'Receipt attached' : 'Receipt'}</span>
        {current && (
          <Button variant="ghost" disabled={busy} onClick={() => void show()}>
            {showing ? 'Hide' : 'View'}
          </Button>
        )}
        {!readOnly && (
          <Button variant="secondary" disabled={busy} onClick={() => input.current?.click()}>
            {current ? 'Replace' : 'Attach photo or PDF'}
          </Button>
        )}
        {current && !readOnly && (
          <Button variant="ghost" className="text-danger" disabled={busy} onClick={() => void remove()}>
            Remove
          </Button>
        )}
      </div>
      <input ref={input} type="file" accept={ACCEPTED} className="hidden" onChange={(e) => void attach(e.target.files?.[0])} />
      {showing && url && (kind === 'application/pdf' ? (
        <a href={url} target="_blank" rel="noreferrer" className="block text-footnote font-semibold text-accent-ink">
          Open the PDF
        </a>
      ) : (
        <img src={url} alt="Receipt" className="max-h-72 w-full rounded-xl object-contain" />
      ))}
      {error && <p className="text-footnote text-danger">{error}</p>}
      <p className="text-caption text-ink-3">Stored encrypted on the server, like everything else.</p>
    </div>
  );
}
