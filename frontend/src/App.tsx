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
import { useEffect } from 'react';
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import { BottomTabBar } from './components/BottomTabBar';
import { Offline } from './components/Offline';
import { useOnline } from './hooks/useOnline';
import { AboutEncryption } from './screens/AboutEncryption';
import { Admin } from './screens/Admin';
import { Goals } from './screens/Goals';
import { usePreferencesStore } from './stores/preferencesStore';
import { Splash } from './components/Splash';
import { TransactionSheet } from './components/TransactionSheet';
import { useAutoLock } from './hooks/useAutoLock';
import { LOCKED_EVENT, SIGNED_OUT_EVENT } from './lib/api';
import { BASE_URL } from './lib/config';
import { Accounts } from './screens/Accounts';
import { Backup } from './screens/Backup';
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
import { Projection } from './screens/Projection';
import { Recurring } from './screens/Recurring';
import { Stats } from './screens/Stats';
import { Tags } from './screens/Tags';
import { useAuthStore } from './stores/authStore';
import { useBudgetStore } from './stores/budgetStore';
import { useLedgerStore } from './stores/ledgerStore';
import { useUiStore } from './stores/uiStore';

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
  return (
    <>
      <div className="mx-auto min-h-dvh max-w-app px-safe pt-safe">
        {/* bottom padding clears the tab bar, the raised [+] and the home indicator */}
        <main className="pb-[calc(theme(spacing.tabbar)+env(safe-area-inset-bottom)+2rem)]">
          <Routes>
            <Route path="/" element={<Home />} />
            <Route path="/calendar" element={<Calendar />} />
            <Route path="/stats" element={<Stats />} />
            <Route path="/more" element={<More />} />
            <Route path="/accounts" element={<Accounts />} />
            <Route path="/categories" element={<Categories />} />
            <Route path="/tags" element={<Tags />} />
            <Route path="/recurring" element={<Recurring />} />
            <Route path="/projection" element={<Projection />} />
            <Route path="/backup" element={<Backup />} />
            <Route path="/goals" element={<Goals />} />
            <Route path="/about-encryption" element={<AboutEncryption />} />
            <Route path="/admin" element={<Admin />} />
            <Route path="/transactions" element={<Ledger />} />
            <Route path="/budget" element={<Budget />} />
            <Route path="/settings" element={<Settings />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </main>
      </div>
      <BottomTabBar onAdd={() => openAddSheet()} />
      <TransactionSheet />
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
  // set goes with the key.
  useEffect(() => {
    if (status !== 'unlocked') {
      closeAddSheet();
      resetLedger();
      resetBudget();
      resetPreferences();
    } else {
      void loadPreferences(); // the theme, the week start, the auto-lock choice
    }
  }, [status, closeAddSheet, resetLedger, resetBudget, resetPreferences, loadPreferences]);

  useAutoLock(status === 'unlocked', autoLockMinutes, () => void lock());

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
