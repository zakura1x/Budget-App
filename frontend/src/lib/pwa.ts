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

/** UX-05. The stored theme on <html>; "system" leaves it to the device. */
export function applyTheme(theme: string | undefined | null): void {
  const root = document.documentElement;
  if (theme === 'light' || theme === 'dark') root.dataset.theme = theme;
  else delete root.dataset.theme;
}
