/**
 * Home · Accounts · [+] · Calendar · More
 *
 * A floating white bar; the tab you are on sits in a soft accent pill. The
 * [+] is centred, raised and larger than the rest: it is the action the app
 * exists for. Accounts is a tab of its own (2026-09-15) - editing one should
 * never be a trip through More. Stats lives behind Calendar's switch, so the
 * Calendar tab stays lit on /stats too.
 *
 * Every target is at least 44px, and the bar sits above the home indicator
 * (safe-area inset).
 */
import { NavLink, useLocation } from 'react-router-dom';
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
      <ul className="mx-auto grid h-16 max-w-app grid-cols-5 items-center rounded-full bg-surface/95 px-1.5 shadow-bar backdrop-blur-xl">
        {TABS.map((tab) =>
          tab === null ? (
            <li key="add" className="flex justify-center">
              <button
                type="button"
                onClick={onAdd}
                aria-label="Add transaction"
                className="-mt-8 flex h-16 w-16 items-center justify-center rounded-full bg-accent text-on-accent shadow-raised ring-4 ring-bg transition active:scale-95"
              >
                <PlusIcon size={30} />
              </button>
            </li>
          ) : (
            <li key={tab.to} className="flex justify-center">
              <NavLink
                to={tab.to}
                end={tab.to === '/'}
                className={({ isActive }) => {
                  const on = isActive || tab.also.some((p) => pathname.startsWith(p));
                  return `flex min-h-tap w-full flex-col items-center justify-center gap-0.5 rounded-full py-1 text-[0.6875rem] font-semibold transition ${
                    on ? 'bg-accent-soft text-accent' : 'text-ink-3 active:bg-surface-2'
                  }`;
                }}
              >
                <span className="relative">
                  <tab.Icon size={22} />
                  {tab.to === '/' && alerting && (
                    <span className="absolute -right-1 -top-0.5 h-2.5 w-2.5 rounded-full bg-danger ring-2 ring-surface" aria-label="Budget alert" />
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
