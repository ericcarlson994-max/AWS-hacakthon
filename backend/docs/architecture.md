# GovDocs Search Architecture

GovDocs Search is a document store focused on saving and retrieving government documents for the fictional agency Jabatan Perkhidmatan Digital Negeri (JPDN). Every upload is stored by SHA-256, extracted (with per-page OCR routing), chunked, embedded, enriched, summarized and made searchable, always filtered by the user's departments.

## Components

```
frontend (:5173) ──HTTP/JSON + SSE──▶ dms_api (FastAPI, :8000)
                                         │ enqueue jobs / query / read-write
          ┌──────────────────────────────┼──────────────────────────┐
          ▼                              ▼                          ▼
  Postgres 17 + pgvector         OpenSearch 2.19            SeaweedFS (S3 API, :9000)
  source of truth + jobs         dms_chunks, dms_titles     bucket "documents", blobs/{sha256}
          ▲                              ▲                          ▲
          └──────── dms_workers (python -m dms_workers.run) ────────┘
                    extract → index → enrich → summarize → delta
                                         │
                                         ▼
                     OpenRouter (embeddings, chat, vision OCR) or fake AI
```

| Package | Role |
|---|---|
| `packages/dms_core` | Pure domain logic: models, ports (Protocols), extraction, chunking, merkle diff, dedup, enrichment, RAPTOR, search and answer services, access groups |
| `packages/dms_adapters` | Implementations of the ports: Postgres repo and job queue, OpenSearch index, S3 blob store, OpenRouter clients, fakes for offline tests; `container.build_container()` wires them from settings |
| `services/api` | FastAPI app (`dms_api.main:app`) exposing the contract in `docs/api-contract.md` |
| `services/workers` | Job runner polling the `jobs` table with `FOR UPDATE SKIP LOCKED` |
| `scripts` | Corpus generation, demo seeding, search evaluation, index rebuild |

## Key principles

1. Postgres is the source of truth. OpenSearch can be rebuilt from Postgres and the blob store at any time (`make rebuild-index`), and embeddings are stored in Postgres so a rebuild needs no re-embedding.
2. Only pay for what changed. Chunk IDs are content-derived (`{doc_id}:{sha1(normalized_text)[:16]}`), so a new version re-embeds only added chunks; the result is recorded in the version's `delta_stats`.
3. One retrieval path. The UI and `/ask` both call `search_service.search` with the requesting user's groups, so the assistant never sees anything the user cannot search.
4. Access control by group. A document's `allowed_groups` is its department, plus `public` for agency-wide documents. Only group IDs are written to the index.

## Pipeline

| Stage | Output | Status after |
|---|---|---|
| upload (API) | blob in S3, `documents` + `versions` rows, exact-duplicate check, `extract` job | `UPLOADED` |
| extract | canonical blocks; PDF pages with < 50 chars of text are rendered at 200 dpi and OCR'd; images always OCR'd | `EXTRACTED` |
| index | heading-aware chunks (350–500 tokens, 12 % overlap), embeddings in batches of 32, OpenSearch upsert | `INDEXED` |
| enrich | title cascade, doctype, metadata, supersedes link, tags, MinHash near-duplicate and semantic check | `ENRICHED` |
| summarize | RAPTOR tree (single summary for ≤ 8 chunks), root summary | `READY` |
| delta | merkle diff against the previous version, re-embed only new chunks | `READY` |

Failed jobs retry with exponential backoff up to 3 attempts, then the document is `FAILED` with `status_detail`.

## Search

Hybrid retrieval: kNN (k = 50) and BM25 `multi_match` over `title^3, text, text.cjk, heading_path^2` run in parallel with the same access filter, fused by reciprocal rank fusion (k = 60), collapsed per document, superseded documents down-ranked (× 0.7), hydrated from Postgres, with facets on doctype, tags and department. `/suggest` uses the `dms_titles` index with tiered boosts (exact, phrase prefix, edge n-grams, trigrams, fuzzy).

## Running locally

```bash
cp .env.example .env
make up
make migrate
make api
make worker
make corpus
make seed
make e2e
make eval
```

`make api` and `make worker` each block, so run them in separate terminals. Without `OPENROUTER_API_KEY` (or with `FAKE_AI=true`) the adapters fall back to deterministic fake AI: hashed bag-of-words embeddings, template enrichment and summaries, and a fake OCR.

## Swapping to AWS later

Implement `dms_adapters/aws/*` for S3, Bedrock and Textract and wire them in the container. `dms_core` does not change.
