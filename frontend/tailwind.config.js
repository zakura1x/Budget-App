/**
 * Tailwind - mobile-first, 390px baseline (an iPhone 14/15 viewport).
 *
 * Colours are CSS variables (src/styles/theme.css), so light and dark - and
 * the four palettes - are a variable swap rather than a `dark:` variant on
 * every element. Unprefixed utilities ARE the phone layout; `sm:`/`md:` only
 * ever widen it.
 *
 * Neo-brutalism (2026-09-18): the look is carried by an outline and a HARD
 * offset shadow, both drawn as box-shadows so they never move the layout.
 * `shadow-card` is the tile, `shadow-edge` the outline alone (inner controls),
 * `shadow-pressed` what a pressed button sinks to. Corners are small (8px)
 * and the radius scale is REPLACED, not extended, so every older rounded-2xl
 * lands on it too.
 */

/** A token from theme.css as an rgb() that respects /opacity modifiers. */
const token = (name) => `rgb(var(--c-${name}) / <alpha-value>)`;

/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    // Replaced, not extended: one small corner everywhere (the "mix" look).
    borderRadius: {
      none: '0',
      sm: '0.125rem',
      DEFAULT: '0.25rem',
      md: '0.375rem',
      lg: '0.375rem',
      xl: '0.5rem',
      '2xl': '0.5rem',
      '3xl': '0.625rem',
      full: '9999px',
    },
    screens: {
      sm: '430px', // large phones
      md: '768px', // tablets - still the phone layout, centred
      lg: '1024px',
    },
    extend: {
      colors: {
        bg: token('bg'),
        surface: token('surface'),
        'surface-2': token('surface-2'),
        ink: token('ink'),
        'ink-2': token('ink-2'),
        'ink-3': token('ink-3'),
        line: token('line'),
        accent: token('accent'),
        'accent-soft': token('accent-soft'),
        'accent-ink': token('accent-ink'),
        stroke: token('stroke'),
        shadow: token('shadow'),
        'on-accent': token('on-accent'),
        highlight: token('highlight'),
        'on-highlight': token('on-highlight'),
        ok: token('ok'),
        warn: token('warn'),
        danger: token('danger'),
      },
      fontFamily: {
        sans: [
          '-apple-system', 'BlinkMacSystemFont', '"SF Pro Text"', '"Segoe UI"',
          'Roboto', '"Helvetica Neue"', 'Arial', 'sans-serif',
        ],
        // Every amount (.num) and every small label. Self-hosted in
        // src/styles/fonts - CSP is font-src 'self', and the PWA must work offline.
        mono: ['"JetBrains Mono"', 'ui-monospace', '"SF Mono"', 'Consolas', 'monospace'],
      },
      fontSize: {
        caption: ['0.75rem', { lineHeight: '1rem' }],
        footnote: ['0.8125rem', { lineHeight: '1.125rem' }],
        body: ['1rem', { lineHeight: '1.375rem' }],
        headline: ['1.0625rem', { lineHeight: '1.375rem', fontWeight: '600' }],
        title: ['1.375rem', { lineHeight: '1.75rem', fontWeight: '700' }],
        display: ['2.5rem', { lineHeight: '2.75rem', fontWeight: '700', letterSpacing: '-0.02em' }],
        // A figure inside a ring: mono digits are wide, and ₱12,345.67 must fit the Home ring.
        figure: ['1.875rem', { lineHeight: '2.25rem', fontWeight: '700' }],
      },
      borderRadius: {
        card: '0.5rem',
        sheet: '0.875rem',
      },
      spacing: {
        tap: '2.75rem', // 44px - the minimum touch target, everywhere
        lift: 'var(--lift)', // a pressed control moves this far, onto its shadow
        tabbar: '4.5rem', // the floating bar, 4rem, and the gap under it
        'safe-b': 'env(safe-area-inset-bottom)',
        'safe-t': 'env(safe-area-inset-top)',
      },
      maxWidth: {
        app: '32rem', // desktop is a widened phone, never a separate design
      },
      boxShadow: {
        edge: 'var(--edge)',
        card: 'var(--edge), var(--lift) var(--lift) 0 var(--bw) rgb(var(--c-shadow))',
        bar: 'var(--edge), var(--lift) var(--lift) 0 var(--bw) rgb(var(--c-shadow))',
        raised: 'var(--edge), calc(var(--lift) * 1.5) calc(var(--lift) * 1.5) 0 var(--bw) rgb(var(--c-shadow))',
        pressed: 'var(--edge), 1px 1px 0 var(--bw) rgb(var(--c-shadow))',
        sheet: 'var(--edge)',
      },
      transitionTimingFunction: {
        ios: 'cubic-bezier(0.32, 0.72, 0, 1)',
      },
    },
  },
  plugins: [],
};
