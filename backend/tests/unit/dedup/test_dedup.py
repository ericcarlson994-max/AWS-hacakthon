import hashlib
import random

from dms_core.dedup.exact import sha256_hex
from dms_core.dedup.minhash_lsh import bands, deserialize, jaccard, serialize, shingles, signature
from dms_core.dedup.semantic import cosine, is_semantic_duplicate, mean_vector


def random_text(seed: int, length: int = 400) -> str:
    rng = random.Random(seed)
    vocabulary = [f"word{i}" for i in range(300)]
    return " ".join(rng.choice(vocabulary) for _ in range(length))


def test_sha256_hex():
    assert sha256_hex(b"abc") == hashlib.sha256(b"abc").hexdigest()


def test_shingles():
    assert shingles("A b c d e f") == {"a b c d e", "b c d e f"}
    assert shingles("short text") == {"short text"}
    assert shingles("   ") == set()


def test_serialize_roundtrip():
    minhash = signature(random_text(1))
    data = serialize(minhash)
    assert len(data) == 128 * 8
    restored = deserialize(data)
    assert serialize(restored) == data
    assert bands(restored) == bands(minhash)


def test_near_duplicates_share_band_and_high_jaccard():
    original = random_text(2)
    words = original.split()
    words[200] = "changedword"
    edited = " ".join(words)
    sig_a = signature(original)
    sig_b = signature(edited)
    assert len(bands(sig_a)) == 32
    assert set(bands(sig_a)) & set(bands(sig_b))
    assert jaccard(serialize(sig_a), serialize(sig_b)) >= 0.8


def test_unrelated_texts_share_no_band():
    sig_a = signature(random_text(3))
    sig_b = signature(" ".join(f"other{i}" for i in range(400)))
    assert not set(bands(sig_a)) & set(bands(sig_b))
    assert jaccard(serialize(sig_a), serialize(sig_b)) < 0.2


def test_semantic_helpers():
    mean = mean_vector([[1.0, 0.0], [0.0, 1.0]])
    assert abs(sum(v * v for v in mean) - 1.0) < 1e-9
    assert abs(cosine([1.0, 0.0], [1.0, 0.0]) - 1.0) < 1e-9
    assert abs(cosine([1.0, 0.0], [0.0, 1.0])) < 1e-9
    assert cosine([0.0, 0.0], [1.0, 0.0]) == 0.0
    assert is_semantic_duplicate([1.0, 0.01], [1.0, 0.0])
    assert not is_semantic_duplicate([1.0, 1.0], [1.0, 0.0])
    assert mean_vector([]) == []
