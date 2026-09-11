"""
Startup self-test: prove the loaded master key and the cipher stack work
before the first request is served.

A throwaway DEK is generated, wrapped under the current master key, unwrapped,
and used to seal and open a row. Nothing touches the database and nothing is
kept. If any step fails the process refuses to start - the same stance config
takes on a malformed key, extended to a key that parses but does not work.

/health reports the result as a yes/no. It never reports anything derived from
the key itself, not even a fingerprint: a fingerprint would let an observer
tell two deployments' keys apart, which is more than a health check needs.
"""

import logging

from app.core.crypto.dek import generate_dek, unwrap_dek, wrap_dek, zero
from app.core.crypto.errors import CryptoError
from app.core.crypto.keyring import MasterKeyring
from app.core.crypto.user_cipher import UserCipher

logger = logging.getLogger(__name__)

_SELF_TEST_USER_ID = 0
_status = {"master_key_loaded": False}


def run_self_test(keyring: MasterKeyring) -> None:
    """Raises CryptoError if the stack does not round-trip."""
    dek = generate_dek()
    probe = {"self_test": True}
    try:
        wrapped = wrap_dek(dek, keyring, _SELF_TEST_USER_ID)
        unwrapped = unwrap_dek(wrapped, keyring, _SELF_TEST_USER_ID)
        try:
            if unwrapped != dek:
                raise CryptoError("DEK did not survive a wrap/unwrap round trip")
            cipher = UserCipher(_SELF_TEST_USER_ID, unwrapped, keyring.current_version)
            sealed = cipher.seal("self_test", 1, probe)
            if cipher.open("self_test", 1, sealed, keyring.current_version) != probe:
                raise CryptoError("payload did not survive an encrypt/decrypt round trip")
        finally:
            zero(unwrapped)
    finally:
        zero(dek)
    _status["master_key_loaded"] = True
    logger.info("Encryption self-test passed (master key version %s)", keyring.current_version)


def master_key_loaded() -> bool:
    return _status["master_key_loaded"]
