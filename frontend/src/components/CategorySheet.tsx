/**
 * Add or edit one category, and delete one safely (CAT-01..CAT-08).
 *
 * The delete is the interesting part. The server refuses to strand
 * transactions, so a category that is in use comes back 409 with the count —
 * not an error, a question. The sheet turns it into the question it is:
 * "Move 14 transactions to…", with the same-kind categories to choose from.
 * Nothing is deleted until that is answered.
 */
import { useEffect, useState } from 'react';
import { ApiError } from '../lib/api';
import {
  createCategory,
  deleteCategory,
  flatten,
  updateCategory,
  usageFrom,
  type Category,
  type CategoryKind,
} from '../lib/categories';
import { afterWrite } from '../lib/invalidate';
import { ColourPicker, DEFAULT_COLOUR, GlyphTile, IconPicker } from './StylePicker';
import { Button } from './ui/Button';
import { Sheet } from './ui/Sheet';
import { TextField } from './ui/TextField';

export interface CategorySheetProps {
  open: boolean;
  /** The category being edited, or null when adding. */
  category: Category | null;
  /** Pre-selected parent when adding a sub-category. */
  parentId: number | null;
  kind: CategoryKind;
  tree: Category[];
  onClose: () => void;
  onSaved: () => void;
}

export function CategorySheet({ open, category, parentId, kind, tree, onClose, onSaved }: CategorySheetProps) {
  const editing = category !== null;
  const [name, setName] = useState('');
  const [colour, setColour] = useState(DEFAULT_COLOUR);
  const [icon, setIcon] = useState('tag');
  const [parent, setParent] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [pendingUsage, setPendingUsage] = useState<number | null>(null);
  const [moveTo, setMoveTo] = useState<number | null>(null);

  const hasChildren = Boolean(category && category.children.length > 0);

  useEffect(() => {
    if (!open) return;
    setError(null);
    setBusy(false);
    setPendingUsage(null);
    setMoveTo(null);
    setName(category?.name ?? '');
    setColour(category?.colour ?? DEFAULT_COLOUR);
    setIcon(category?.icon ?? 'tag');
    setParent(category ? category.parent_id : parentId);
  }, [open, category, parentId]);

  const parents = tree.filter((c) => c.kind === kind && c.id !== category?.id);
  const doomed = category ? [category.id, ...category.children.map((c) => c.id)] : [];
  const targets = flatten(tree).filter((c) => c.kind === kind && !doomed.includes(c.id));

  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      const draft = { name: name.trim(), kind, parent_id: parent, icon, colour };
      if (category) await updateCategory(category.id, draft);
      else await createCategory(draft);
      // A name, a colour or an icon is printed on every transaction row, on Home's
      // grid and on a Stats slice - none of which live on this screen (CAT-01/04).
      afterWrite('categories');
      onSaved();
      onClose();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'That did not save. Try again.');
      setBusy(false);
    }
  };

  const remove = async () => {
    if (!category) return;
    setBusy(true);
    setError(null);
    try {
      await deleteCategory(category.id, moveTo ?? undefined);
      // Deleting reassigns what was filed under it, so the rows themselves moved
      // and every figure filed by category changed with them (CAT-06).
      afterWrite('categories', 'transactions', 'budget', 'stats');
      onSaved();
      onClose();
    } catch (e) {
      const usage = usageFrom(e);
      if (usage !== null) {
        setPendingUsage(usage);
        setError(null);
      } else {
        setError(e instanceof ApiError ? e.message : 'That did not delete. Try again.');
      }
      setBusy(false);
    }
  };

  const title = editing ? 'Edit category' : parentId ? 'New sub-category' : 'New category';

  return (
    <Sheet open={open} onClose={onClose} title={title}>
      <div className="space-y-5 pb-2">
        {/* the tile lines up with the input, not with the label above it */}
        <div className="flex items-end gap-3">
          <GlyphTile icon={icon} colour={colour} size={48} />
          <TextField
            className="flex-1"
            label="Name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Groceries"
            maxLength={40}
            autoComplete="off"
          />
        </div>

        {!editing && parents.length > 0 && (
          <div>
            <p className="mb-2 text-footnote font-semibold text-ink-2">Sits under</p>
            <div className="flex flex-wrap gap-2">
              <Chip selected={parent === null} onClick={() => setParent(null)}>
                Nothing — it is a main one
              </Chip>
              {parents.map((option) => (
                <Chip key={option.id} selected={parent === option.id} onClick={() => setParent(option.id)}>
                  {option.name}
                </Chip>
              ))}
            </div>
            <p className="mt-2 text-footnote text-ink-3">Sub-categories go one level deep.</p>
          </div>
        )}

        {editing && hasChildren && (
          <p className="rounded-card border-2 border-stroke bg-surface-2 px-4 py-3 text-footnote text-ink-2">
            {category?.children.length} sub-categories sit under this one. Deleting it deletes them too.
          </p>
        )}

        <div>
          <p className="mb-2 text-footnote font-semibold text-ink-2">Colour</p>
          <ColourPicker value={colour} onChange={setColour} />
        </div>

        <div>
          <p className="mb-2 text-footnote font-semibold text-ink-2">Icon</p>
          <IconPicker value={icon} onChange={setIcon} colour={colour} />
        </div>

        {pendingUsage === null ? (
          // Pinned to the bottom of the sheet: the icon grid is long, and below it Save and Delete
          // were out of sight - on a PC window the editor looked as if it had no buttons.
          <div className="sticky -bottom-4 -mx-5 space-y-1 border-t border-stroke/40 bg-surface px-5 pb-6 pt-3">
            {error && <p className="pb-1 text-footnote text-danger">{error}</p>}
            <Button block size="lg" onClick={() => void save()} disabled={busy || !name.trim()}>
              {editing ? 'Save changes' : 'Add category'}
            </Button>
            {editing && (
              <Button variant="ghost" block className="text-danger" onClick={() => void remove()} disabled={busy}>
                Delete category
              </Button>
            )}
          </div>
        ) : (
          <div className="space-y-3 rounded-card border-2 border-stroke bg-surface-2 p-4">
            {error && <p className="text-footnote text-danger">{error}</p>}
            <p className="text-body">
              {pendingUsage} transaction{pendingUsage === 1 ? '' : 's'} use this category. Where should they go?
            </p>
            <div className="max-h-56 space-y-1 overflow-y-auto">
              {targets.map((option) => (
                <button
                  key={option.id}
                  type="button"
                  onClick={() => setMoveTo(option.id)}
                  className={[
                    'flex min-h-tap w-full items-center gap-3 rounded-xl px-3 text-left transition',
                    moveTo === option.id ? 'bg-accent-soft text-accent-ink' : 'active:bg-line',
                  ].join(' ')}
                >
                  <GlyphTile icon={option.icon} colour={option.colour} size={32} />
                  <span className="truncate text-body">
                    {option.parent_id ? '↳ ' : ''}
                    {option.name}
                  </span>
                </button>
              ))}
              {targets.length === 0 && (
                <p className="text-footnote text-ink-2">
                  Add another {kind} category first — the transactions need somewhere to go.
                </p>
              )}
            </div>
            <Button variant="danger" block onClick={() => void remove()} disabled={busy || moveTo === null}>
              Move them and delete
            </Button>
            <Button variant="ghost" block onClick={() => setPendingUsage(null)} disabled={busy}>
              Keep the category
            </Button>
          </div>
        )}
      </div>
    </Sheet>
  );
}

function Chip({ selected, onClick, children }: { selected: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={selected}
      className={[
        'min-h-tap rounded-xl px-3.5 text-footnote font-medium transition',
        selected ? 'bg-accent text-on-accent shadow-edge' : 'bg-surface text-ink-2 shadow-edge active:bg-surface-2',
      ].join(' ')}
    >
      {children}
    </button>
  );
}
