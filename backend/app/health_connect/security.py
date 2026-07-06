import hashlib
import hmac
import secrets
import uuid


def new_link_code() -> str:
    alphabet = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
    return "".join(secrets.choice(alphabet) for _ in range(8))


def keyed_hash(value: str, pepper: str) -> str:
    return hmac.new(pepper.encode(), value.encode(), hashlib.sha256).hexdigest()


def new_device_token(device_id: uuid.UUID) -> str:
    return f"{device_id}.{secrets.token_urlsafe(32)}"


def token_device_id(token: str) -> uuid.UUID | None:
    public_id, separator, _secret = token.partition(".")
    if not separator:
        return None
    try:
        return uuid.UUID(public_id)
    except ValueError:
        return None


def hashes_match(left: str, right: str) -> bool:
    return hmac.compare_digest(left, right)
