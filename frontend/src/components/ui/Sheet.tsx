/**
 * Bottom sheet - the pattern the add-transaction flow is built on.
 *
 * Slides up from the bottom, dims the page, closes on backdrop tap, Escape,
 * or a downward drag on the handle. Locks page scroll while open, moves focus
 * into the sheet and returns it on close.
 */
import { useEffect, useRef, useState, type ReactNode } from 'react';

export interface SheetProps {
  open: boolean;
  onClose: () => void;
  title?: string;
  children: ReactNode;
}

const DRAG_CLOSE_PX = 90;

export function Sheet({ open, onClose, title, children }: SheetProps) {
  const panel = useRef<HTMLDivElement>(null);
  const opener = useRef<Element | null>(null);
  const dragStart = useRef<number | null>(null);
  const [dragY, setDragY] = useState(0);
  const [mounted, setMounted] = useState(open);

  // Stay mounted through the closing animation.
  useEffect(() => {
    if (open) setMounted(true);
  }, [open]);

  useEffect(() => {
    if (!open) return;
    opener.current = document.activeElement;
    const { overflow } = document.body.style;
    document.body.style.overflow = 'hidden';
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose();
    window.addEventListener('keydown', onKey);
    requestAnimationFrame(() => panel.current?.focus());
    return () => {
      document.body.style.overflow = overflow;
      window.removeEventListener('keydown', onKey);
      (opener.current as HTMLElement | null)?.focus?.();
    };
  }, [open, onClose]);

  if (!mounted) return null;

  const onPointerDown = (e: React.PointerEvent) => {
    dragStart.current = e.clientY;
    (e.target as Element).setPointerCapture?.(e.pointerId);
  };
  const onPointerMove = (e: React.PointerEvent) => {
    if (dragStart.current !== null) setDragY(Math.max(0, e.clientY - dragStart.current));
  };
  const onPointerUp = () => {
    if (dragY > DRAG_CLOSE_PX) onClose();
    dragStart.current = null;
    setDragY(0);
  };

  return (
    <div className="fixed inset-0 z-50" role="presentation">
      <div
        className={`absolute inset-0 touch-none bg-black/40 transition-opacity duration-300 ${open ? 'opacity-100' : 'opacity-0'}`}
        onClick={onClose}
        aria-hidden="true"
      />
      <div
        ref={panel}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        tabIndex={-1}
        onTransitionEnd={() => !open && setMounted(false)}
        className={[
          'absolute inset-x-0 bottom-0 mx-auto max-w-app rounded-t-sheet border-x-2 border-t-2 border-stroke bg-surface outline-none',
          'pb-safe transition-transform duration-300 ease-ios',
          open ? 'translate-y-0' : 'translate-y-full',
        ].join(' ')}
        style={dragY ? { transform: `translateY(${dragY}px)`, transition: 'none' } : undefined}
      >
        <div
          className="flex h-7 cursor-grab touch-none items-center justify-center"
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={onPointerUp}
          onPointerCancel={onPointerUp}
        >
          <span className="h-1.5 w-12 rounded-full bg-stroke" />
        </div>
        {title && <h2 className="px-5 pb-3 text-title font-black tracking-tight">{title}</h2>}
        {/* Vertical only: overflow-y-auto alone makes x auto too, and iOS then lets a
            finger drag the whole form sideways; contain stops the drag reaching the page. */}
        <div className="max-h-[85dvh] overflow-y-auto overflow-x-hidden overscroll-contain px-5 pb-4 pt-1">{children}</div>
      </div>
    </div>
  );
}
