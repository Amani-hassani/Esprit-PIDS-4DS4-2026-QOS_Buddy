from __future__ import annotations

import os
import secrets
import time


_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def _encode(num: int, length: int) -> str:
    chars = []
    for _ in range(length):
        chars.append(_ALPHABET[num & 0x1F])
        num >>= 5
    return "".join(reversed(chars))


def ulid() -> str:
    """Crockford-ULID: 10 chars ms timestamp + 16 chars randomness."""
    ts = int(time.time() * 1000)
    return _encode(ts, 10) + _encode(int.from_bytes(os.urandom(10), "big"), 16)


def short_id(prefix: str) -> str:
    """Prefixed short id for human-readable handles."""
    return f"{prefix}_{secrets.token_hex(4)}"
