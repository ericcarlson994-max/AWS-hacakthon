def rrf(rank_lists: list[list[str]], k: int = 60) -> dict[str, float]:
    scores: dict[str, float] = {}
    for ranking in rank_lists:
        seen: set[str] = set()
        for rank, item_id in enumerate(ranking, start=1):
            if item_id in seen:
                continue
            seen.add(item_id)
            scores[item_id] = scores.get(item_id, 0.0) + 1.0 / (k + rank)
    return dict(sorted(scores.items(), key=lambda pair: pair[1], reverse=True))
