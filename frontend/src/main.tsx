import { QueryClientProvider } from '@tanstack/react-query';
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { App } from './App';
import { registerServiceWorker, restoreTheme } from './lib/pwa';
import { queryClient } from './lib/queryClient';
import './styles/index.css';

restoreTheme(); // UX-05 - the lock screen of a reopened app keeps the chosen theme
registerServiceWorker();

const root = document.getElementById('root');
if (!root) throw new Error('#root missing from the shell');

createRoot(root).render(
  <StrictMode>
    {/* The cache the screens read (plan §2.1). It is page memory only, and
        App.tsx empties it the moment the app locks or signs out (SEC-29). */}
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>
  </StrictMode>,
);
