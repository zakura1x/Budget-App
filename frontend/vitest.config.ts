/**
 * Vitest - the caching layer's tests (misc/UX_RESPONSIVENESS_PLAN.md §4.4).
 *
 * Kept apart from vite.config.ts so the build config stays exactly what it
 * was. These tests cover logic that fails SILENTLY - a freshness guard that
 * skips a fetch it should have made shows a wrong number, not an error - so
 * they assert on how many times a fetcher was called, not just on its result.
 *
 * No DOM: nothing here renders a component. `src/tests/setup.ts` provides the
 * two globals `lib/config.ts` needs at import time.
 */
import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    environment: 'node',
    include: ['src/tests/**/*.test.ts'],
    setupFiles: ['./src/tests/setup.ts'],
    restoreMocks: true,
  },
});
