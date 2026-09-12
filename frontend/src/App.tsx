/**
 * The app shell and its one decision: which world is the user in?
 *
 *   loading     the skeleton, while /auth/me answers
 *   anonymous   sign in · create account · recover - nothing else routes
 *   locked      the lock screen, and ONLY the lock screen: the app screens
 *               are unmounted, so nothing decrypted stays in the page
 *   unlocked    first-run steps if pending (the 12 words, then the PIN),
 *               then the tabs
 *
 * Routes are relative to BASE_URL (/ZBDGT); a refresh on /ZBDGT/stats lands
 * back on Stats through the server's SPA fallback.
 */
import { useEffect } from 'react';
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import { BottomTabBar } from './components/BottomTabBar';
import { Splash } from './components/Splash';
import { TransactionSheet } from './components/TransactionSheet';
import { useAutoLock } from './hooks/useAutoLock';
import { LOCKED_EVENT, SIGNED_OUT_EVENT } from './lib/api';
import { BASE_URL } from './lib/config';
import { Accounts } from './screens/Accounts';
import { Calendar } from './screens/Calendar';
import { Categories } from './screens/Categories';
import { Home } from './screens/Home';
import { Login } from './screens/Login';
import { More } from './screens/More';
import { PinLock } from './screens/PinLock';
import { PinSetup } from './screens/PinSetup';
import { RecoveryPhraseEnter } from './screens/RecoveryPhraseEnter';
import { RecoveryPhraseSetup } from './screens/RecoveryPhraseSetup';
import { Register } from './screens/Register';
import { Stats } from './screens/Stats';
import { useAuthStore } from './stores/authStore';
import { useUiStore } from './stores/uiStore';

function SignedOutRoutes() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/register" element={<Register />} />
      <Route path="/recover" element={<RecoveryPhraseEnter />} />
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
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </main>
      </div>
      <BottomTabBar onAdd={openAddSheet} />
      <TransactionSheet />
    </>
  );
}

function Unlocked() {
  const pendingPhrase = useAuthStore((s) => s.pendingPhrase);
  const offerPinSetup = useAuthStore((s) => s.offerPinSetup);
  const pinEnabled = useAuthStore((s) => s.config?.pin_enabled ?? true);
  const pinSet = useAuthStore((s) => s.session?.pin_set ?? false);
  if (pendingPhrase) return <RecoveryPhraseSetup />;
  if (offerPinSetup && pinEnabled && !pinSet) return <PinSetup />;
  return <AppTabs />;
}

export function App() {
  const status = useAuthStore((s) => s.status);
  const init = useAuthStore((s) => s.init);
  const lock = useAuthStore((s) => s.lock);
  const markLocked = useAuthStore((s) => s.markLocked);
  const markSignedOut = useAuthStore((s) => s.markSignedOut);
  const autoLockMinutes = useAuthStore((s) => s.session?.auto_lock_minutes ?? 5);
  const closeAddSheet = useUiStore((s) => s.closeAddSheet);

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

  // Anything open over the app closes when it locks or signs out.
  useEffect(() => {
    if (status !== 'unlocked') closeAddSheet();
  }, [status, closeAddSheet]);

  useAutoLock(status === 'unlocked', autoLockMinutes, () => void lock());

  return (
    <BrowserRouter basename={BASE_URL}>
      {status === 'loading' && <Splash />}
      {status === 'anonymous' && <SignedOutRoutes />}
      {status === 'locked' && <PinLock />}
      {status === 'unlocked' && <Unlocked />}
    </BrowserRouter>
  );
}
