/**
 * Calendar | Stats - the two views behind the Calendar tab (2026-09-15).
 * Each is still its own route, so a refresh or a link lands on the right one.
 */
import { useLocation, useNavigate } from 'react-router-dom';
import { Segmented } from './ui/Segmented';

type View = '/calendar' | '/stats';

export function CalendarSwitch() {
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const value: View = pathname.startsWith('/stats') ? '/stats' : '/calendar';
  return (
    <div className="pt-3">
      <Segmented<View>
        label="Calendar or stats"
        value={value}
        onChange={(next) => navigate(next, { replace: true })}
        options={[
          { value: '/calendar', label: 'Calendar' },
          { value: '/stats', label: 'Stats' },
        ]}
      />
    </div>
  );
}
