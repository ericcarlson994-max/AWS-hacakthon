from __future__ import annotations

import sys
import time


def main() -> int:
    from dms_adapters.container import build_container
    from dms_workers.indexing import reindex_document

    container = build_container()
    started = time.monotonic()
    container.index.drop_indexes()
    container.index.ensure_indexes()
    document_ids = container.repo.list_all_document_ids()
    failures = 0
    for position, document_id in enumerate(document_ids, start=1):
        try:
            reindex_document(container, document_id)
            print(f"[{position}/{len(document_ids)}] reindexed {document_id}")
        except Exception as error:
            failures += 1
            print(f"[{position}/{len(document_ids)}] FAILED {document_id}: {error}")
    container.index.refresh()
    print(f"Rebuilt indexes for {len(document_ids) - failures}/{len(document_ids)} documents in {time.monotonic() - started:.1f}s")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
