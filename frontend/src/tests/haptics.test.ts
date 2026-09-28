/**
 * UX-14 - the vibration follows the preference, and a phone that cannot
 * vibrate (every iPhone) is simply left alone.
 */
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { Preferences } from '../lib/budgets';
import { buzz } from '../lib/haptics';
import { usePreferencesStore } from '../stores/preferencesStore';

const prefs = (haptics?: boolean) => ({ haptics } as unknown as Preferences);

describe('buzz', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    usePreferencesStore.setState({ prefs: null });
  });

  it('vibrates by default, and not once it is turned off', () => {
    const vibrate = vi.fn(() => true);
    vi.stubGlobal('navigator', { vibrate });
    buzz('tap');
    expect(vibrate).toHaveBeenCalledWith(8);
    usePreferencesStore.setState({ prefs: prefs(false) });
    buzz('success');
    expect(vibrate).toHaveBeenCalledTimes(1);
  });

  it('does nothing where the browser has no vibration', () => {
    vi.stubGlobal('navigator', {});
    expect(() => buzz('warn')).not.toThrow();
  });

  it('never lets a refusing browser break a save', () => {
    vi.stubGlobal('navigator', { vibrate: () => { throw new Error('blocked'); } });
    expect(() => buzz('error')).not.toThrow();
  });
});
