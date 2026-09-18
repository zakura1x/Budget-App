/**
 * The installed app and the offline shell (UX-09, UX-10, SEC-29).
 *
 * The service worker (app/web/static/sw.js) caches the shell and the bundle,
 * never an API response. On lock and sign-out the page empties this app's
 * caches anyway: cache storage is shared with every other app on the host.
 * Only the production build registers it - Vite's dev server has no sw.js.
 */
import { BASE_URL } from './config';

interface InstallPromptEvent extends Event {
  prompt: () => Promise<void>;
  userChoice: Promise<{ outcome: 'accepted' | 'dismissed' }>;
}

let deferred: InstallPromptEvent | null = null;
const listeners = new Set<() => void>();

export function registerServiceWorker(): void {
  window.addEventListener('beforeinstallprompt', (event) => {
    event.preventDefault(); // offered from More instead of popping up uninvited
    deferred = event as InstallPromptEvent;
    listeners.forEach((l) => l());
  });
  if (!import.meta.env.PROD || !('serviceWorker' in navigator)) return;
  window.addEventListener('load', () => {
    navigator.serviceWorker.register(`${BASE_URL}/sw.js`, { scope: `${BASE_URL}/` }).catch(() => {
      /* the app works without it; only the offline shell is lost */
    });
  });
}

export async function clearOfflineCaches(): Promise<void> {
  try {
    navigator.serviceWorker?.controller?.postMessage({ type: 'clear' });
    if ('caches' in window) {
      const keys = await caches.keys();
      await Promise.all(keys.filter((k) => k.startsWith('zbdgt-')).map((k) => caches.delete(k)));
    }
  } catch {
    /* nothing figure-bearing is ever cached; this is belt and braces */
  }
}

export const canInstall = () => deferred !== null;

export function onInstallAvailable(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export async function install(): Promise<boolean> {
  if (!deferred) return false;
  const event = deferred;
  deferred = null;
  await event.prompt();
  const choice = await event.userChoice;
  listeners.forEach((l) => l());
  return choice.outcome === 'accepted';
}

export const isStandalone = () =>
  window.matchMedia('(display-mode: standalone)').matches || (navigator as unknown as { standalone?: boolean }).standalone === true;

export const isIos = () => /iPhone|iPad|iPod/.test(navigator.userAgent);

/**
 * UX-05. The user's theme on <html>; "system" leaves it to the device.
 *
 * It is also remembered in ONE cookie, `zbdgt_theme` - the light/dark word and
 * nothing else - so the lock screen of an app reopened while locked opens in
 * the chosen theme (user's decision, 2026-09-16). The rest of the preferences
 * are encrypted and stay out of the browser (SEC-29). Prefixed and scoped to
 * /ZBDGT like the session cookies (SEC-28), and the server only ever echoes
 * "light" or "dark" back into the page.
 */
export function applyTheme(theme: string | undefined | null): void {
  const root = document.documentElement;
  if (theme === 'light' || theme === 'dark') {
    root.dataset.theme = theme;
    rememberTheme(theme);
  } else {
    delete root.dataset.theme;
    rememberTheme(null);
  }
}

const THEME_COOKIE = 'zbdgt_theme';

const PALETTES = ['candy', 'lime', 'mono'];

/**
 * UX-05 (2026-09-18). The colour palette on <html>; classic is the default and
 * is shown as no attribute at all. Unlike the light/dark word, the palette is
 * NEVER remembered in the browser (invariant 10, user's decision the same
 * day): it lives in the encrypted preferences, so sign-in and the lock screen
 * of a reopened app show classic.
 */
export function applyPalette(palette: string | undefined | null): void {
  const root = document.documentElement;
  if (palette && PALETTES.includes(palette)) root.dataset.palette = palette;
  else delete root.dataset.palette;
}

/**
 * Put the remembered theme on <html> before the first paint. The server does
 * this in the shell already; this covers a shell served from the service
 * worker's cache and the Vite dev server, neither of which saw the cookie.
 */
export function restoreTheme(): void {
  const match = document.cookie.match(/(?:^|;\s*)zbdgt_theme=(light|dark)(?:;|$)/);
  if (match?.[1]) document.documentElement.dataset.theme = match[1];
}

function rememberTheme(theme: 'light' | 'dark' | null): void {
  const secure = window.location.protocol === 'https:' ? '; Secure' : '';
  document.cookie = theme
    ? `${THEME_COOKIE}=${theme}; Path=${BASE_URL}; Max-Age=31536000; SameSite=Strict${secure}`
    : `${THEME_COOKIE}=; Path=${BASE_URL}; Max-Age=0; SameSite=Strict${secure}`;
}
