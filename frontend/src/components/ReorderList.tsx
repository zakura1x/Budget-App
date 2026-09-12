/**
 * Drag to reorder, touch first (CAT-06).
 *
 * Two ways to lift a row, because one is not enough on a phone:
 *
 *  - LONG PRESS anywhere on it. While a row is lifted a non-passive
 *    touchmove listener holds the page still; without it the browser would
 *    scroll the list out from under the finger.
 *  - THE GRIP, which lifts on contact. It carries `touch-action: none`, so
 *    a drag that starts there is never mistaken for a scroll — the reliable
 *    path when a long press has been eaten by a fling.
 *
 * The grip is also a real button: focus it and the arrow keys move the row,
 * which is the only way to reorder without a pointer at all.
 *
 * Order is committed once, on release, as the full list of sibling ids.
 */
import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react';

const LIFT_MS = 350;
const SLOP_PX = 8;

export interface ReorderListProps<T> {
  items: T[];
  idOf: (item: T) => number;
  renderItem: (item: T, grip: ReactNode, lifted: boolean) => ReactNode;
  onReorder: (orderedIds: number[]) => void;
  label: string;
}

export function ReorderList<T>({ items, idOf, renderItem, onReorder, label }: ReorderListProps<T>) {
  const [order, setOrder] = useState<T[]>(items);
  const [liftedId, setLifted] = useState<number | null>(null);
  const rows = useRef(new Map<number, HTMLLIElement>());
  const gesture = useRef<{ id: number; startY: number; timer: number | null; lifted: boolean } | null>(null);

  // Someone else's edit wins over a drag that is not in progress.
  useEffect(() => {
    if (liftedId === null) setOrder(items);
  }, [items, liftedId]);

  // While a row is lifted, the page must not scroll underneath it.
  useEffect(() => {
    if (liftedId === null) return;
    const hold = (e: TouchEvent) => e.preventDefault();
    document.addEventListener('touchmove', hold, { passive: false });
    return () => document.removeEventListener('touchmove', hold);
  }, [liftedId]);

  const commit = useCallback(
    (next: T[]) => {
      setOrder(next);
      onReorder(next.map(idOf));
    },
    [idOf, onReorder],
  );

  const moveBy = (id: number, delta: number) => {
    const from = order.findIndex((item) => idOf(item) === id);
    const to = from + delta;
    if (from < 0 || to < 0 || to >= order.length) return;
    const next = [...order];
    next.splice(to, 0, ...next.splice(from, 1));
    commit(next);
  };

  /** Which index the pointer is over, measured from the rows themselves. */
  const indexAt = (clientY: number): number => {
    for (let i = 0; i < order.length; i += 1) {
      const item = order[i];
      const box = item === undefined ? undefined : rows.current.get(idOf(item))?.getBoundingClientRect();
      if (box && clientY < box.bottom) return i;
    }
    return order.length - 1;
  };

  const lift = (id: number) => {
    gesture.current = { ...(gesture.current as NonNullable<typeof gesture.current>), lifted: true };
    setLifted(id);
  };

  const onPointerDown = (id: number, e: React.PointerEvent, immediate: boolean) => {
    // A nested list sits inside a row of this one; without this the parent row
    // would lift the moment a child row is touched.
    e.stopPropagation();
    (e.currentTarget as Element).setPointerCapture?.(e.pointerId);
    const timer = immediate ? null : window.setTimeout(() => lift(id), LIFT_MS);
    gesture.current = { id, startY: e.clientY, timer, lifted: immediate };
    if (immediate) setLifted(id);
  };

  const onPointerMove = (e: React.PointerEvent) => {
    e.stopPropagation();
    const active = gesture.current;
    if (!active) return;
    if (!active.lifted) {
      // Moved before the row lifted: this was a scroll, not a drag.
      if (Math.abs(e.clientY - active.startY) > SLOP_PX) cancel();
      return;
    }
    const from = order.findIndex((item) => idOf(item) === active.id);
    const to = indexAt(e.clientY);
    if (to !== from && to >= 0) {
      const next = [...order];
      next.splice(to, 0, ...next.splice(from, 1));
      setOrder(next);
    }
  };

  const cancel = () => {
    if (gesture.current?.timer) window.clearTimeout(gesture.current.timer);
    gesture.current = null;
    setLifted(null);
  };

  const onPointerUp = (e?: React.PointerEvent) => {
    e?.stopPropagation();
    const active = gesture.current;
    if (active?.timer) window.clearTimeout(active.timer);
    gesture.current = null;
    setLifted(null);
    if (active?.lifted) onReorder(order.map(idOf));
  };

  return (
    <ul aria-label={label} className="divide-y divide-line overflow-hidden rounded-card bg-surface shadow-card">
      {order.map((item) => {
        const id = idOf(item);
        const lifted = liftedId === id;
        const grip = (
          <button
            type="button"
            aria-label="Reorder — hold and drag, or use the arrow keys"
            onPointerDown={(e) => onPointerDown(id, e, true)}
            onPointerMove={onPointerMove}
            onPointerUp={onPointerUp}
            onPointerCancel={onPointerUp}
            onKeyDown={(e) => {
              if (e.key === 'ArrowUp') { e.preventDefault(); moveBy(id, -1); }
              if (e.key === 'ArrowDown') { e.preventDefault(); moveBy(id, 1); }
            }}
            className="-mr-1 flex h-10 w-9 shrink-0 cursor-grab touch-none items-center justify-center text-ink-3 active:cursor-grabbing"
          >
            <svg width="18" height="18" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true">
              <path d="M5 9h14M5 15h14" />
            </svg>
          </button>
        );
        return (
          <li
            key={id}
            ref={(node) => {
              if (node) rows.current.set(id, node);
              else rows.current.delete(id);
            }}
            onPointerDown={(e) => onPointerDown(id, e, false)}
            onPointerMove={onPointerMove}
            onPointerUp={onPointerUp}
            onPointerCancel={cancel}
            style={{ touchAction: 'pan-y' }}
            className={[
              'bg-surface transition-shadow',
              lifted ? 'relative z-10 scale-[1.02] shadow-sheet' : '',
            ].join(' ')}
          >
            {renderItem(item, grip, lifted)}
          </li>
        );
      })}
    </ul>
  );
}
