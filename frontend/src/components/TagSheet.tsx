/**
 * Add or edit one tag (TXN-10). Deleting asks once - with the count of
 * transactions that will lose it - because unlike a category nothing has to
 * move: the server takes the id out of every transaction in the same commit.
 */
import { useEffect, useState } from 'react';
import { ApiError } from '../lib/api';
import { createTag, deleteTag, updateTag, type Tag } from '../lib/tags';
import { ColourPicker, PALETTE } from './StylePicker';
import { Button } from './ui/Button';
import { Sheet } from './ui/Sheet';
import { TextField } from './ui/TextField';

export interface TagSheetProps {
  open: boolean;
  tag: Tag | null;
  onClose: () => void;
  onSaved: () => void;
}

const DEFAULT = PALETTE[5] ?? '#4A90D9';

export function TagSheet({ open, tag, onClose, onSaved }: TagSheetProps) {
  const [name, setName] = useState('');
  const [colour, setColour] = useState(DEFAULT);
  const [confirming, setConfirming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!open) return;
    setName(tag?.name ?? '');
    setColour(tag?.colour ?? DEFAULT);
    setConfirming(false);
    setError(null);
    setBusy(false);
  }, [open, tag]);

  const run = async (action: () => Promise<unknown>, failed: string) => {
    setBusy(true);
    setError(null);
    try {
      await action();
      onSaved();
      onClose();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : failed);
      setBusy(false);
    }
  };

  const save = () =>
    run(() => (tag ? updateTag(tag.id, { name: name.trim(), colour }) : createTag({ name: name.trim(), colour })),
      'That did not save. Try again.');

  const remove = () => {
    if (!tag) return;
    if (tag.usage > 0 && !confirming) {
      setConfirming(true);
      return;
    }
    void run(() => deleteTag(tag.id), 'That did not delete. Try again.');
  };

  return (
    <Sheet open={open} onClose={onClose} title={tag ? 'Edit tag' : 'New tag'}>
      <div className="space-y-5 pb-2">
        <div className="flex items-end gap-3">
          <span className="mb-3.5 h-4 w-4 shrink-0 rounded-full" style={{ backgroundColor: colour }} aria-hidden="true" />
          <TextField
            className="flex-1"
            label="Name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Boracay trip"
            maxLength={30}
            autoComplete="off"
          />
        </div>
        <div>
          <p className="mb-2 text-footnote font-semibold text-ink-2">Colour</p>
          <ColourPicker value={colour} onChange={setColour} />
        </div>

        {error && <p className="text-footnote text-danger">{error}</p>}

        {confirming && tag ? (
          <div className="space-y-3 rounded-card border-2 border-stroke bg-surface-2 p-4">
            <p className="text-body">
              {tag.usage} transaction{tag.usage === 1 ? '' : 's'} carry this tag. They stay as they are, without it.
            </p>
            <Button variant="danger" block onClick={remove} disabled={busy}>
              Remove it and delete
            </Button>
            <Button variant="ghost" block onClick={() => setConfirming(false)} disabled={busy}>
              Keep the tag
            </Button>
          </div>
        ) : (
          <>
            <Button block size="lg" onClick={() => void save()} disabled={busy || !name.trim()}>
              {tag ? 'Save changes' : 'Add tag'}
            </Button>
            {tag && (
              <Button variant="ghost" block className="text-danger" onClick={remove} disabled={busy}>
                Delete tag
              </Button>
            )}
          </>
        )}
      </div>
    </Sheet>
  );
}
