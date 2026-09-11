/**
 * Session state. Holds WHO is signed in and WHETHER they are unlocked - never
 * a key, never a token (those are HttpOnly cookies and server memory), and
 * nothing here is persisted to browser storage (SEC-29).
 *
 * The one secret it ever holds is the recovery phrase between sign-up and the
 * "re-enter 3 words" check, in memory only, cleared the moment it is confirmed.
 */
import { create } from 'zustand';
import { ApiError } from '../lib/api';
import { authApi, type AuthConfig, type Session } from '../lib/auth';

export type AuthStatus = 'loading' | 'anonymous' | 'locked' | 'unlocked';

interface AuthState {
  status: AuthStatus;
  session: Session | null;
  config: AuthConfig | null;
  pendingPhrase: string[] | null;
  offerPinSetup: boolean;
  bootError: string | null;

  init: () => Promise<void>;
  login: (email: string, password: string) => Promise<void>;
  register: (input: { email: string; password: string; registration_code: string; display_name?: string }) => Promise<void>;
  confirmPhrase: () => void;
  setPin: (pin: string, currentPassword?: string) => Promise<void>;
  skipPinSetup: () => void;
  lock: () => Promise<void>;
  unlockWithPin: (pin: string) => Promise<void>;
  unlockWithPassword: (password: string) => Promise<void>;
  recover: (phrase: string, newPassword: string) => Promise<void>;
  logout: () => Promise<void>;
  markLocked: () => void;
  markSignedOut: () => void;
}

const statusOf = (s: Session): AuthStatus => (s.locked ? 'locked' : 'unlocked');

export const useAuthStore = create<AuthState>((set, get) => ({
  status: 'loading',
  session: null,
  config: null,
  pendingPhrase: null,
  offerPinSetup: false,
  bootError: null,

  init: async () => {
    try {
      const config = await authApi.config();
      set({ config });
    } catch (e) {
      set({ status: 'anonymous', bootError: (e as Error).message });
      return;
    }
    try {
      const session = await authApi.me();
      set({ session, status: statusOf(session), bootError: null });
    } catch {
      set({ session: null, status: 'anonymous' });
    }
  },

  login: async (email, password) => {
    const session = await authApi.login(email, password);
    set({ session, status: statusOf(session), offerPinSetup: false });
  },

  register: async (input) => {
    const { recovery_phrase, ...session } = await authApi.register(input);
    set({ session, status: statusOf(session), pendingPhrase: recovery_phrase, offerPinSetup: true });
  },

  confirmPhrase: () => set({ pendingPhrase: null }),

  setPin: async (pin, currentPassword) => {
    const session = await authApi.setPin(pin, currentPassword);
    set({ session, offerPinSetup: false });
  },

  skipPinSetup: () => set({ offerPinSetup: false }),

  lock: async () => {
    // Unmount the screens first, so nothing decrypted stays on show while the
    // request is in flight.
    set({ status: 'locked' });
    try {
      await authApi.lock();
    } catch {
      /* the server auto-locks on its own; the screen is already locked */
    }
    const s = get().session;
    if (s) set({ session: { ...s, locked: true, user: { ...s.user, email: null, display_name: null } } });
  },

  unlockWithPin: async (pin) => {
    const session = await authApi.verifyPin(pin);
    set({ session, status: statusOf(session) });
  },

  unlockWithPassword: async (password) => {
    const session = await authApi.unlock(password);
    set({ session, status: statusOf(session) });
  },

  recover: async (phrase, newPassword) => {
    const session = await authApi.recover(phrase, newPassword);
    set({ session, status: statusOf(session), offerPinSetup: true, pendingPhrase: null });
  },

  logout: async () => {
    try {
      await authApi.logout();
    } finally {
      set({ session: null, status: 'anonymous', pendingPhrase: null, offerPinSetup: false });
    }
  },

  markLocked: () => {
    if (get().status === 'unlocked') set({ status: 'locked' });
  },

  markSignedOut: () => set({ session: null, status: 'anonymous', pendingPhrase: null, offerPinSetup: false }),
}));

/** A friendly message for an auth error. */
export function authErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.code === 'OFFLINE') return 'You are offline. Check your connection.';
    return error.detail ?? error.message;
  }
  return 'Something went wrong. Try again.';
}
