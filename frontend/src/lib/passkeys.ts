/**
 * SEC-12 - the browser's half of a passkey: navigator.credentials, and the
 * base64url the server speaks. The server checks everything; this only turns
 * its options into the browser's ArrayBuffers and the answer back into text.
 *
 * Nothing is kept here. The credential lives in the phone's own keychain -
 * Face ID, a fingerprint, Windows Hello - and never in browser storage.
 */
import { api } from './api';
import type { PasskeyAnswer, PasskeyCreationOptions, PasskeyRequestOptions } from './auth';

export interface Passkey {
  id: string;
  label: string | null;
  created: string;
  last_used: string | null;
}

function toBuffer(text: string): ArrayBuffer {
  const base64 = text.replace(/-/g, '+').replace(/_/g, '/').padEnd(Math.ceil(text.length / 4) * 4, '=');
  const bytes = Uint8Array.from(atob(base64), (c) => c.charCodeAt(0));
  return bytes.buffer;
}

function toText(buffer: ArrayBuffer): string {
  let binary = '';
  for (const byte of new Uint8Array(buffer)) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

/** Does this device have its own Face ID, fingerprint or Windows Hello? */
export async function passkeysSupported(): Promise<boolean> {
  try {
    return typeof window.PublicKeyCredential !== 'undefined'
      && await PublicKeyCredential.isUserVerifyingPlatformAuthenticatorAvailable();
  } catch {
    return false;
  }
}

/** The lock screen: ask the device to sign the server's challenge. */
export async function signWithPasskey(options: PasskeyRequestOptions): Promise<PasskeyAnswer> {
  const credential = await navigator.credentials.get({
    publicKey: {
      challenge: toBuffer(options.challenge),
      rpId: options.rpId,
      allowCredentials: options.allowCredentials.map((c) => ({ type: c.type, id: toBuffer(c.id) })),
      userVerification: options.userVerification,
      timeout: options.timeout,
    },
  }) as PublicKeyCredential | null;
  if (!credential) throw new Error('No passkey was used');
  const response = credential.response as AuthenticatorAssertionResponse;
  return {
    credential_id: toText(credential.rawId),
    client_data_json: toText(response.clientDataJSON),
    authenticator_data: toText(response.authenticatorData),
    signature: toText(response.signature),
  };
}

/** Settings: the password first (the server asks for it), then the device makes a key. */
export async function addPasskey(password: string): Promise<Passkey> {
  const options = await api<PasskeyCreationOptions>('/auth/passkeys/options', { method: 'POST', body: { password } });
  const credential = await navigator.credentials.create({
    publicKey: {
      challenge: toBuffer(options.challenge),
      rp: options.rp,
      user: { ...options.user, id: toBuffer(options.user.id) },
      pubKeyCredParams: options.pubKeyCredParams,
      authenticatorSelection: options.authenticatorSelection,
      attestation: options.attestation,
      timeout: options.timeout,
      excludeCredentials: options.excludeCredentials.map((c) => ({ type: c.type, id: toBuffer(c.id) })),
    },
  }) as PublicKeyCredential | null;
  if (!credential) throw new Error('No passkey was made');
  const response = credential.response as AuthenticatorAttestationResponse;
  return api<Passkey>('/auth/passkeys', {
    method: 'POST',
    body: { client_data_json: toText(response.clientDataJSON), attestation_object: toText(response.attestationObject) },
  });
}

export const removePasskey = (id: string) =>
  api<null>(`/auth/passkeys/${encodeURIComponent(id)}`, { method: 'DELETE' });

/** A cancelled prompt is not an error worth a red line - the PIN is right there. */
export function passkeyCancelled(error: unknown): boolean {
  return error instanceof DOMException && (error.name === 'NotAllowedError' || error.name === 'AbortError');
}
