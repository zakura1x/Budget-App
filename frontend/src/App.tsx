/**
 * The app shell and its one decision: which world is the user in?
 *
 *   loading     the skeleton, while /auth/me answers
 *   anonymous   sign in · create account · forgot / reset password - nothing
 *               else routes
 *   locked      the lock screen, and ONLY the lock screen: the app screens
 *               are unmounted, so nothing decrypted stays in the page
 *   unlocked    the PIN offer after sign-up, then the tabs
 *
 * Routes are relative to BASE_URL (/ZBDGT); a refresh on /ZBDGT/stats lands
 * back on Stats through the server's SPA fallback.
 */
import { lazy, Suspense, useEffect } from 'react';
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import { BottomTabBar } from './components/BottomTabBar';
import { Offline } from './components/Offline';
import { RefreshLine } from './components/RefreshLine';
import { RuleSheetHost } from './components/RuleSheetHost';
import { useOnline } from './hooks/useOnline';
import { usePreferencesStore } from './stores/preferencesStore';
import { Splash } from './components/Splash';
import { TransactionPreview } from './components/TransactionPreview';
import { TransactionSheet } from './components/TransactionSheet';
import { UndoToast } from './components/UndoToast';
import { useAutoLock } from './hooks/useAutoLock';
import { useCatchUp } from './hooks/useCatchUp';
import { clearScrollMemory, useScrollMemory } from './hooks/useScrollMemory';
import { LOCKED_EVENT, SIGNED_OUT_EVENT } from './lib/api';
import { BASE_URL } from './lib/config';
import { warmLazyScreens, warmOnUnlock } from './lib/prefetch';
import { queryClient } from './lib/queryClient';
import * as lazyScreens from './screens/lazy';
import { AccountDetail } from './screens/AccountDetail';
import { Accounts } from './screens/Accounts';
import { Budget } from './screens/Budget';
import { Calendar } from './screens/Calendar';
import { Categories } from './screens/Categories';
import { ForgotPassword } from './screens/ForgotPassword';
import { Ledger } from './screens/Ledger';
import { Home } from './screens/Home';
import { Login } from './screens/Login';
import { More } from './screens/More';
import { PinLock } from './screens/PinLock';
import { PinSetup } from './screens/PinSetup';
import { Register } from './screens/Register';
import { ResetPassword } from './screens/ResetPassword';
import { Settings } from './screens/Settings';
import { Tags } from './screens/Tags';
import { useAuthStore } from './stores/authStore';
import { useBudgetStore } from './stores/budgetStore';
import { useLedgerStore } from './stores/ledgerStore';
import { useUiStore } from './stores/uiStore';

// Loaded when first opened (Phase 10): Stats carries recharts, the largest
// dependency, and the rest are visited rarely. Everything on the way to Home
// and the add sheet stays in the main bundle.
const AboutEncryption = lazy(() => lazyScreens.loadAboutEncryption().then((m) => ({ default: m.AboutEncryption })));
const Admin = lazy(() => lazyScreens.loadAdmin().then((m) => ({ default: m.Admin })));
const Backup = lazy(() => lazyScreens.loadBackup().then((m) => ({ default: m.Backup })));
const Goals = lazy(() => lazyScreens.loadGoals().then((m) => ({ default: m.Goals })));
const Projection = lazy(() => lazyScreens.loadProjection().then((m) => ({ default: m.Projection })));
const Recurring = lazy(() => lazyScreens.loadRecurring().then((m) => ({ default: m.Recurring })));
const RecentlyDeleted = lazy(() => lazyScreens.loadRecentlyDeleted().then((m) => ({ default: m.RecentlyDeleted })));
const Stats = lazy(() => lazyScreens.loadStats().then((m) => ({ default: m.Stats })));

function SignedOutRoutes() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/register" element={<Register />} />
      <Route path="/forgot" element={<ForgotPassword />} />
      <Route path="/reset" element={<ResetPassword />} />
      <Route path="*" element={<Navigate to="/login" replace />} />
    </Routes>
  );
}

function AppTabs() {
  const openAddSheet = useUiStore((s) => s.openAddSheet);
  useScrollMemory(); // come back to a tab where you left it (step 6)
  return (
    <>
      <RefreshLine />
      <div className="mx-auto min-h-dvh max-w-app px-safe pt-safe">
        {/* bottom padding clears the tab bar, the raised [+] and the home indicator */}
        <main className="pb-[calc(theme(spacing.tabbar)+env(safe-area-inset-bottom)+2rem)]">
          <Suspense fallback={<div className="skeleton mt-16 h-96 rounded-card" aria-hidden="true" />}>
          <Routes>
            <Route path="/" element={<Home />} />
            <Route path="/calendar" element={<Calendar />} />
            <Route path="/stats" element={<Stats />} />
            <Route path="/more" element={<More />} />
            <Route path="/accounts" element={<Accounts />} />
            <Route path="/accounts/:id" element={<AccountDetail />} />
            <Route path="/categories" element={<Categories />} />
            <Route path="/tags" element={<Tags />} />
            <Route path="/recurring" element={<Recurring />} />
            <Route path="/projection" element={<Projection />} />
            <Route path="/backup" element={<Backup />} />
            <Route path="/goals" element={<Goals />} />
            <Route path="/about-encryption" element={<AboutEncryption />} />
            <Route path="/admin" element={<Admin />} />
            <Route path="/transactions" element={<Ledger />} />
            <Route path="/deleted" element={<RecentlyDeleted />} />
            <Route path="/budget" element={<Budget />} />
            <Route path="/settings" element={<Settings />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
          </Suspense>
        </main>
      </div>
      <BottomTabBar onAdd={() => openAddSheet()} />
      <TransactionSheet />
      <TransactionPreview />
      <RuleSheetHost />
      <UndoToast />
    </>
  );
}

function Unlocked() {
  const offerPinSetup = useAuthStore((s) => s.offerPinSetup);
  const pinEnabled = useAuthStore((s) => s.config?.pin_enabled ?? true);
  const pinSet = useAuthStore((s) => s.session?.pin_set ?? false);
  if (offerPinSetup && pinEnabled && !pinSet) return <PinSetup />;
  return <AppTabs />;
}

export function App() {
  const status = useAuthStore((s) => s.status);
  const init = useAuthStore((s) => s.init);
  const lock = useAuthStore((s) => s.lock);
  const markLocked = useAuthStore((s) => s.markLocked);
  const markSignedOut = useAuthStore((s) => s.markSignedOut);
  const serverLockMinutes = useAuthStore((s) => s.session?.auto_lock_minutes ?? 5);
  const preferredLock = usePreferencesStore((s) => s.prefs?.auto_lock_minutes);
  const autoLockMinutes = Math.min(preferredLock ?? serverLockMinutes, serverLockMinutes);
  const loadPreferences = usePreferencesStore((s) => s.load);
  const resetPreferences = usePreferencesStore((s) => s.reset);
  const online = useOnline();
  const closeAddSheet = useUiStore((s) => s.closeAddSheet);
  const resetLedger = useLedgerStore((s) => s.reset);
  const resetBudget = useBudgetStore((s) => s.reset);

  useEffect(() => {
    void init();
  }, [init]);

  useEffect(() => {
    window.addEventListener(LOCKED_EVENT, markLocked);
    window.addEventListener(SIGNED_OUT_EVENT, markSignedOut);
    return () => {
      window.removeEventListener(LOCKED_EVENT, markLocked);
      window.removeEventListener(SIGNED_OUT_EVENT, markSignedOut);
    };
  }, [markLocked, markSignedOut]);

  // Anything open over the app closes when it locks or signs out - and the
  // decrypted rows the page was holding go with it, as the server's working
  // set goes with the key. That includes the query cache (SEC-29): every
  // figure any screen fetched is dropped here, not kept for the next unlock.
  useEffect(() => {
    if (status !== 'unlocked') {
      closeAddSheet();
      queryClient.clear();
      clearScrollMemory();
      resetLedger();
      resetBudget();
      // Locked (or still loading) is the same person, so the theme stays; signed
      // out is not - the next person on this device gets the device's setting (UX-05).
      resetPreferences({ keepTheme: status !== 'anonymous' });
    } else {
      void loadPreferences(); // the theme, the week start, the auto-lock choice
      warmOnUnlock(); // the answers every screen needs, while Home is still drawing
      warmLazyScreens(); // and the chunks for Stats and friends, once things are quiet
    }
  }, [status, closeAddSheet, resetLedger, resetBudget, resetPreferences, loadPreferences]);

  useAutoLock(status === 'unlocked', autoLockMinutes, () => void lock());
  useCatchUp(status === 'unlocked');

  if (!online) return <Offline />;

  return (
    <BrowserRouter basename={BASE_URL}>
      {status === 'loading' && <Splash />}
      {status === 'anonymous' && <SignedOutRoutes />}
      {status === 'locked' && <PinLock />}
      {status === 'unlocked' && <Unlocked />}
    </BrowserRouter>
  );
}
