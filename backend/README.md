# GovDocs Search Backend

Document store for saving and retrieving government documents: upload, OCR-aware extraction, chunking, embeddings, enrichment (title, doctype, metadata, tags, supersedes), RAPTOR summaries, duplicate detection, versioning with merkle deltas, hybrid search, typo-tolerant suggest and cited answers over SSE, all filtered by the user's departments.

The demo corpus is synthetic, for the fictional agency **Jabatan Perkhidmatan Digital Negeri (JPDN)**. No real government content is used.

## Requirements

- Docker (OrbStack or Colima on macOS)
- [uv](https://docs.astral.sh/uv/) with Python 3.12

## Quickstart

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

| Target | What it does |
|---|---|
| `make up` | Starts Postgres 17 + pgvector (5432), OpenSearch 2.19 (9200) and SeaweedFS S3 (9000) |
| `make migrate` | Applies `db/migrations/001_init.sql` |
| `make api` | FastAPI on http://localhost:8000 (docs at `/docs`, schema at `/openapi.json`) |
| `make worker` | Background pipeline worker (extract, index, enrich, summarize, delta) |
| `make corpus` | Generates the synthetic corpus into `samples/corpus/` |
| `make seed` | Seeds departments, users and tags, uploads the corpus and the procurement v2 version, prints a summary and `delta_stats` |
| `make e2e` | Acceptance and integration tests against the running stack |
| `make eval` | Top-5 hit rate over `samples/eval_queries.jsonl` per category and overall |
| `make rebuild-index` | Drops and rebuilds the OpenSearch indexes from Postgres |
| `make test` | Offline unit tests |

Run `make api` and `make worker` in separate terminals. Set `API_BASE` to point the seed and eval scripts at a different API URL.

## Dev users

| username | departments |
|---|---|
| `alice` | finance (contributor), public (viewer) |
| `ben` | hr (contributor), public (viewer) |
| `chloe` | finance, hr, public (viewer) |
| `admin` | finance, hr, public (admin) |

Log in with `POST /auth/dev-login {"username": "alice"}` and send the returned token as `Authorization: Bearer <token>`.

## Ask: RAG and agent

`POST /ask` with `"mode": "agent"` runs a Strands Agents tool-using agent (`packages/dms_agent`). Its tools are search, document metadata, version diff and list. Every tool runs under the caller's departments. The default `"mode": "rag"` is single-shot retrieval plus an answer. See `docs/api-contract.md`.

## Secrets

`.env` is git-ignored. The secret-blocking pre-commit hook lives in `.githooks/`. Enable it once per clone:

```bash
git config core.hooksPath .githooks
```

It rejects staged `.env` files and anything that looks like an OpenRouter, Anthropic, OpenAI, AWS, GitHub or Slack key, or a private key.

## Notes

- **SeaweedFS replaces MinIO.** MinIO container images are no longer publicly available, so `docker-compose.yml` runs SeaweedFS with its S3 gateway on port 9000. Any access key works, clients must use path-style addressing, and the `documents` bucket is created on first use.
- **Fake AI mode.** When `OPENROUTER_API_KEY` is empty or `FAKE_AI=true`, the backend uses deterministic fakes instead of OpenRouter: hashed bag-of-words embeddings, template enrichment and summaries, a fake vision OCR and a streamed answer that cites `[n]`. Everything runs offline; search quality and OCR of image-only pages are lower than with real models.
- Postgres is the source of truth. OpenSearch can always be rebuilt with `make rebuild-index`.

## Documentation

- `docs/api-contract.md`: API contract for the frontend, with curl and SSE examples
- `docs/architecture.md`: architecture and local run steps
- `docs/demo-script.md`: 5-minute demo walkthrough
