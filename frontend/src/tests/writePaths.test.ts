/**
 * Every write tells the app what it touched (misc/UX_RESPONSIVENESS_PLAN.md
 * Part 3, and the CLAUDE.md rule "a component never invalidates by hand").
 *
 * This reads the source rather than running it, because what went wrong before
 * was never a broken function - it was a call site that simply forgot. Six of
 * eleven did: paying a plan, paying an occurrence early, typing a balance on
 * the Accounts tab, renaming a category, deleting a tag and attaching a
 * receipt all wrote something the rest of the app never heard about.
 *
 * So: any component that calls a mutating API helper must also go through
 * `afterWrite`, or through the `Outcome` paths that already do the whole job.
 * A new write added next month fails this test until it says what it touched.
 */
import { describe, expect, it } from 'vitest';

// Vite reads the sources for us - no node APIs, and the glob is checked at
// build time, so a renamed folder fails here rather than silently matching
// nothing.
// The options must be an inline literal - Vite reads this at build time.
const libSources = import.meta.glob('../lib/*.ts', { query: '?raw', import: 'default', eager: true }) as Record<string, string>;
const screenSources = {
  ...(import.meta.glob('../components/*.tsx', { query: '?raw', import: 'default', eager: true }) as Record<string, string>),
  ...(import.meta.glob('../screens/*.tsx', { query: '?raw', import: 'default', eager: true }) as Record<string, string>),
};

/** '../components/AccountSheet.tsx' -> 'components/AccountSheet.tsx' */
const shortName = (path: string) => path.replace('../', '');

/** The helpers in lib/ that change something on the server. */
function mutatingHelpers(): Set<string> {
  const found = new Set<string>();
  for (const text of Object.values(libSources)) {
    for (const m of text.matchAll(/export const (\w+) = [^;]*?method: '(?:POST|PUT|PATCH|DELETE)'/gs)) {
      found.add(m[1]!);
    }
  }
  return found;
}

/**
 * Writes that reach no figure, with the reason. Anything else must invalidate.
 */
const EXEMPT: Record<string, string> = {
  'components/SecuritySheets.tsx':
    'a password change, a DEK rotation and account deletion end the session - App.tsx clears every cache on the way out',
  'screens/Admin.tsx':
    'activating or deleting another user touches no figure this account can see',
  'screens/Payoff.tsx':
    'the payoff planner (REC-35) is a POST only to carry the typed payments - it writes nothing',
};

/**
 * The three ways a component may legitimately announce a write. Matched as
 * CALLS, not names: an `import { afterWrite }` left behind after the call was
 * deleted is exactly the regression this test exists to catch.
 */
const ANNOUNCES = [/afterWrite\s*\(/, /applyOutcome\s*\(/, /removeIds\s*\(/];

describe('every write says what it touched', () => {
  const helpers = mutatingHelpers();

  it('finds the mutating helpers to check against', () => {
    // A guard on the guard: if lib/ is restructured and this finds nothing,
    // the test below would pass by vacuously checking no files at all.
    expect(helpers.size).toBeGreaterThan(30);
    expect(helpers).toContain('createTransaction');
    expect(helpers).toContain('payPlan');
  });

  const screens = Object.entries(screenSources).map(([path, text]) => ({ name: shortName(path), text }));

  for (const { name, text } of screens) {
    const used = [...helpers].filter((fn) => new RegExp(`\\b${fn}\\(`).test(text)).sort();
    if (used.length === 0) continue;

    it(`${name} (${used.join(', ')})`, () => {
      if (EXEMPT[name]) {
        expect(EXEMPT[name], `${name} is exempt but now announces a write - remove the exemption`)
          .toBeTruthy();
        return;
      }
      const announces = ANNOUNCES.some((call) => call.test(text));
      expect(announces, `${name} writes (${used.join(', ')}) but never calls afterWrite`).toBe(true);
    });
  }

  it('keeps the exemption list honest', () => {
    for (const name of Object.keys(EXEMPT)) {
      expect(screens.find((f) => f.name === name), `${name} is exempt but no longer exists`).toBeDefined();
    }
  });
});

describe('the sheets do not fetch their own copies', () => {
  // Step 8: the add sheet asked for accounts, categories and tags on every tap
  // of [+], the most used button in the app. They read the cache now.
  const SHEETS = [
    'components/TransactionSheet.tsx',
    'components/AccountSheet.tsx',
    'components/StatementSheet.tsx',
    'components/TransactionPreview.tsx',
    'components/BillSheet.tsx',
  ];
  const DIRECT = /\b(listAccounts|listCategories|listTags|listRules)\(/;

  for (const name of SHEETS) {
    it(name, () => {
      const text = screenSources[`../${name}`];
      expect(text, `${name} no longer exists`).toBeDefined();
      expect(DIRECT.test(text!), `${name} fetches a lookup directly - use ensure* from lib/prefetch`).toBe(false);
    });
  }
});
