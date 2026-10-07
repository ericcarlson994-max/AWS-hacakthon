import hashlib

import numpy as np
from datasketch import MinHash

from dms_core.chunking.tokens import normalize_text

MINHASH_SEED = 1
MINHASH_SCHEME = "affine32"


def shingles(text: str, k: int = 5) -> set[str]:
    words = normalize_text(text).split()
    if not words:
        return set()
    if len(words) < k:
        return {" ".join(words)}
    return {" ".join(words[index : index + k]) for index in range(len(words) - k + 1)}


def signature(text: str, num_perm: int = 128) -> MinHash:
    minhash = MinHash(num_perm=num_perm, seed=MINHASH_SEED, scheme=MINHASH_SCHEME)
    for shingle in sorted(shingles(text)):
        minhash.update(shingle.encode("utf-8"))
    return minhash


def serialize(minhash: MinHash) -> bytes:
    return np.asarray(minhash.hashvalues, dtype=np.uint64).tobytes()


def deserialize(data: bytes, num_perm: int = 128) -> MinHash:
    hashvalues = np.frombuffer(data, dtype=np.uint64).copy()
    return MinHash(num_perm=num_perm, seed=MINHASH_SEED, hashvalues=hashvalues, scheme=MINHASH_SCHEME)


def bands(minhash: MinHash, num_bands: int = 32) -> list[tuple[int, str]]:
    hashvalues = np.asarray(minhash.hashvalues, dtype=np.uint64)
    rows_per_band = len(hashvalues) // num_bands
    result: list[tuple[int, str]] = []
    for band_index in range(num_bands):
        rows = hashvalues[band_index * rows_per_band : (band_index + 1) * rows_per_band]
        bucket = hashlib.sha1(rows.tobytes()).hexdigest()[:16]
        result.append((band_index, bucket))
    return result


def jaccard(sig_a: bytes, sig_b: bytes) -> float:
    values_a = np.frombuffer(sig_a, dtype=np.uint64)
    values_b = np.frombuffer(sig_b, dtype=np.uint64)
    if len(values_a) != len(values_b) or len(values_a) == 0:
        return 0.0
    return float(np.count_nonzero(values_a == values_b)) / len(values_a)
