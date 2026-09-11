/**
 * Progress ring - the home screen's centrepiece (Phase 5 feeds it real data).
 *
 * `progress` is the share of the budget USED, 0..1 (over 1 = overspent). The
 * tone follows the one colour rule of this app: ok -> warn -> danger, and
 * only money state ever uses those colours.
 */
import type { ReactNode } from 'react';

export type Tone = 'ok' | 'warn' | 'danger';

export function toneFor(progress: number, warnAt = 0.8): Tone {
  if (progress >= 1) return 'danger';
  if (progress >= warnAt) return 'warn';
  return 'ok';
}

const STROKE: Record<Tone, string> = {
  ok: 'stroke-ok',
  warn: 'stroke-warn',
  danger: 'stroke-danger',
};

export interface RingProps {
  progress: number;
  size?: number;
  thickness?: number;
  tone?: Tone;
  label?: string;
  children?: ReactNode;
}

export function Ring({ progress, size = 232, thickness = 18, tone, label, children }: RingProps) {
  const clamped = Math.min(Math.max(progress, 0), 1);
  const radius = (size - thickness) / 2;
  const circumference = 2 * Math.PI * radius;
  const resolved = tone ?? toneFor(progress);

  return (
    <div
      className="relative inline-flex items-center justify-center"
      style={{ width: size, height: size }}
      role="img"
      aria-label={label ?? `${Math.round(clamped * 100)} percent of budget used`}
    >
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} className="-rotate-90">
        <circle cx={size / 2} cy={size / 2} r={radius} fill="none" strokeWidth={thickness} className="stroke-surface-2" />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          strokeWidth={thickness}
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={circumference * (1 - clamped)}
          className={`${STROKE[resolved]} transition-[stroke-dashoffset] duration-700 ease-ios`}
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center text-center">{children}</div>
    </div>
  );
}
