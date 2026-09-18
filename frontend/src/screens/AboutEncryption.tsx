/**
 * About your encryption (UX-12) - what is protected and what is not, in plain
 * words. No security theatre: the limits are stated as plainly as the
 * protections.
 */
import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { ScreenHeader } from '../components/ScreenHeader';
import { Button } from '../components/ui/Button';
import { Card, SectionTitle } from '../components/ui/Card';
import { canInstall, install, isIos, isStandalone, onInstallAvailable } from '../lib/pwa';

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <>
      <SectionTitle>{title}</SectionTitle>
      <Card className="space-y-2 text-body text-ink-2 [&_strong]:font-semibold [&_strong]:text-ink">{children}</Card>
    </>
  );
}

export function AboutEncryption() {
  const navigate = useNavigate();
  const [installable, setInstallable] = useState(canInstall());
  useEffect(() => onInstallAvailable(() => setInstallable(canInstall())), []);

  return (
    <>
      <ScreenHeader
        title="Your encryption"
        subtitle={<button type="button" className="text-accent-ink" onClick={() => navigate(-1)}>‹ Back</button>}
      />

      <Section title="What is protected">
        <p>
          <strong>Every amount, name, date, note and receipt</strong> is encrypted before it reaches the company database,
          with a key that belongs to your account alone (AES-256). Someone who can read the database sees scrambled bytes.
        </p>
        <p>Each row is bound to its own place, so rows cannot be swapped around unnoticed either.</p>
      </Section>

      <Section title="What is not">
        <p>The database can see <strong>that</strong> you have an account, how many rows each part of the app holds, and when rows were written or changed — not what is in them.</p>
        <p>Your email is stored only as a one-way fingerprint for signing in.</p>
      </Section>

      <Section title="Who can read your data">
        <p><strong>You</strong>, signed in and unlocked.</p>
        <p><strong>Whoever runs this server</strong> holds the master key that unlocks every account, so trust them the way you trust your bank’s staff.</p>
        <p><strong>Not the admin of the app, and not the database’s administrators.</strong> The admin can disable or delete an account, but can’t see a single figure in it.</p>
      </Section>

      <Section title="If something is lost">
        <p><strong>Forgot your password?</strong> Use “Forgot your password?” on the sign-in screen and a link comes to your email. Your data isn’t locked to your password, so nothing is lost with it — which also means anyone who can read your email could reset it. Keep that mailbox secure.</p>
        <p><strong>The server’s key</strong> is kept by whoever runs this server, with a copy stored away from it. There is no second key: if that key and every copy were lost, no one could open any account.</p>
        <p>If someone may have got hold of your key, Settings can rotate it.</p>
      </Section>

      <Section title="Backups and exports">
        <p><strong>Backups stay encrypted</strong> — safe on a USB stick or in cloud storage. They open with this server’s key, here or on a new server set up with the same key.</p>
        <p><strong>A CSV export is not encrypted.</strong> It is the one way your data leaves in plain form, and the app warns you each time.</p>
      </Section>

      <Section title="This device">
        <p>Nothing from your account is saved on the phone. Locking the app clears your key from the server’s memory, and offline the app shows no figures at all.</p>
        {!isStandalone() && installable && (
          <Button className="mt-2" block variant="secondary" onClick={() => void install().then(() => setInstallable(canInstall()))}>
            Install the app on this device
          </Button>
        )}
        {!isStandalone() && isIos() && (
          <p>To install on iPhone: tap <strong>Share</strong> in Safari, then <strong>Add to Home Screen</strong>.</p>
        )}
      </Section>
    </>
  );
}
