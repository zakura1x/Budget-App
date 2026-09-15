/**
 * A half-circle gauge - the Budget screen's headline (2026-09-15).
 *
 * Same rule as the Ring: `progress` is the share USED (over 1 = overspent),
 * and the arc is money state - ok, warn, danger - and nothing else.
 */
import type { ReactNode } from 'react';
import { toneFor, type Tone } from './Ring';

const STROKE: Record<Tone, string> = { ok: 'stroke-ok', warn: 'stroke-warn', danger: 'stroke-danger' };

export function Gauge({
  progress, tone, label, width = 260, thickness = 20, children,
}: { progress: number; tone?: Tone; label: string; width?: number; thickness?: number; children?: ReactNode }) {
  const clamped = Math.min(Math.max(progress, 0), 1);
  const radius = (width - thickness) / 2;
  const height = radius + thickness;
  const cx = width / 2;
  const cy = radius + thickness / 2;
  const arc = `M ${cx - radius} ${cy} A ${radius} ${radius} 0 0 1 ${cx + radius} ${cy}`;
  const length = Math.PI * radius;

  return (
    <div className="relative mx-auto" style={{ width, height }} role="img" aria-label={label}>
      <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`}>
        <path d={arc} fill="none" strokeWidth={thickness} strokeLinecap="round" className="stroke-surface-2" />
        <path
          d={arc}
          fill="none"
          strokeWidth={thickness}
          strokeLinecap="round"
          strokeDasharray={length}
          strokeDashoffset={length * (1 - clamped)}
          className={`${STROKE[tone ?? toneFor(progress)]} transition-[stroke-dashoffset] duration-700 ease-ios`}
        />
      </svg>
      <div className="absolute inset-x-0 bottom-0 flex flex-col items-center text-center">{children}</div>
    </div>
  );
}
