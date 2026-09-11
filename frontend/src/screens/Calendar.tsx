import { eachDayOfInterval, endOfMonth, endOfWeek, format, isSameMonth, isToday, startOfMonth, startOfWeek } from 'date-fns';
import { PhaseNote, ScreenHeader } from '../components/ScreenHeader';
import { Card } from '../components/ui/Card';

const WEEK_STARTS_ON = 1; // Monday - DEFAULT_WEEK_START_DAY; becomes a setting in 8b

/** The month grid. Phase 6 colours each day by what was spent on it. */
export function Calendar() {
  const month = new Date();
  const days = eachDayOfInterval({
    start: startOfWeek(startOfMonth(month), { weekStartsOn: WEEK_STARTS_ON }),
    end: endOfWeek(endOfMonth(month), { weekStartsOn: WEEK_STARTS_ON }),
  });

  return (
    <>
      <ScreenHeader title={format(month, 'MMMM')} subtitle={format(month, 'yyyy')} />
      <Card>
        <div className="grid grid-cols-7 pb-2 text-center text-caption font-semibold uppercase text-ink-3">
          {days.slice(0, 7).map((d) => (
            <span key={d.toISOString()}>{format(d, 'EEEEE')}</span>
          ))}
        </div>
        <div className="grid grid-cols-7 gap-1">
          {days.map((d) => (
            <div
              key={d.toISOString()}
              className={`num flex aspect-square items-center justify-center rounded-xl text-body ${
                isToday(d) ? 'bg-accent font-semibold text-on-accent' : isSameMonth(d, month) ? 'bg-surface-2/60 text-ink' : 'text-ink-3/60'
              }`}
            >
              {format(d, 'd')}
            </div>
          ))}
        </div>
      </Card>
      <PhaseNote phase="6">A spending heatmap on this grid; tap a day for its transactions.</PhaseNote>
    </>
  );
}
