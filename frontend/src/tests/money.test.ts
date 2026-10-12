/**
 * lib/money.ts - the two questions every screen asks of a money string. They
 * were written out in nine places and the copies disagreed (architecture
 * review 2026-10-12, pass 2 B): one turned "0.00" into "-0.00".
 */
import { describe, expect, it } from 'vitest';
import { isZero, negate } from '../lib/money';

describe('isZero', () => {
  it('knows zero however it is written', () => {
    for (const zero of ['0', '0.00', '-0.00', '00.0']) expect(isZero(zero)).toBe(true);
    for (const other of ['0.01', '-0.01', '10.00', '100']) expect(isZero(other)).toBe(false);
  });
});

describe('negate', () => {
  it('flips the sign', () => {
    expect(negate('12.50')).toBe('-12.50');
    expect(negate('-12.50')).toBe('12.50');
  });
  it('never makes a negative zero', () => {
    expect(negate('0.00')).toBe('0.00');
    expect(negate('-0.00')).toBe('0.00');
  });
});
