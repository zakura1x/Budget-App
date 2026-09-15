import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { App } from './App';
import { registerServiceWorker } from './lib/pwa';
import './styles/index.css';

registerServiceWorker();

const root = document.getElementById('root');
if (!root) throw new Error('#root missing from the shell');

createRoot(root).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
