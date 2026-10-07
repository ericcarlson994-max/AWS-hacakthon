def diff_manifests(old_ids: list[str], new_ids: list[str]) -> tuple[list[str], list[str], list[str]]:
    old_set = set(old_ids)
    new_set = set(new_ids)
    added = [chunk_id for chunk_id in new_ids if chunk_id not in old_set]
    reused = [chunk_id for chunk_id in new_ids if chunk_id in old_set]
    removed = [chunk_id for chunk_id in old_ids if chunk_id not in new_set]
    return added, removed, reused
