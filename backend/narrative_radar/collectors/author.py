import hashlib
import hmac


class AuthorHasher:
    """작성자 식별자를 저장하지 않고 HMAC만 남긴다 (DATA_POLICY 7).

    같은 salt 안에서는 같은 작성자를 알아볼 수 있어 독립 근거를 셀 수 있지만,
    salt 없이는 원래 식별자를 되돌릴 수 없다.
    """

    MIN_SALT_BYTES = 16

    def __init__(self, salt: str) -> None:
        raw = salt.encode("utf-8")
        if len(raw) < self.MIN_SALT_BYTES:
            raise ValueError(
                "author hash salt must be at least 16 bytes; set NR_AUTHOR_HASH_SALT "
                '(python -c "import secrets; print(secrets.token_hex(32))")'
            )
        self._salt = raw

    def hash(self, source: str, author_key: str) -> str | None:
        key = author_key.strip()
        if not key:
            return None
        msg = f"{source}\x00{key}".encode()
        return hmac.new(self._salt, msg, hashlib.sha256).hexdigest()
