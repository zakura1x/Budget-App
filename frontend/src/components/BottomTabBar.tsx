/**
 * Home · Calendar · [+] · Stats · More
 *
 * The [+] is centred, raised and larger than the rest: it is the action the
 * app exists for. Every target is at least 44px, and the bar sits above the
 * home indicator (safe-area inset).
 */
import { NavLink } from 'react-router-dom';
import { CalendarIcon, HomeIcon, MoreIcon, PlusIcon, StatsIcon } from './Icons';

const TABS = [
  { to: '/', label: 'Home', Icon: HomeIcon, end: true },
  { to: '/calendar', label: 'Calendar', Icon: CalendarIcon, end: false },
  null, // the [+] slot
  { to: '/stats', label: 'Stats', Icon: StatsIcon, end: false },
  { to: '/more', label: 'More', Icon: MoreIcon, end: false },
] as const;

export function BottomTabBar({ onAdd }: { onAdd: () => void }) {
  return (
    <nav
      aria-label="Main"
      className="fixed inset-x-0 bottom-0 z-40 border-t border-line/70 bg-surface/90 pb-safe backdrop-blur-xl"
    >
      <ul className="mx-auto grid h-tabbar max-w-app grid-cols-5 items-center">
        {TABS.map((tab) =>
          tab === null ? (
            <li key="add" className="flex justify-center">
              <button
                type="button"
                onClick={onAdd}
                aria-label="Add transaction"
                className="-mt-7 flex h-16 w-16 items-center justify-center rounded-full bg-accent text-on-accent shadow-raised ring-4 ring-bg transition active:scale-95"
              >
                <PlusIcon size={30} />
              </button>
            </li>
          ) : (
            <li key={tab.to}>
              <NavLink
                to={tab.to}
                end={tab.end}
                className={({ isActive }) =>
                  `flex min-h-tap flex-col items-center justify-center gap-0.5 text-[0.6875rem] font-medium transition ${
                    isActive ? 'text-accent' : 'text-ink-3'
                  }`
                }
              >
                <tab.Icon size={24} />
                {tab.label}
              </NavLink>
            </li>
          ),
        )}
      </ul>
    </nav>
  );
}
