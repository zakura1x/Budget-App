import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { App } from './App';
import { registerServiceWorker, restoreTheme } from './lib/pwa';
import './styles/index.css';

restoreTheme(); // UX-05 - the lock screen of a reopened app keeps the chosen theme
registerServiceWorker();

const root = document.getElementById('root');
if (!root) throw new Error('#root missing from the shell');

createRoot(root).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
