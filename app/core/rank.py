ALPHABET = "0123456789abcdefghijklmnopqrstuvwxyz"
WIDTH = 12
MAX_VALUE = 36 ** WIDTH - 1
STEP = 36 ** 5


def encode_rank(value: int) -> str:
    if value < 0 or value > MAX_VALUE:
        raise ValueError("rank fuera de rango")
    chars = []
    for _ in range(WIDTH):
        value, rem = divmod(value, 36)
        chars.append(ALPHABET[rem])
    return "".join(reversed(chars))


def decode_rank(rank: str) -> int:
    value = 0
    for ch in rank:
        value = value * 36 + ALPHABET.index(ch)
    return value


def initial_rank() -> str:
    return encode_rank(STEP)


def next_rank(current: str | None) -> str:
    if not current:
        return initial_rank()
    return encode_rank(min(decode_rank(current) + STEP, MAX_VALUE))


def rank_between(before: str | None, after: str | None) -> str | None:
    low = decode_rank(before) if before else 0
    high = decode_rank(after) if after else MAX_VALUE
    if high - low <= 1:
        return None
    return encode_rank((low + high) // 2)
