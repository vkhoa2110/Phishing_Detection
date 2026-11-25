"""Password hashing and opaque session primitives for the local workspace."""
import hashlib
import hmac
import secrets

SCRYPT_N = 2 ** 17


def password_hash(password):
    salt = secrets.token_bytes(16)
    value = hashlib.scrypt(password.encode(), salt=salt, n=SCRYPT_N, r=8, p=1,
                           maxmem=256 * 1024 * 1024, dklen=32)
    return f"scrypt${SCRYPT_N}${salt.hex()}${value.hex()}"


def password_matches(password, encoded):
    try:
        algorithm, cost, salt, expected = encoded.split("$")
        cost = int(cost)
        if algorithm != "scrypt" or cost not in {2 ** i for i in range(10, 18)}:
            raise ValueError("Invalid password record")
        salt, expected = bytes.fromhex(salt), bytes.fromhex(expected)
        if len(salt) != 16 or len(expected) != 32:
            raise ValueError("Invalid password record")
    except (AttributeError, TypeError, ValueError):
        cost, salt, expected = SCRYPT_N, bytes(16), bytes(32)
    actual = hashlib.scrypt(password.encode(), salt=salt, n=cost, r=8, p=1,
                            maxmem=256 * 1024 * 1024, dklen=32)
    return hmac.compare_digest(actual, expected)


def new_token():
    return secrets.token_urlsafe(32)


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def csrf_token(token):
    return hmac.new(token.encode(), b"phishlens-csrf-v1", hashlib.sha256).hexdigest()
