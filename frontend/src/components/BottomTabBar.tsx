/**
 * Home · Accounts · [+] · Calendar · More
 *
 * A floating outlined pill on a hard shadow (kept through the neo-brutalist
 * redesign, 2026-09-18); the tab you are on sits in an accent pill. The [+]
 * is centred, raised and larger than the rest: it is the action the app
 * exists for. Accounts is a tab of its own (2026-09-15) - editing one should
 * never be a trip through More. Stats lives behind Calendar's switch, so the
 * Calendar tab stays lit on /stats too.
 *
 * Every target is at least 44px, and the bar sits above the home indicator
 * (safe-area inset).
 */
import { NavLink, useLocation } from 'react-router-dom';
import { prefetchTab } from '../lib/prefetch';
import { useBudgetStore } from '../stores/budgetStore';
import { CalendarIcon, HomeIcon, MoreIcon, PlusIcon, WalletIcon } from './Icons';

const TABS = [
  { to: '/', label: 'Home', Icon: HomeIcon, also: [] as string[] },
  { to: '/accounts', label: 'Accounts', Icon: WalletIcon, also: [] as string[] },
  null, // the [+] slot
  { to: '/calendar', label: 'Calendar', Icon: CalendarIcon, also: ['/stats'] },
  { to: '/more', label: 'More', Icon: MoreIcon, also: [] as string[] },
] as const;

export function BottomTabBar({ onAdd }: { onAdd: () => void }) {
  // UX-19: a dot on Home while the current period has an alert (BUD-12).
  const alerting = useBudgetStore((s) => s.currentAlerts > 0);
  const { pathname } = useLocation();
  return (
    <nav aria-label="Main" className="fixed inset-x-0 bottom-0 z-40 px-3 pb-[max(0.5rem,env(safe-area-inset-bottom))]">
      <ul className="mx-auto grid h-16 max-w-app grid-cols-5 items-center rounded-full bg-surface px-1.5 shadow-bar">
        {TABS.map((tab) =>
          tab === null ? (
            <li key="add" className="flex justify-center">
              <button
                type="button"
                onClick={onAdd}
                aria-label="Add transaction"
                className="press -mt-8 flex h-16 w-16 items-center justify-center rounded-full bg-accent text-on-accent"
              >
                <PlusIcon size={30} />
              </button>
            </li>
          ) : (
            <li key={tab.to} className="flex justify-center">
              <NavLink
                to={tab.to}
                end={tab.to === '/'}
                // Finger down is 80-150 ms before the tab changes: ask now, so
                // the screen has its answer by the time it mounts (plan §2.5).
                onPointerDown={() => prefetchTab(tab.to)}
                className={({ isActive }) => {
                  const on = isActive || tab.also.some((p) => pathname.startsWith(p));
                  return `flex min-h-tap w-full flex-col items-center justify-center gap-0.5 rounded-full py-1 font-mono text-[0.625rem] font-bold uppercase tracking-wide transition ${
                    on ? 'bg-accent text-on-accent shadow-edge' : 'text-ink-2 active:bg-surface-2'
                  }`;
                }}
              >
                <span className="relative">
                  <tab.Icon size={22} />
                  {tab.to === '/' && alerting && (
                    <span className="absolute -right-1 -top-0.5 h-2.5 w-2.5 rounded-full bg-danger shadow-edge" aria-label="Budget alert" />
                  )}
                </span>
                {tab.label}
              </NavLink>
            </li>
          ),
        )}
      </ul>
    </nav>
  );
}
