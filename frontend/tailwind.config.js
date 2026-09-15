/**
 * Tailwind - mobile-first, 390px baseline (an iPhone 14/15 viewport).
 *
 * Colours are CSS variables (src/styles/theme.css), so light and dark are a
 * variable swap rather than a `dark:` variant on every element. Unprefixed
 * utilities ARE the phone layout; `sm:`/`md:` only ever widen it.
 */

/** A token from theme.css as an rgb() that respects /opacity modifiers. */
const token = (name) => `rgb(var(--c-${name}) / <alpha-value>)`;

/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
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
      },
      fontSize: {
        caption: ['0.75rem', { lineHeight: '1rem' }],
        footnote: ['0.8125rem', { lineHeight: '1.125rem' }],
        body: ['1rem', { lineHeight: '1.375rem' }],
        headline: ['1.0625rem', { lineHeight: '1.375rem', fontWeight: '600' }],
        title: ['1.375rem', { lineHeight: '1.75rem', fontWeight: '700' }],
        display: ['2.5rem', { lineHeight: '2.75rem', fontWeight: '700', letterSpacing: '-0.02em' }],
      },
      borderRadius: {
        card: '1.25rem',
        sheet: '1.75rem',
      },
      spacing: {
        tap: '2.75rem', // 44px - the minimum touch target, everywhere
        tabbar: '4.5rem', // the floating bar, 4rem, and the gap under it
        'safe-b': 'env(safe-area-inset-bottom)',
        'safe-t': 'env(safe-area-inset-top)',
      },
      maxWidth: {
        app: '32rem', // desktop is a widened phone, never a separate design
      },
      boxShadow: {
        card: '0 1px 2px rgb(var(--c-accent) / 0.05), 0 4px 16px rgb(var(--c-accent) / 0.06)',
        bar: '0 8px 28px rgb(var(--c-accent) / 0.16), 0 1px 3px rgb(0 0 0 / 0.06)',
        raised: '0 6px 20px rgb(var(--c-accent) / 0.35)',
        sheet: '0 -8px 32px rgb(0 0 0 / 0.12)',
      },
      transitionTimingFunction: {
        ios: 'cubic-bezier(0.32, 0.72, 0, 1)',
      },
    },
  },
  plugins: [],
};
