/**
 * Categories (CAT-01..CAT-08).
 *
 * Expense and income are separate lists, not one list with a badge on each
 * row — you are only ever editing one of them, and a mixed list makes every
 * later "which of these can I pick?" question harder than it needs to be.
 *
 * The hierarchy is shown by indentation and by where the [+] sits: each
 * parent carries its own "add a sub-category" button, so nesting is something
 * you do from the parent rather than a field you fill in afterwards.
 *
 * Reordering writes sibling order only. Dragging a child out of its parent
 * would change what it is, not where it sits, so it is not a drag — it is an
 * edit.
 */
import { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { CategorySheet } from '../components/CategorySheet';
import { ChevronRightIcon, PlusIcon } from '../components/Icons';
import { ReorderList } from '../components/ReorderList';
import { ScreenHeader } from '../components/ScreenHeader';
import { GlyphTile } from '../components/StylePicker';
import { Button } from '../components/ui/Button';
import { Card } from '../components/ui/Card';
import { Segmented } from '../components/ui/Segmented';
import { listCategories, reorderCategories, type Category, type CategoryKind } from '../lib/categories';

function Row({
  category,
  grip,
  child = false,
  onEdit,
  onAddChild,
}: {
  category: Category;
  grip: React.ReactNode;
  child?: boolean;
  onEdit: (c: Category) => void;
  onAddChild?: (c: Category) => void;
}) {
  return (
    <div className={`flex items-center gap-2 pr-2 ${child ? 'pl-10' : 'pl-3'}`}>
      <button
        type="button"
        onClick={() => onEdit(category)}
        className="flex min-h-14 min-w-0 flex-1 items-center gap-3 text-left"
      >
        <GlyphTile icon={category.icon} colour={category.colour} size={child ? 32 : 40} />
        <span className="min-w-0 flex-1">
          <span className="block truncate text-body">{category.name}</span>
          {(category.usage > 0 || category.archived) && (
            <span className="block text-footnote text-ink-3">
              {category.usage > 0 && `${category.usage} transaction${category.usage === 1 ? '' : 's'}`}
              {category.usage > 0 && category.archived && ' · '}
              {category.archived && 'archived'}
            </span>
          )}
        </span>
        {/* Says the row opens - on a PC nothing else did, and the editor looked missing. */}
        <ChevronRightIcon size={18} className="shrink-0 text-ink-3" />
      </button>
      {onAddChild && (
        <button
          type="button"
          onClick={() => onAddChild(category)}
          aria-label={`Add a sub-category under ${category.name}`}
          className="flex h-10 w-9 shrink-0 items-center justify-center rounded-lg text-ink-3 transition active:bg-surface-2"
        >
          <PlusIcon size={18} />
        </button>
      )}
      {grip}
    </div>
  );
}

export function Categories() {
  const navigate = useNavigate();
  const [kind, setKind] = useState<CategoryKind>('expense');
  const [tree, setTree] = useState<Category[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sheetOpen, setSheetOpen] = useState(false);
  const [editing, setEditing] = useState<Category | null>(null);
  const [newParent, setNewParent] = useState<number | null>(null);

  const load = useCallback((signal?: AbortSignal) => {
    return listCategories(signal)
      .then((result) => {
        setTree(result);
        setError(null);
      })
      .catch((e: Error) => e.name !== 'AbortError' && setError(e.message));
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load]);

  const openNew = (parentId: number | null) => {
    setEditing(null);
    setNewParent(parentId);
    setSheetOpen(true);
  };

  const openEdit = (category: Category) => {
    setEditing(category);
    setNewParent(null);
    setSheetOpen(true);
  };

  const persistOrder = (ids: number[]) => {
    reorderCategories(ids)
      .then(() => load())
      .catch((e: Error) => setError(e.message));
  };

  const shown = (tree ?? []).filter((c) => c.kind === kind);

  return (
    <>
      <ScreenHeader
        title="Categories"
        subtitle={<button type="button" className="text-accent-ink" onClick={() => navigate('/more')}>‹ More</button>}
        action={
          <Button size="md" onClick={() => openNew(null)} aria-label="Add category">
            <PlusIcon size={20} />
            Add
          </Button>
        }
      />

      <Segmented
        label="Category kind"
        value={kind}
        onChange={setKind}
        options={[
          { value: 'expense', label: 'Spending' },
          { value: 'income', label: 'Income' },
        ]}
      />

      {error && (
        <p className="mt-4 rounded-2xl border-2 border-danger bg-danger/10 px-4 py-3 text-footnote text-danger">
          {error}{' '}
          <button type="button" className="font-semibold underline" onClick={() => void load()}>
            Try again
          </button>
        </p>
      )}

      {tree && shown.length === 0 && !error && (
        <Card className="mt-4 text-center">
          <p className="text-body">No {kind === 'expense' ? 'spending' : 'income'} categories yet.</p>
          <p className="mt-1 text-footnote text-ink-2">
            Start with the handful you actually use. You can add the rest as you go.
          </p>
          <Button className="mt-4" onClick={() => openNew(null)}>
            Add a category
          </Button>
        </Card>
      )}

      {shown.length > 0 && (
        <div className="mt-4 space-y-4">
          <p className="px-1 text-footnote text-ink-2">Tap a category to change or delete it.</p>
          <ReorderList
            label={`${kind} categories`}
            items={shown}
            idOf={(c) => c.id}
            onReorder={persistOrder}
            renderItem={(parent, grip) => (
              <>
                <Row category={parent} grip={grip} onEdit={openEdit} onAddChild={(c) => openNew(c.id)} />
                {parent.children.length > 0 && (
                  <div className="border-t border-stroke/40">
                    <ReorderList
                      label={`sub-categories of ${parent.name}`}
                      items={parent.children}
                      idOf={(c) => c.id}
                      onReorder={persistOrder}
                      renderItem={(child, childGrip) => (
                        <Row category={child} grip={childGrip} child onEdit={openEdit} />
                      )}
                    />
                  </div>
                )}
              </>
            )}
          />
          <p className="px-1 text-footnote text-ink-3">
            Hold a row to lift it, or use the grip. Deleting one asks where its transactions should go.
          </p>
        </div>
      )}

      <CategorySheet
        open={sheetOpen}
        category={editing}
        parentId={newParent}
        kind={editing?.kind ?? kind}
        tree={tree ?? []}
        onClose={() => setSheetOpen(false)}
        onSaved={() => void load()}
      />
    </>
  );
}
