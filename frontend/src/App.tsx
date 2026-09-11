/**
 * The app shell: a scrolling screen area above a fixed bottom tab bar, and
 * the add-transaction sheet on top of both.
 *
 * Routes are relative to BASE_URL (/ZBDGT), so /ZBDGT/stats is the Stats tab
 * and a refresh there lands back on it (the server's SPA fallback).
 */
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import { TransactionSheet } from './components/TransactionSheet';
import { BottomTabBar } from './components/BottomTabBar';
import { BASE_URL } from './lib/config';
import { Calendar } from './screens/Calendar';
import { Home } from './screens/Home';
import { More } from './screens/More';
import { Stats } from './screens/Stats';
import { useUiStore } from './stores/uiStore';

export function App() {
  const openAddSheet = useUiStore((s) => s.openAddSheet);

  return (
    <BrowserRouter basename={BASE_URL}>
      <div className="mx-auto min-h-dvh max-w-app px-safe pt-safe">
        {/* bottom padding clears the tab bar, the raised [+] and the home indicator */}
        <main className="pb-[calc(theme(spacing.tabbar)+env(safe-area-inset-bottom)+2rem)]">
          <Routes>
            <Route path="/" element={<Home />} />
            <Route path="/calendar" element={<Calendar />} />
            <Route path="/stats" element={<Stats />} />
            <Route path="/more" element={<More />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </main>
      </div>
      <BottomTabBar onAdd={openAddSheet} />
      <TransactionSheet />
    </BrowserRouter>
  );
}
