"""
SEC-12. Unlock the lock screen with a passkey - Face ID, a fingerprint,
Windows Hello - instead of typing the PIN.

WHAT A PASSKEY IS HERE: the PIN's equal, and nothing more (ARCHITECTURE.md
section 6). It never derives, wraps or unwraps a key. A verified passkey
makes the server unwrap the DEK again with the master key through the same
`_reunlock` the PIN uses, so there is still exactly ONE way to a DEK. It only
unlocks a session that is already signed in (SEC-27); signing in still takes
the password, and the PIN stays as the fallback on every device.

WHY IT IS HAND-ROLLED (the user's choice, 2026-09-28): the server venv is
shared with QUOT, and a WebAuthn library brings cbor2, pyOpenSSL and asn1crypto
into it. What this app needs is small, and `cryptography` already does the
signature checks:

    registration  attestation "none" - the authenticator's maker is not
                  checked, only that this browser, on this origin, produced
                  this public key after verifying the user. So the CBOR in
                  attestationObject is read for authData and nothing else.
    assertion     the signature over authenticatorData || SHA-256(clientDataJSON),
                  by the public key stored at registration: ES256 or RS256.

Both check the challenge (single use, 2 minutes, kept in process memory -
one uvicorn worker, invariant 7), the type, the origin (APP_PUBLIC_URL) and
the relying party (its host), and that the user was VERIFIED - a fingerprint
or face, not merely a tap. A sign counter that goes backwards is refused: that
is what a cloned authenticator looks like.

Stored on users.passkeys as JSON: each credential's id, its PUBLIC key (SPKI,
base64), the algorithm, the counter, a device label and two dates. Nothing
there is secret - a public key opens nothing.
"""

import base64
import hashlib
import hmac
import json
import secrets
import struct
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa

from app.core.config import settings
from app.core.exceptions import BusinessRuleException, InvalidCredentialsException, ValidationException
from app.db.models import User
from app.db.types import utcnow

ES256 = -7
RS256 = -257
ALGORITHMS = (ES256, RS256)
MAX_PASSKEYS = 5
CHALLENGE_SECONDS = 120
TIMEOUT_MS = 60_000
RP_NAME = "Budget"

FLAG_UP = 0x01  # the user was present
FLAG_UV = 0x04  # the user was verified - biometric or device PIN
FLAG_AT = 0x40  # attested credential data follows


@dataclass(frozen=True)
class Passkey:
    id: str  # the credential id, base64url
    label: Optional[str]
    created: datetime
    last_used: Optional[datetime]


# ----------------------------------------------------------- the challenges


class _Challenges:
    """One outstanding challenge per session and purpose, used once."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._items: Dict[Tuple[str, str], Tuple[bytes, float]] = {}

    def issue(self, session_id: str, purpose: str) -> bytes:
        challenge = secrets.token_bytes(32)
        with self._lock:
            now = time.monotonic()
            self._items = {k: v for k, v in self._items.items() if v[1] > now}
            self._items[(session_id, purpose)] = (challenge, now + CHALLENGE_SECONDS)
        return challenge

    def take(self, session_id: str, purpose: str) -> Optional[bytes]:
        with self._lock:
            item = self._items.pop((session_id, purpose), None)
        if item is None or item[1] <= time.monotonic():
            return None
        return item[0]


_challenges = _Challenges()


# ---------------------------------------------------------------- the API


def enabled() -> bool:
    return bool(settings.BIOMETRIC_WEBAUTHN_ENABLED)


def listed(user: User) -> List[Passkey]:
    return [
        Passkey(
            id=item["id"], label=item.get("label"),
            created=datetime.fromisoformat(item["created"]),
            last_used=datetime.fromisoformat(item["last_used"]) if item.get("last_used") else None,
        )
        for item in _stored(user)
    ]


def has_passkeys(user: User) -> bool:
    return enabled() and bool(_stored(user))


def registration_options(user: User, session_id: str) -> Dict[str, Any]:
    """What navigator.credentials.create() needs - binary fields as base64url."""
    _require_enabled()
    if len(_stored(user)) >= MAX_PASSKEYS:
        raise BusinessRuleException(f"At most {MAX_PASSKEYS} passkeys - remove one first")
    challenge = _challenges.issue(session_id, "register")
    return {
        "challenge": _b64(challenge),
        "rp": {"id": _rp_id(), "name": RP_NAME},
        # An opaque handle - never the email, which the authenticator would show and keep.
        "user": {"id": _b64(_user_handle(user)), "name": RP_NAME, "displayName": RP_NAME},
        "pubKeyCredParams": [{"type": "public-key", "alg": alg} for alg in ALGORITHMS],
        "authenticatorSelection": {
            "authenticatorAttachment": "platform",  # this phone's own Face ID or fingerprint
            "userVerification": "required",
            "residentKey": "discouraged",
        },
        "attestation": "none",
        "timeout": TIMEOUT_MS,
        "excludeCredentials": [{"type": "public-key", "id": item["id"]} for item in _stored(user)],
    }


def register(user: User, session_id: str, *, client_data_json: str, attestation_object: str,
             label: Optional[str]) -> Passkey:
    """Check a new credential and add it to the user. The caller commits (and audits)."""
    _require_enabled()
    challenge = _challenges.take(session_id, "register")
    if challenge is None:
        raise ValidationException("That took too long - try again")
    _check_client_data(_unb64(client_data_json), "webauthn.create", challenge)

    attestation = _cbor(_unb64(attestation_object))
    if not isinstance(attestation, dict) or not isinstance(attestation.get("authData"), bytes):
        raise ValidationException("The passkey could not be read")
    auth = _auth_data(attestation["authData"], need_credential=True)
    credential_id, (algorithm, public_key) = auth["credential_id"], auth["public_key"]

    stored = _stored(user)
    key_id = _b64(credential_id)
    if any(item["id"] == key_id for item in stored):
        raise BusinessRuleException("This device already unlocks with a passkey")
    now = utcnow().isoformat()
    stored.append({
        "id": key_id,
        "alg": algorithm,
        "key": base64.b64encode(public_key.public_bytes(
            serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)).decode("ascii"),
        "count": auth["count"],
        "label": (label or "").strip()[:60] or None,
        "created": now,
        "last_used": None,
    })
    _save(user, stored)
    return listed(user)[-1]


def unlock_options(user: User, session_id: str) -> Dict[str, Any]:
    """What navigator.credentials.get() needs on the lock screen."""
    _require_enabled()
    stored = _stored(user)
    if not stored:
        raise BusinessRuleException("No passkey is set - unlock with your PIN")
    challenge = _challenges.issue(session_id, "unlock")
    return {
        "challenge": _b64(challenge),
        "rpId": _rp_id(),
        "allowCredentials": [{"type": "public-key", "id": item["id"]} for item in stored],
        "userVerification": "required",
        "timeout": TIMEOUT_MS,
    }


def verify(user: User, session_id: str, *, credential_id: str, client_data_json: str,
           authenticator_data: str, signature: str) -> None:
    """
    Raise unless this is a fresh, verified signature by one of the user's
    passkeys. Updates its counter and last use; the caller commits. Deciding
    is all it does - auth_service unlocks.
    """
    _require_enabled()
    challenge = _challenges.take(session_id, "unlock")
    if challenge is None:
        raise InvalidCredentialsException("That took too long - try again")
    stored = _stored(user)
    item = next((k for k in stored if hmac.compare_digest(k["id"], credential_id or "")), None)
    if item is None:
        raise InvalidCredentialsException("This passkey does not unlock this account")

    client_data = _unb64(client_data_json)
    _check_client_data(client_data, "webauthn.get", challenge)
    raw_auth = _unb64(authenticator_data)
    auth = _auth_data(raw_auth, need_credential=False)

    public_key = serialization.load_der_public_key(base64.b64decode(item["key"]))
    signed = raw_auth + hashlib.sha256(client_data).digest()
    try:
        if item["alg"] == ES256 and isinstance(public_key, ec.EllipticCurvePublicKey):
            public_key.verify(_unb64(signature), signed, ec.ECDSA(hashes.SHA256()))
        elif item["alg"] == RS256 and isinstance(public_key, rsa.RSAPublicKey):
            public_key.verify(_unb64(signature), signed, padding.PKCS1v15(), hashes.SHA256())
        else:
            raise InvalidCredentialsException("This passkey does not unlock this account")
    except InvalidSignature:
        raise InvalidCredentialsException("The passkey did not match") from None

    count, before = auth["count"], int(item.get("count") or 0)
    if (count or before) and count <= before:
        raise InvalidCredentialsException("This passkey looks copied - unlock with your PIN")
    item["count"] = count
    item["last_used"] = utcnow().isoformat()
    _save(user, stored)


def remove(user: User, passkey_id: str) -> None:
    stored = _stored(user)
    kept = [item for item in stored if item["id"] != passkey_id]
    if len(kept) == len(stored):
        raise BusinessRuleException("That passkey was already removed")
    _save(user, kept)


# ---------------------------------------------------------------- checking


def _check_client_data(raw: bytes, kind: str, challenge: bytes) -> None:
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise ValidationException("The passkey could not be read") from None
    if not isinstance(data, dict) or data.get("type") != kind:
        raise InvalidCredentialsException("The passkey answered the wrong question")
    if not hmac.compare_digest(str(data.get("challenge") or ""), _b64(challenge)):
        raise InvalidCredentialsException("That passkey answer is not for this request")
    if data.get("origin") != settings.APP_PUBLIC_URL or data.get("crossOrigin"):
        raise InvalidCredentialsException("That passkey answer came from another site")


def _auth_data(raw: bytes, *, need_credential: bool) -> Dict[str, Any]:
    if len(raw) < 37:
        raise ValidationException("The passkey could not be read")
    if not hmac.compare_digest(raw[:32], hashlib.sha256(_rp_id().encode("ascii")).digest()):
        raise InvalidCredentialsException("That passkey belongs to another site")
    flags = raw[32]
    if not flags & FLAG_UP or not flags & FLAG_UV:
        raise InvalidCredentialsException("Your fingerprint or face was not checked")
    out: Dict[str, Any] = {"count": struct.unpack(">I", raw[33:37])[0]}
    if not need_credential:
        return out
    if not flags & FLAG_AT or len(raw) < 55:
        raise ValidationException("The passkey could not be read")
    length = struct.unpack(">H", raw[53:55])[0]
    credential_id = raw[55:55 + length]
    if len(credential_id) != length or not 16 <= length <= 1023:
        raise ValidationException("The passkey could not be read")
    cose, _ = _cbor_at(raw, 55 + length)
    out["credential_id"] = credential_id
    out["public_key"] = _cose_key(cose)
    return out


def _cose_key(cose: Any):
    """A COSE_Key (RFC 8152) as a cryptography public key: EC2 P-256 or RSA."""
    if not isinstance(cose, dict):
        raise ValidationException("The passkey could not be read")
    algorithm = cose.get(3)
    try:
        if cose.get(1) == 2 and algorithm == ES256 and cose.get(-1) == 1:
            x, y = cose[-2], cose[-3]
            if not (isinstance(x, bytes) and isinstance(y, bytes) and len(x) == len(y) == 32):
                raise ValueError
            return ES256, ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), b"\x04" + x + y)
        if cose.get(1) == 3 and algorithm == RS256:
            n, e = int.from_bytes(cose[-1], "big"), int.from_bytes(cose[-2], "big")
            if n.bit_length() < 2048:
                raise ValueError
            return RS256, rsa.RSAPublicNumbers(e, n).public_key()
    except (KeyError, TypeError, ValueError):
        raise ValidationException("The passkey could not be read") from None
    raise ValidationException("This passkey uses a kind of key the app does not accept")


# ------------------------------------------------------------ a small CBOR


def _cbor(data: bytes) -> Any:
    value, end = _cbor_at(data, 0)
    if end != len(data):
        raise ValidationException("The passkey could not be read")
    return value


def _cbor_at(data: bytes, pos: int, depth: int = 0) -> Tuple[Any, int]:
    """
    Just enough RFC 8949 for WebAuthn: integers, byte and text strings, arrays,
    maps and the simple values. Definite lengths only, as WebAuthn requires.
    """
    if depth > 8 or pos >= len(data):
        raise ValidationException("The passkey could not be read")
    head = data[pos]
    major, info = head >> 5, head & 0x1F
    pos += 1
    if info < 24:
        arg = info
    elif info in (24, 25, 26, 27):
        size = 1 << (info - 24)
        if pos + size > len(data):
            raise ValidationException("The passkey could not be read")
        arg = int.from_bytes(data[pos:pos + size], "big")
        pos += size
    else:
        raise ValidationException("The passkey could not be read")

    if major == 0:
        return arg, pos
    if major == 1:
        return -1 - arg, pos
    if major in (2, 3):
        if pos + arg > len(data):
            raise ValidationException("The passkey could not be read")
        chunk = data[pos:pos + arg]
        pos += arg
        if major == 2:
            return chunk, pos
        try:
            return chunk.decode("utf-8"), pos
        except UnicodeDecodeError:
            raise ValidationException("The passkey could not be read") from None
    if major == 4:
        items = []
        for _ in range(arg):
            item, pos = _cbor_at(data, pos, depth + 1)
            items.append(item)
        return items, pos
    if major == 5:
        mapping: Dict[Any, Any] = {}
        for _ in range(arg):
            key, pos = _cbor_at(data, pos, depth + 1)
            if isinstance(key, (list, dict)):
                raise ValidationException("The passkey could not be read")
            mapping[key], pos = _cbor_at(data, pos, depth + 1)
        return mapping, pos
    if major == 7 and info in (20, 21, 22):
        return {20: False, 21: True, 22: None}[info], pos
    raise ValidationException("The passkey could not be read")


# --------------------------------------------------------------- internals


def _require_enabled() -> None:
    if not enabled():
        raise BusinessRuleException("Passkeys are turned off on this server")


def _rp_id() -> str:
    return urlparse(settings.APP_PUBLIC_URL).hostname or "localhost"


def _user_handle(user: User) -> bytes:
    return hashlib.sha256(f"zbdgt-user:{user.id}".encode("ascii")).digest()[:16]


def _stored(user: User) -> List[Dict[str, Any]]:
    if not user.passkeys:
        return []
    try:
        items = json.loads(user.passkeys)
    except ValueError:
        return []
    return [dict(i) for i in items if isinstance(i, dict) and i.get("id") and i.get("key")] if isinstance(items, list) else []


def _save(user: User, items: List[Dict[str, Any]]) -> None:
    user.passkeys = json.dumps(items, separators=(",", ":")) if items else None


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _unb64(text: Optional[str]) -> bytes:
    try:
        text = str(text or "")
        return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
    except (ValueError, TypeError):
        raise ValidationException("The passkey could not be read") from None
