import math
from collections.abc import Sequence


def _norm(vector: Sequence[float]) -> float:
    return math.sqrt(sum(value * value for value in vector))


def mean_vector(vectors: Sequence[Sequence[float]]) -> list[float]:
    if not vectors:
        return []
    dimension = len(vectors[0])
    totals = [0.0] * dimension
    for vector in vectors:
        for index, value in enumerate(vector):
            totals[index] += value
    mean = [total / len(vectors) for total in totals]
    length = _norm(mean)
    if length == 0:
        return mean
    return [value / length for value in mean]


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    norm_a = _norm(a)
    norm_b = _norm(b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return sum(x * y for x, y in zip(a, b)) / (norm_a * norm_b)


def is_semantic_duplicate(a: Sequence[float], b: Sequence[float], threshold: float = 0.95) -> bool:
    return cosine(a, b) >= threshold
