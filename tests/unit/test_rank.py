from app.core.rank import decode_rank, initial_rank, next_rank, rank_between


def test_rank_between_is_strictly_between():
    first = initial_rank()
    second = next_rank(first)
    middle = rank_between(first, second)
    assert middle is not None
    assert decode_rank(first) < decode_rank(middle) < decode_rank(second)


def test_next_rank_increases():
    first = initial_rank()
    assert decode_rank(next_rank(first)) > decode_rank(first)
