/**
 * The smallest browser the app needs to be imported outside one.
 *
 * `lib/config.ts` reads the shell's meta tags at module load, so any test that
 * imports a store (which imports the API layer, which imports config) needs a
 * `document` to ask. Answering "no such meta tag" makes it fall back to the
 * production defaults, which is what the tests want anyway. Nothing here is a
 * DOM implementation - no test in this suite renders a component.
 */
import { vi } from 'vitest';

globalThis.document ??= { querySelector: () => null } as unknown as Document;
globalThis.window ??= globalThis as unknown as Window & typeof globalThis;

// Every test mocks the calls it cares about; this catches one it forgot
// rather than letting it reach the company server.
globalThis.fetch = vi.fn(() => Promise.reject(new Error('a test made a real request'))) as typeof fetch;
