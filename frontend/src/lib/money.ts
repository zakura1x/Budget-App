/**
 * Money formatting - PHP only (ACC-11), and NEVER through a float.
 *
 * The API sends amounts as decimal strings ("3500.00"). Formatting them by
 * way of Number() would be harmless for display most of the time and wrong
 * some of the time (0.1 + 0.2), and "most of the time" is not a standard a
 * budget app gets to have. So this is string arithmetic only: split, group,
 * pad. Nothing here ever calls parseFloat.
 */

const DECIMAL = /^(-)?(\d+)(?:\.(\d+))?$/;

/** Normalise "1234.5" -> { negative, int: "1234", frac: "50" }. */
export function splitDecimal(value: string, places = 2) {
  const match = DECIMAL.exec(value.trim());
  if (!match) throw new Error('not a decimal string');
  const [, sign, rawInt = '0', rawFrac = ''] = match;
  if (rawFrac.length > places) throw new Error(`more than ${places} decimal places`);
  const int = rawInt.replace(/^0+(?=\d)/, '');
  const frac = rawFrac.padEnd(places, '0');
  const isZero = /^0+$/.test(int) && /^0*$/.test(frac);
  return { negative: Boolean(sign) && !isZero, int, frac };
}

export function groupThousands(int: string): string {
  return int.replace(/\B(?=(\d{3})+(?!\d))/g, ',');
}

/** "18500" -> "₱18,500.00"; "-5.5" -> "−₱5.50". */
export function formatPHP(value: string, { symbol = '₱', places = 2 } = {}): string {
  const { negative, int, frac } = splitDecimal(value, places);
  const body = `${symbol}${groupThousands(int)}${places ? `.${frac}` : ''}`;
  return negative ? `−${body}` : body;
}

/**
 * Whole centavos as a plain number — for a RATIO or a bar width, never for an
 * amount. An integer count of centavos is exact in a double well past any
 * balance this app will hold; a peso figure with a fraction is not, which is
 * why nothing else here converts.
 */
export function centavos(value: string): number {
  const { negative, int, frac } = splitDecimal(value);
  const whole = Number(`${int}${frac}`);
  return negative ? -whole : whole;
}

/** Whole centavos back to the API's decimal string: 70050 -> "700.50". Integer arithmetic only. */
export function fromCentavos(value: number): string {
  const negative = value < 0;
  const whole = Math.abs(Math.trunc(value));
  const int = Math.floor(whole / 100);
  const frac = String(whole % 100).padStart(2, '0');
  return `${negative ? '-' : ''}${int}.${frac}`;
}

/**
 * TXN-22. A percentage of an amount - "2% of ₱1,000" -> "20.00" - as a
 * SUGGESTION for the cashback field, rounded down to the centavo.
 *
 * Integer arithmetic only, the way every other figure here is handled: the
 * rate becomes hundredths of a per cent (2.5% -> 250), and centavos × that
 * stays exact in a double for any amount this app can hold. The result is only
 * ever a starting point the user can overwrite; what is recorded is whatever
 * ends up in the field.
 */
export function percentOf(amount: string, rate: string): string {
  // A rate is NOT money: the server sends four places ("3.2500"), which the
  // two-place helpers refuse - so it is parsed here, on its own terms.
  const match = /^(\d+)(?:\.(\d{0,4}))?\d*$/.exec(rate.trim());
  if (!match) return '0.00';
  const scaled = BigInt(`${match[1]}${(match[2] ?? '').padEnd(4, '0')}`); // rate x 10,000
  if (scaled <= 0n) return '0.00';
  // BigInt because centavos x rate can pass what a double holds exactly, and
  // integer division rounds down - a suggestion never rounds up into money
  // that was not earned.
  return fromCentavos(Number((BigInt(Math.abs(centavos(amount))) * scaled) / 1000000n));
}

/**
 * Keep only what a typed amount can contain: digits, one decimal point, two
 * places - and one leading minus when `allowNegative`.
 */
export function sanitizeAmount(input: string, { allowNegative = false } = {}): string {
  const negative = allowNegative && input.trimStart().startsWith('-');
  const [whole = '', ...rest] = input.replace(/[^\d.]/g, '').split('.');
  const body = rest.length ? `${whole}.${rest.join('').slice(0, 2)}` : whole;
  return negative ? `-${body}` : body;
}

/**
 * Apply one numpad key to an amount being typed. The typed amount is a
 * string throughout, so what the user sees is exactly what is sent.
 */
export function applyAmountKey(current: string, key: string, { maxInt = 9, places = 2 } = {}): string {
  if (key === 'back') return current.length > 1 ? current.slice(0, -1) : '0';
  const [int = '0', frac] = current.split('.');
  if (key === '.') return frac === undefined && places > 0 ? `${current}.` : current;
  if (!/^\d$/.test(key)) return current;
  if (frac !== undefined) return frac.length < places ? `${current}${key}` : current;
  if (int === '0') return key;
  return int.length < maxInt ? `${current}${key}` : current;
}

/** The typed amount as the API's decimal string: "12." -> "12.00". */
export function toDecimalString(typed: string, places = 2): string {
  const { negative, int, frac } = splitDecimal(typed.endsWith('.') ? typed.slice(0, -1) : typed, places);
  return `${negative ? '-' : ''}${int}.${frac}`;
}
