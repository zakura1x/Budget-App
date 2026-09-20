/**
 * Tags (TXN-10) - labels that cut across categories: "Boracay trip" can hold
 * the flight, the hotel and the food, each still in its own category. Chosen
 * in the add sheet, filtered on in the ledger, totalled on Stats.
 */
import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { PlusIcon } from '../components/Icons';
import { ScreenHeader } from '../components/ScreenHeader';
import { TagSheet } from '../components/TagSheet';
import { Button } from '../components/ui/Button';
import { Card } from '../components/ui/Card';
import { keys, STALE } from '../lib/queryKeys';
import { listTags, type Tag } from '../lib/tags';

export function Tags() {
  const navigate = useNavigate();
  const [sheetOpen, setSheetOpen] = useState(false);
  const [editing, setEditing] = useState<Tag | null>(null);

  // The same answer `useLookups` holds, so a tag chip on a row and this list
  // can never disagree.
  const { data: tags, error, refetch } = useQuery({
    queryKey: keys.tags(),
    queryFn: ({ signal }) => listTags(signal),
    staleTime: STALE.taxonomy,
  });

  const open = (tag: Tag | null) => {
    setEditing(tag);
    setSheetOpen(true);
  };

  return (
    <>
      <ScreenHeader
        title="Tags"
        subtitle={<button type="button" className="text-accent-ink" onClick={() => navigate('/more')}>‹ More</button>}
        action={
          <Button onClick={() => open(null)} aria-label="Add tag">
            <PlusIcon size={20} />
            Add
          </Button>
        }
      />

      {error && (
        <p className="mb-3 rounded-2xl border-2 border-danger bg-danger/10 px-4 py-3 text-footnote text-danger">
          {error.message}{' '}
          <button type="button" className="font-semibold underline" onClick={() => void refetch()}>
            Try again
          </button>
        </p>
      )}

      {tags && tags.length === 0 && !error && (
        <Card className="text-center">
          <p className="text-body">No tags yet.</p>
          <p className="mx-auto mt-1 max-w-xs text-footnote text-ink-2">
            A tag groups spending across categories — a trip, a project, a wedding. Add one, then pick it when you
            add a transaction.
          </p>
          <Button className="mt-4" onClick={() => open(null)}>
            Add a tag
          </Button>
        </Card>
      )}

      {tags && tags.length > 0 && (
        <div className="divide-y divide-stroke/80 overflow-hidden rounded-card bg-surface shadow-card">
          {tags.map((tag) => (
            <button
              key={tag.id}
              type="button"
              onClick={() => open(tag)}
              className="flex min-h-14 w-full items-center gap-3 px-4 text-left transition active:bg-surface-2"
            >
              <span className="h-3.5 w-3.5 shrink-0 rounded-full" style={{ backgroundColor: tag.colour }} aria-hidden="true" />
              <span className="min-w-0 flex-1 truncate text-body">{tag.name}</span>
              <span className="text-footnote text-ink-3">
                {tag.usage} transaction{tag.usage === 1 ? '' : 's'}
              </span>
            </button>
          ))}
        </div>
      )}

      <TagSheet open={sheetOpen} tag={editing} onClose={() => setSheetOpen(false)} onSaved={() => undefined} />
    </>
  );
}
