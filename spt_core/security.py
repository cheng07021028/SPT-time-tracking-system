from __future__ import annotations

import base64
import hashlib
import hmac
import os

_ALGORITHM = "pbkdf2_sha256"
_ITERATIONS = 260_000
_LEGACY_PERMISSION_ITERATIONS = 120_000


def hash_password(password: str) -> str:
    if not password:
        raise ValueError("password must not be empty")
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _ITERATIONS)
    return "$".join([
        _ALGORITHM,
        str(_ITERATIONS),
        base64.urlsafe_b64encode(salt).decode("ascii"),
        base64.urlsafe_b64encode(digest).decode("ascii"),
    ])


def verify_password(password: str, encoded: str) -> bool:
    """Verify current hashes and legacy SPT permission hashes.

    Supported formats:
    - current: pbkdf2_sha256$iterations$salt_urlsafe_b64$digest_urlsafe_b64
    - legacy security: pbkdf2_sha256$iterations$salt_base64$digest_base64
    - legacy permission: pbkdf2_sha256$salt_hex_text$digest_hex, 120000 iterations
    """
    if not password or not encoded:
        return False
    try:
        parts = str(encoded).split("$")
        if len(parts) == 4:
            algorithm, iterations_text, salt_text, digest_text = parts
            if algorithm != _ALGORITHM:
                return False
            iterations = int(iterations_text)
            try:
                salt = base64.urlsafe_b64decode(salt_text.encode("ascii"))
                expected = base64.urlsafe_b64decode(digest_text.encode("ascii"))
            except Exception:
                salt = base64.b64decode(salt_text.encode("ascii"))
                expected = base64.b64decode(digest_text.encode("ascii"))
            actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
            return hmac.compare_digest(actual, expected)

        if len(parts) == 3:
            algorithm, salt_text, digest_hex = parts
            if algorithm != _ALGORITHM:
                return False
            actual_hex = hashlib.pbkdf2_hmac(
                "sha256",
                password.encode("utf-8"),
                salt_text.encode("utf-8"),
                _LEGACY_PERMISSION_ITERATIONS,
            ).hex()
            return hmac.compare_digest(actual_hex, digest_hex)
    except Exception:
        return False
    return False
