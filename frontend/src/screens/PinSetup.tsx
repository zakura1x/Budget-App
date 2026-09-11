/**
 * Choose a PIN - offered right after sign-up and after recovery.
 *
 * The PIN only unlocks this device's session (SEC-07); it is not a password
 * and it never touches the encryption. Skipping is allowed: a locked screen
 * then asks for the password instead.
 */
import { useState } from 'react';
import { AuthLayout, FormError } from '../components/AuthLayout';
import { PinPad } from '../components/PinPad';
import { Button } from '../components/ui/Button';
import { authErrorMessage, useAuthStore } from '../stores/authStore';

export function PinSetup() {
  const length = useAuthStore((s) => s.config?.pin_length ?? 6);
  const setPin = useAuthStore((s) => s.setPin);
  const skip = useAuthStore((s) => s.skipPinSetup);
  const [first, setFirst] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [errorKey, setErrorKey] = useState(0);
  const [busy, setBusy] = useState(false);

  const onComplete = async (pin: string) => {
    if (first === null) {
      setFirst(pin);
      setError(null);
      setErrorKey(0);
      return;
    }
    if (pin !== first) {
      setFirst(null);
      setError('The two PINs did not match. Start again.');
      setErrorKey((k) => k + 1);
      return;
    }
    setBusy(true);
    try {
      await setPin(pin);
    } catch (err) {
      setFirst(null);
      setError(authErrorMessage(err));
      setErrorKey((k) => k + 1);
    } finally {
      setBusy(false);
    }
  };

  return (
    <AuthLayout
      title={first === null ? 'Choose a PIN' : 'Enter it again'}
      subtitle={`${length} digits to unlock the app on this device. Your password stays the key to your account.`}
      footer={<Button variant="ghost" onClick={skip}>Skip - I will unlock with my password</Button>}
    >
      <div className="mb-4 min-h-6"><FormError message={error} /></div>
      <PinPad key={first === null ? 'first' : 'second'} length={length} onComplete={onComplete} busy={busy}
        errorKey={errorKey} />
    </AuthLayout>
  );
}
