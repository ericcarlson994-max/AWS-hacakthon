from __future__ import annotations

import json
import os
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import httpx

API_BASE = os.environ.get("API_BASE", "http://localhost:8000").rstrip("/")
EVAL_FILE = Path(__file__).resolve().parent.parent / "samples" / "eval_queries.jsonl"
TOP_K = 5
TARGET_HIT_RATE = 0.9


class EvalClient:
    def __init__(self, client: httpx.Client) -> None:
        self.client = client
        self.tokens: dict[str, str] = {}
        self.filenames_by_document: dict[str, set[str]] = {}

    def headers(self, username: str) -> dict[str, str]:
        if username not in self.tokens:
            response = self.client.post("/auth/dev-login", json={"username": username})
            response.raise_for_status()
            self.tokens[username] = response.json()["token"]
        return {"Authorization": f"Bearer {self.tokens[username]}"}

    def search(self, username: str, query: str) -> list[dict[str, Any]]:
        response = self.client.post(
            "/search",
            headers=self.headers(username),
            json={"query": query, "page": 1, "page_size": TOP_K},
        )
        response.raise_for_status()
        return response.json().get("results", [])[:TOP_K]

    def filenames(self, username: str, document_id: str) -> set[str]:
        if document_id in self.filenames_by_document:
            return self.filenames_by_document[document_id]
        names: set[str] = set()
        try:
            response = self.client.get(f"/documents/{document_id}/versions", headers=self.headers(username))
            if response.status_code == 200:
                names.update(version.get("original_filename", "") for version in response.json())
            detail = self.client.get(f"/documents/{document_id}", headers=self.headers(username))
            if detail.status_code == 200 and detail.json().get("original_filename"):
                names.add(detail.json()["original_filename"])
        except httpx.HTTPError:
            pass
        self.filenames_by_document[document_id] = names
        return names


def title_matches(expected_file: str, title: str) -> bool:
    stem = Path(expected_file).stem.lower().replace("_", " ")
    return bool(title) and title.lower() == stem


def load_queries() -> list[dict[str, Any]]:
    with EVAL_FILE.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def main() -> int:
    queries = load_queries()
    per_category: dict[str, list[bool]] = defaultdict(list)
    rows: list[tuple[str, str, str, str, str]] = []
    with httpx.Client(base_url=API_BASE, timeout=60.0) as client:
        evaluator = EvalClient(client)
        for item in queries:
            query = item["query"]
            expected_file = item.get("expected_file") or item.get("expected_document_file", "")
            username = item["user"]
            category = item.get("category", "uncategorized")
            rank = "-"
            try:
                results = evaluator.search(username, query)
                for position, result in enumerate(results, start=1):
                    document_id = str(result.get("document_id"))
                    if title_matches(expected_file, result.get("title", "")) or expected_file in evaluator.filenames(username, document_id):
                        rank = str(position)
                        break
                top_title = results[0].get("title", "") if results else "(no results)"
            except httpx.HTTPError as error:
                top_title = f"ERROR {error}"[:60]
            hit = rank != "-"
            per_category[category].append(hit)
            rows.append(("HIT " if hit else "MISS", rank, username, query, top_title))

    query_width = max(len(row[3]) for row in rows)
    print(f"{'result':6}{'rank':6}{'user':8}{'query'.ljust(query_width)}  top result")
    for result_label, rank, username, query, top_title in rows:
        print(f"{result_label:6}{rank:6}{username:8}{query.ljust(query_width)}  {top_title}")

    print()
    print(f"{'category':14}{'hits':>6}{'total':>7}{'rate':>8}")
    total_hits = 0
    total_queries = 0
    for category in sorted(per_category):
        outcomes = per_category[category]
        hits = sum(outcomes)
        total_hits += hits
        total_queries += len(outcomes)
        print(f"{category:14}{hits:>6}{len(outcomes):>7}{hits / len(outcomes):>8.0%}")
    overall = total_hits / total_queries if total_queries else 0.0
    print(f"{'overall':14}{total_hits:>6}{total_queries:>7}{overall:>8.0%}")
    print(f"Top-{TOP_K} hit rate target {TARGET_HIT_RATE:.0%}: {'PASS' if overall >= TARGET_HIT_RATE else 'FAIL'}")
    return 0 if overall >= TARGET_HIT_RATE else 1


if __name__ == "__main__":
    sys.exit(main())
