import { PhaseNote, ScreenHeader } from '../components/ScreenHeader';
import { Card } from '../components/ui/Card';

export function Stats() {
  return (
    <>
      <ScreenHeader title="Stats" subtitle="This month" />
      <Card className="flex h-56 items-center justify-center">
        <div className="h-36 w-36 rounded-full border-[18px] border-surface-2" aria-hidden="true" />
      </Card>
      <PhaseNote phase="6">
        Spending by category, the trend line, month-over-month comparison and the month-end forecast.
      </PhaseNote>
    </>
  );
}
