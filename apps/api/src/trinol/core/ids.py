from __future__ import annotations

import os
import time
import uuid

_12_BIT_MASK = 0x0FFF
_62_BIT_MASK = 0x3FFFFFFFFFFFFFFF
_48_BIT_MASK = 0xFFFFFFFFFFFF


def uuid7() -> uuid.UUID:
    """RFC 9562 UUIDv7: millisecond timestamp + random bits, time-ordered.

    Used for every primary key (DATABASE.md §1) so index locality is good and
    ids stay unguessable, unlike a plain sequence.
    """
    unix_ts_ms = time.time_ns() // 1_000_000
    rand_a = int.from_bytes(os.urandom(2), "big") & _12_BIT_MASK
    rand_b = int.from_bytes(os.urandom(8), "big") & _62_BIT_MASK

    uuid_int = (
        ((unix_ts_ms & _48_BIT_MASK) << 80) | (0x7 << 76) | (rand_a << 64) | (0b10 << 62) | rand_b
    )
    return uuid.UUID(int=uuid_int)
