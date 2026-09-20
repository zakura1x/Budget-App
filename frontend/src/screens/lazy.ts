/**
 * The screens that are NOT in the main bundle, as one list.
 *
 * Two things need them: App.tsx, which wraps each in `lazy()`, and the idle
 * warmer (lib/prefetch.ts), which pulls the chunks down once the app is quiet
 * so the first tap on Stats does not download recharts before it can draw
 * (plan §1.6, step 5). Both go through these thunks, so the list cannot drift.
 */
export const loadAboutEncryption = () => import('./AboutEncryption');
export const loadAdmin = () => import('./Admin');
export const loadBackup = () => import('./Backup');
export const loadGoals = () => import('./Goals');
export const loadProjection = () => import('./Projection');
export const loadRecurring = () => import('./Recurring');
export const loadStats = () => import('./Stats');

/** Warmed in this order: Stats is the heaviest and the most visited of them. */
export const LAZY_SCREENS = [
  loadStats,
  loadRecurring,
  loadProjection,
  loadGoals,
  loadBackup,
  loadAboutEncryption,
  loadAdmin,
];
