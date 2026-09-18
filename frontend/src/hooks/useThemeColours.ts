/**
 * The theme.css tokens as colour strings, for the one place a class cannot
 * reach: recharts draws SVG with colour ATTRIBUTES. Read from the live CSS
 * variables, so the charts follow light and dark exactly as everything else
 * does - and re-read when the system scheme or the chosen theme changes.
 */
import { useEffect, useState } from 'react';

const NAMES = ['ink', 'ink-2', 'ink-3', 'line', 'stroke', 'surface', 'surface-2', 'accent', 'ok', 'warn', 'danger'] as const;

export type ThemeColours = Record<(typeof NAMES)[number], string>;

function read(): ThemeColours {
  const style = getComputedStyle(document.documentElement);
  return Object.fromEntries(
    NAMES.map((name) => [name, `rgb(${style.getPropertyValue(`--c-${name}`).trim()})`]),
  ) as ThemeColours;
}

export function useThemeColours(): ThemeColours {
  const [colours, setColours] = useState(read);

  useEffect(() => {
    const update = () => setColours(read());
    const media = window.matchMedia('(prefers-color-scheme: dark)');
    media.addEventListener('change', update);
    const observer = new MutationObserver(update);
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme', 'data-palette'] });
    return () => {
      media.removeEventListener('change', update);
      observer.disconnect();
    };
  }, []);

  return colours;
}
