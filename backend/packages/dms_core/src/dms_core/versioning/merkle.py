import hashlib


def _sha256(data: bytes) -> bytes:
    return hashlib.sha256(data).digest()


def merkle_root(leaf_ids: list[str]) -> str:
    if not leaf_ids:
        return hashlib.sha256(b"").hexdigest()
    level = [_sha256(leaf_id.encode("utf-8")) for leaf_id in leaf_ids]
    while len(level) > 1:
        parents: list[bytes] = []
        for index in range(0, len(level) - 1, 2):
            parents.append(_sha256(level[index] + level[index + 1]))
        if len(level) % 2 == 1:
            parents.append(level[-1])
        level = parents
    return level[0].hex()
