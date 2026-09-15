/**
 * Offline (UX-10): the shell opens and says so - and shows no figures. Nothing
 * is kept on the device to show; the screens with money unmount while this is
 * up, and come back when the connection does.
 */
import { AuthLayout } from './AuthLayout';
import { Button } from './ui/Button';

export function Offline() {
  return (
    <AuthLayout title="You’re offline" subtitle="Budget App needs a connection to show your money.">
      <p className="text-body text-ink-2">
        Nothing from your account is stored on this device, so there is nothing to show until you are back online. Entries
        can’t be added offline yet.
      </p>
      <Button className="mt-6" block size="lg" onClick={() => window.location.reload()}>Try again</Button>
    </AuthLayout>
  );
}
