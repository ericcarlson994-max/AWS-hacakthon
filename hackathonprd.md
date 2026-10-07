# GovDocs Search — Hackathon PRD (Backend)

> **Status:** Build-ready · **Date:** 2026-10-07 · **Owner:** Marcus Yeo
> **Scope of this doc:** backend, built and run locally. The frontend is a separate build (`../frontend`) that connects through the API contract in §7.
> **Parent PRD (reference only, outside the repos):** `~/aws-hackathon/Enterprise_DMS_Prototype_PRD_whitepaper.pdf`

---

## 1. Problem statement

> Government agencies manage thousands of documents — policies, SOPs, circulars, guidelines, reports, and meeting minutes. Finding the right information is often time-consuming, leading to slower decision-making and reduced productivity. We need a solution that transforms organizational knowledge into an intelligent, searchable resource, helping employees and stakeholders find information faster and make better decisions.

## 2. What we're building

A document store focused on **saving and retrieving**. Every uploaded file (PDF, DOCX, XLSX, PNG/JPEG, scanned or digital) ends up:

- **Saved:** the original file stored by its SHA-256 hash, its text extracted (OCR where needed), and its versions tracked.
- **Understood:** an AI-suggested title, a document type (policy / SOP / circular / guideline / report / minutes), extracted metadata (agency, reference no., effective date, *supersedes*), tags, and a summary.
- **Findable:** instant title suggestions as you type, hybrid semantic + keyword search with facets, and an **Ask** endpoint that answers questions with citations. All of it is filtered by the user's departments.

### In scope
| # | Capability | Parent-PRD ref |
|---|---|---|
| 1 | Upload → extract (per-page OCR routing) → chunk → embed → index | §5.1, §5.3 |
| 2 | Title cascade, document type, metadata, tags | §5.2, §5.5 |
| 3 | RAPTOR-style summaries (simplified) | §5.7 |
| 4 | Three-tier duplicate detection (SHA-256 → MinHash → semantic) | §5.6 |
| 5 | Versioning with merkle chunk diff, re-embedding only what changed | §6 |
| 6 | `/suggest` (typo-tolerant titles) + `/search` (hybrid) + facets | §5.8 |
| 7 | `/ask`: answers grounded in documents, with citations, retrieved only through `/search` | §5.8 |
| 8 | Department-based access filter applied in search, listing and opening a document | §5.4 (slim) |

### Out of scope (deliberately)
Sanitization/CDR, workflow engine, audit trail, eSign, the five-role admin console, and AWS deployment. The code is structured so AWS can replace the local services later (see §11).

### Success criteria for the demo
- A user uploads a scanned circular and it is **READY** (searchable, summarized) in under 60 s.
- Typing `"quartely bud"` suggests **"Quarterly Budget …"**.
- `eval_search.py`: for **≥ 90 %** of eval queries, the target document is in the **top 5** results (hybrid beats dense-only).
- Ask: "What is the current policy on remote work?" returns an answer citing the **latest** circular and noting which one it supersedes.
- A Finance user gets **zero** hits from HR-only documents, in search, suggest and ask alike.
- Editing one section of a document re-embeds only that section (shown in the version's `delta_stats`).

---

## 3. Local architecture

```
                ┌───────────── frontend (separate build, :5173) ─────────────┐
                └───────────────────────────┬────────────────────────────────┘
                                            │ HTTP/JSON + SSE (Bearer dev JWT)
┌───────────────────────────────────────────▼───────────────────────────────────┐
│ dms_api  (FastAPI, :8000)                                                     │
│  auth · documents · versions · suggest · search · ask · tags · departments    │
└──────┬───────────────────────┬──────────────────────────┬─────────────────────┘
       │ enqueue job           │ query                    │ read/write
┌──────▼──────────┐   ┌────────▼─────────┐      ┌─────────▼──────────┐
│ Postgres 17     │   │ OpenSearch 2.19  │      │ MinIO (S3 API)     │
│ + pgvector      │   │  chunks index    │      │  documents bucket  │
│ source of truth │   │  titles index    │      │  blobs/{sha256}    │
│ + jobs queue    │   └────────▲─────────┘      └─────────▲──────────┘
└──────▲──────────┘            │                          │
       │ SKIP LOCKED poll      │ upsert/delete            │ get
┌──────┴───────────────────────┴──────────────────────────┴─────────────────────┐
│ dms_workers  (python -m dms_workers.run)                                      │
│  extract → index → enrich → summarize → (delta on new version)                │
└──────────────────────────────┬────────────────────────────────────────────────┘
                               │ HTTPS
                     ┌─────────▼──────────┐
                     │ OpenRouter         │  embeddings · chat · vision OCR
                     └────────────────────┘
```

**Principles (from the parent PRD):**
1. **Postgres is the source of truth.** OpenSearch can be rebuilt from Postgres + MinIO at any time. Chunk embeddings are also stored in Postgres, so a rebuild needs no re-embedding.
2. **Only pay for what changed.** Chunk IDs are derived from content (`{doc_id}:{sha1(normalized_text)[:16]}`), and chunk boundaries follow headings, so an edit changes only nearby chunks.
3. **Every client goes through the same retrieval path.** The UI and `/ask` both go through `search_service`, with the requesting user's groups applied on the server side.

### 3.1 Technology choices (local)
| Concern | Local choice | Later AWS swap |
|---|---|---|
| Object storage | MinIO (S3 API) | S3 (config change only) |
| Metadata + queue | Postgres 17 + pgvector; `jobs` table polled with `FOR UPDATE SKIP LOCKED` | RDS Postgres; SQS + Step Functions |
| Search | OpenSearch 2.19 single node, security disabled, 1 GB heap | Amazon OpenSearch Service |
| Embeddings | OpenRouter `baai/bge-m3` (dense, 1024 d) | BGE-M3 on SageMaker, or Titan V2 |
| Lexical side of hybrid | OpenSearch BM25 (+ `cjk` subfield for Chinese) | same |
| Hybrid fusion | Reciprocal rank fusion in Python (kNN + BM25 run as two queries) | same, or OpenSearch's hybrid query |
| Chat / enrichment LLM | OpenRouter `google/gemini-3.5-flash-lite` | Bedrock |
| Answer LLM (`/ask`) | OpenRouter `anthropic/claude-haiku-4.5` | Bedrock Claude |
| OCR (scanned pages, EN/MS/ZH) | OpenRouter vision `qwen/qwen3-vl-32b-instruct` | Textract + Bedrock vision |
| Text-layer extraction | PyMuPDF, python-docx, openpyxl | same |
| Duplicate detection | `datasketch` MinHash + LSH bands stored in Postgres | same |
| Auth | Dev JWT (HS256), seeded users | Cognito |

Every model ID is an env var. The ones above were checked against OpenRouter's live model list on 2026-10-07.

---

## 4. Repository layout (`~/aws-hackathon/backend`)

```
backend/
├── README.md
├── Makefile                     # up | down | migrate | api | worker | seed | test | eval | rebuild-index
├── pyproject.toml               # uv workspace root; ALL deps declared here in Wave 0
├── docker-compose.yml           # postgres(pgvector) · opensearch · minio
├── .env.example
├── docs/
│   ├── architecture.md
│   ├── api-contract.md          # mirror of §7 for the frontend
│   └── demo-script.md
├── packages/
│   ├── dms_core/src/dms_core/
│   │   ├── config.py            # pydantic-settings, reads .env
│   │   ├── ports.py             # Protocols: BlobStore, Embedder, Llm, VisionOcr, SearchIndex, Repo, JobQueue
│   │   ├── models.py            # Block, Chunk, Document, Version, Tag, RaptorNode, SearchHit … (pydantic)
│   │   ├── extract/             # filetype.py, blocks.py, pdf.py, docx.py, xlsx.py, image.py, router.py
│   │   ├── chunking/            # structure_chunker.py, chunk_id.py, tokens.py
│   │   ├── versioning/          # merkle.py, diff.py, delta_plan.py
│   │   ├── dedup/               # exact.py, minhash_lsh.py, semantic.py
│   │   ├── enrich/              # titles.py, doctype.py, metadata.py, tags.py, prompts.py
│   │   ├── raptor/              # cluster.py, build.py
│   │   ├── search/              # mappings.py, hybrid_query.py, suggest_query.py, fusion.py, facets.py, service.py
│   │   ├── answer/              # prompt.py, citations.py, service.py
│   │   └── access/              # groups.py (user → allowed_groups), guard.py
│   └── dms_adapters/src/dms_adapters/
│       ├── openrouter/          # client.py, embedder.py, llm.py, vision_ocr.py
│       ├── storage/             # minio_store.py
│       ├── opensearch/          # index.py (create indexes, bulk upsert, delete, query)
│       ├── postgres/            # db.py, repo.py, jobs.py
│       ├── fakes/               # in-memory implementations of every port (unit tests)
│       └── aws/                 # placeholder: s3/textract/bedrock adapters (post-hackathon)
├── db/migrations/               # 001_init.sql (single file for speed)
├── services/
│   ├── api/src/dms_api/         # main.py, deps.py, auth.py, schemas.py, routers/*.py
│   └── workers/src/dms_workers/ # run.py (poll loop), stages/{extract,index,enrich,summarize,delta}.py
├── scripts/                     # seed_demo.py, rebuild_index.py, eval_search.py, make_corpus.py
├── samples/
│   ├── corpus/                  # generated demo docs (see §9)
│   └── eval_queries.jsonl
└── tests/
    ├── unit/<area>/
    ├── integration/
    └── acceptance/
```

---

## 5. Data model (`db/migrations/001_init.sql`)

```sql
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE departments (id TEXT PRIMARY KEY, name TEXT NOT NULL);
CREATE TABLE users (id TEXT PRIMARY KEY, username TEXT UNIQUE NOT NULL, display_name TEXT NOT NULL);
CREATE TABLE user_departments (
  user_id TEXT REFERENCES users(id), department_id TEXT REFERENCES departments(id),
  role TEXT NOT NULL CHECK (role IN ('viewer','contributor','admin')),
  PRIMARY KEY (user_id, department_id));

CREATE TABLE documents (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  department_id TEXT NOT NULL REFERENCES departments(id),
  title TEXT NOT NULL DEFAULT 'Untitled document',
  title_source TEXT NOT NULL DEFAULT 'default',      -- metadata|heading|filename|llm|user|default
  title_confidence REAL NOT NULL DEFAULT 0,
  doctype TEXT,                                      -- policy|sop|circular|guideline|report|minutes|other
  meta JSONB NOT NULL DEFAULT '{}',                  -- {agency, reference_no, effective_date, supersedes_ref, language}
  superseded_by UUID REFERENCES documents(id),
  duplicate_of UUID REFERENCES documents(id),
  duplicate_tier TEXT,                               -- exact|near|semantic
  root_summary TEXT,
  minhash BYTEA,
  status TEXT NOT NULL DEFAULT 'UPLOADED',           -- UPLOADED|EXTRACTED|INDEXED|ENRICHED|READY|FAILED
  status_detail TEXT,
  current_version_id UUID,
  created_by TEXT REFERENCES users(id),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now());

CREATE TABLE versions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  document_id UUID NOT NULL REFERENCES documents(id),
  version_no INT NOT NULL,
  blob_sha256 TEXT NOT NULL,
  original_filename TEXT NOT NULL,
  mime_type TEXT NOT NULL,
  size_bytes BIGINT NOT NULL,
  page_count INT,
  blocks JSONB,                                      -- canonical blocks (§6.1)
  merkle_root TEXT,
  chunk_manifest JSONB,                              -- ordered list of chunk ids
  delta_stats JSONB,                                 -- {added, removed, reused, reembedded, raptor_nodes_refreshed}
  uploaded_by TEXT REFERENCES users(id),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (document_id, version_no));
CREATE INDEX ON versions (blob_sha256);

CREATE TABLE chunks (
  id TEXT PRIMARY KEY,                               -- {doc_id}:{sha1(normalized)[:16]}
  document_id UUID NOT NULL REFERENCES documents(id),
  text TEXT NOT NULL,
  heading_path TEXT[],
  page_from INT, page_to INT,
  token_count INT,
  embedding vector(1024));

CREATE TABLE minhash_bands (band INT, bucket TEXT, document_id UUID REFERENCES documents(id),
  PRIMARY KEY (band, bucket, document_id));

CREATE TABLE tags (
  id SERIAL PRIMARY KEY, name TEXT NOT NULL, department_id TEXT REFERENCES departments(id),
  centroid vector(1024), UNIQUE (name, department_id));
CREATE TABLE document_tags (
  document_id UUID REFERENCES documents(id), tag_id INT REFERENCES tags(id),
  source TEXT NOT NULL CHECK (source IN ('ai','user')),
  status TEXT NOT NULL CHECK (status IN ('suggested','confirmed')),
  similarity REAL, PRIMARY KEY (document_id, tag_id));

CREATE TABLE raptor_nodes (
  id TEXT PRIMARY KEY, document_id UUID REFERENCES documents(id), version_no INT,
  level INT NOT NULL, summary_text TEXT NOT NULL, embedding vector(1024), children TEXT[]);

CREATE TABLE jobs (
  id BIGSERIAL PRIMARY KEY,
  document_id UUID NOT NULL, version_id UUID,
  stage TEXT NOT NULL,                               -- extract|index|enrich|summarize|delta
  status TEXT NOT NULL DEFAULT 'queued',             -- queued|running|done|failed
  attempts INT NOT NULL DEFAULT 0,
  run_after TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_error TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now());
CREATE INDEX ON jobs (status, run_after);
```

**Allowed groups:** a document's `allowed_groups` = `[department_id]`, plus `"public"` when it belongs to the `public` department (agency-wide circulars). Only group IDs are written to the search index, never user IDs.

---

## 6. Pipeline and core algorithms

| Stage | Input → output | Status after | Notes |
|---|---|---|---|
| **upload** (API) | file → MinIO `blobs/{sha256}`, `documents` + `versions` rows, `extract` job | `UPLOADED` | Tier-1 duplicate check here: if the SHA-256 exists, set `duplicate_of` / `duplicate_tier='exact'` and **skip all processing** (reuse the existing version's chunks). |
| **extract** | blob → canonical `blocks` | `EXTRACTED` | Route **per page**. For a PDF page whose text layer is < 50 chars of text, render it at 200 dpi and OCR it with the vision model. Images always go to OCR. |
| **index** | blocks → chunks → embeddings → OpenSearch (`chunks` + `titles`) | `INDEXED` | Embed in batches of 32. Store embeddings in Postgres too. |
| **enrich** | chunks → title, doctype, meta, tags, MinHash (tier 2) → semantic check (tier 3) | `ENRICHED` | **One** LLM JSON call returns `{title, doctype, agency, reference_no, effective_date, supersedes_ref, language, tags[]}`. |
| **summarize** | chunks → RAPTOR tree → `root_summary`; level ≥ 1 nodes indexed into `chunks` with `level` | `READY` | Docs with ≤ 8 chunks get a single summary call instead. |
| **delta** (new version) | merkle diff vs the previous version → re-embed only new chunks, delete removed ones, rebuild only the summary nodes above changed chunks | `READY` | Writes `delta_stats`. |

On failure: retry with backoff (`attempts < 3`, `run_after = now() + 2^attempts s`), then `status=FAILED`, `status_detail=error`.

### 6.1 Canonical blocks
`Block = {type: heading|paragraph|table|cell, text, page, level?, bbox?, order, source: text_layer|ocr|docx|xlsx}`.
- **docx:** heading level comes from the style name (`Heading 1..6`); tables are serialized row by row as `col: value | col: value`.
- **xlsx:** one `heading` per sheet, then each row serialized as `header: value | …`. Never dump raw cells.
- **OCR prompt:** "Transcribe all text on this page exactly. Preserve headings as markdown `#`, keep table rows as `| a | b |`. Do not translate." The markdown is parsed back into blocks.

### 6.2 Chunking
Split on headings first. Then pack paragraphs into **350–500 tokens** with about **12 % overlap**. Never split a table row. Token count = `len(text)//4` (no tokenizer download). Each chunk keeps `heading_path`, `page_from` and `page_to`.

### 6.3 Merkle diff
Leaves = chunk IDs in order. Each parent = `sha256(left||right)`; with an odd count, the last node is promoted. Diff the old and new **sets** of chunk IDs to get `added`, `removed` and `reused`, and use the root to short-circuit when nothing changed. Delta plan: embed only `added`, delete `removed` from the index, copy embeddings for `reused`, and mark summary nodes dirty when any child is in `added ∪ removed`.

### 6.4 Duplicate detection
1. **Exact:** SHA-256 lookup at upload.
2. **Near:** MinHash with 128 permutations over 5-word shingles; LSH with 32 bands × 4 rows; candidate when Jaccard ≥ 0.8.
3. **Semantic (only for tier-2 candidates):** cosine similarity between the two documents' mean chunk embeddings ≥ 0.95 → `duplicate_tier='semantic'`.

Duplicates are always a **soft warning**: processing still completes.

### 6.5 Titles, doctype, metadata, tags
- **Title cascade:** (1) the PDF `/Title` or docx core title, rejected if it's junk (looks like the filename, has an extension, is < 3 chars); (2) the first heading, or for PDFs the largest-font span in the top third of page 1 (3–120 chars, not a date, not all digits); (3) the filename cleaned up; (4) the LLM title if the heuristic confidence is < 0.6.
- **Supersedes:** if `supersedes_ref` matches another document's `meta.reference_no` in the same department, set that document's `superseded_by` to the new one.
- **Tags:** seeded per department (§9). Attach suggested tags whose cosine similarity between the doc embedding and the tag centroid is ≥ 0.55. Also attach tags the LLM returned that match the taxonomy. When a user confirms or removes a tag, recompute that tag's centroid.

### 6.6 RAPTOR (simplified for time)
Leaf vectors → PCA to 10 dims → `sklearn` GaussianMixture, choosing k by BIC from 2..min(8, n/3) → summarize each cluster with the LLM (≤ 120 words) → embed the summaries → repeat until there is ≤ 1 cluster → root summary (≤ 150 words). Maximum depth is 3. UMAP is skipped deliberately (numba compile time).

### 6.7 Search
**`chunks` index fields:** `chunk_id`, `document_id`, `version_id`, `level` (0 = leaf), `allowed_groups` (keyword), `department_id`, `doctype`, `tags`, `title`, `text` (standard analyzer + `text.cjk` subfield using the built-in `cjk` analyzer), `heading_path`, `page_from`, `effective_date`, `superseded` (bool), `embedding` (knn_vector 1024, HNSW, `cosinesimil`, lucene engine).

**`titles` index:** one entry per document: `document_id`, `title` (+ subfields `edge` = edge n-grams 2–20, `tri` = trigrams), `filename`, `tags`, `doctype`, `allowed_groups`, `superseded`.

**`/suggest`:** a `bool.should` with tiered boosts: exact keyword match ×10 › `match_phrase_prefix` ×6 › `title.edge` ×3 › `title.tri` (`minimum_should_match: 70%`) ×1 › `fuzzy` (`fuzziness: AUTO`, `prefix_length: 2`) ×0.5. The `allowed_groups` terms filter is always applied. Returns 8 documents + 5 matching tags.

**`/search`:**
1. Embed the query (LRU cache keyed on the normalized query).
2. Run kNN (k = 50) and BM25 `multi_match` over `title^3, text, text.cjk, heading_path^2` (`fuzziness: AUTO`) **in parallel**. Both carry the same `bool.filter` (allowed groups + any user filters).
3. Reciprocal rank fusion (k = 60).
4. Collapse by `document_id`, keeping the best chunk as the snippet.
5. Down-rank superseded documents (× 0.7) and add `superseded_by`.
6. Hydrate the results from Postgres.
7. Facets: a `terms` aggregation on `doctype`, `tags` and `department_id` over the same filter, so they're safe by construction.
8. "Did you mean": if there are 0 hits or the top score is under the floor, run a phrase suggester on `titles`.

### 6.8 Ask
1. `search_service.search(user, question, k=8)` (the same function, under the same user).
2. Build a context of the top chunks (plus summary nodes for thematic questions), each labelled `[n]`.
3. Call the answer LLM with: "Answer only from the sources. Cite as [n]. If a source is superseded, say so and prefer the newer one. If the answer is not in the sources, say you couldn't find it."
4. Stream tokens over SSE, then send a final `citations` event: `[{n, document_id, title, chunk_id, page, quote}]`.

The assistant **cannot** see anything the user can't search.

---

## 7. API contract (frontend integration surface)

Base URL `http://localhost:8000`. All endpoints except `/health` and `/auth/dev-login` require `Authorization: Bearer <token>`. CORS allows `http://localhost:5173`. The OpenAPI spec is served at `/openapi.json` and the docs at `/docs`. Errors use the shape `{ "error": { "code": "...", "message": "..." } }`.

| Method & path | Request | Response |
|---|---|---|
| `GET /health` | — | `{status:"ok", deps:{postgres,opensearch,minio,openrouter}}` |
| `POST /auth/dev-login` | `{username}` | `{token, user:{id, display_name, departments:[{id,name,role}]}}` |
| `GET /me` | — | same `user` object |
| `GET /departments` | — | `[{id,name}]`: only the user's departments |
| `POST /documents` | multipart: `file`, `department_id` | `202 {document_id, version_id, status, duplicate:{document_id,title,tier}\|null}` |
| `GET /documents` | `?department_id&doctype&tag&status&page=1&page_size=20&sort=-created_at` | `{items:[DocumentSummary], total, page}` |
| `GET /documents/{id}` | — | `DocumentDetail` |
| `GET /documents/{id}/status` | — | `{status, status_detail, stages:[{stage,status,updated_at}]}` (poll every 1.5 s until `READY`/`FAILED`) |
| `GET /documents/{id}/file` | `?version_no` | file stream (original filename) |
| `PATCH /documents/{id}` | `{title?, doctype?}` | `DocumentDetail` (`title_source` becomes `user`) |
| `POST /documents/{id}/tags` | `{name}` | `TagRef[]` |
| `PUT /documents/{id}/tags/{tag_id}` | `{status:"confirmed"}` | `TagRef[]` |
| `DELETE /documents/{id}/tags/{tag_id}` | — | `TagRef[]` |
| `POST /documents/{id}/versions` | multipart `file` | `202 {version_id, version_no, status}` |
| `GET /documents/{id}/versions` | — | `[{version_no, created_at, uploaded_by, original_filename, merkle_root, delta_stats}]` |
| `GET /suggest` | `?q=` (≥ 2 chars) | `{documents:[{id,title,doctype,department_id}], tags:[{id,name}]}` |
| `POST /search` | `{query, filters?:{doctype[],department_id[],tags[],date_from,date_to,include_superseded}, page?, page_size?}` | `{results:[SearchResult], facets:{doctype:[{value,count}],tags:[…],department_id:[…]}, total, did_you_mean\|null, took_ms}` |
| `POST /ask` | `{question, filters?}` | **SSE**: `event: token` `{text}` … `event: citations` `{citations:[Citation]}` … `event: done` |
| `GET /tags` | `?department_id` | `[{id,name,department_id,doc_count}]` |

**Shapes**
```jsonc
// DocumentSummary
{ "id": "uuid", "title": "…", "doctype": "circular", "department_id": "finance",
  "status": "READY", "tags": [{"id":1,"name":"Budget","status":"confirmed"}],
  "meta": {"agency":"…","reference_no":"…","effective_date":"2026-01-01"},
  "superseded_by": null, "created_at": "…", "current_version_no": 2 }
// DocumentDetail = DocumentSummary + {
  "title_source":"heading", "title_confidence":0.82, "root_summary":"…",
  "duplicate": {"document_id":"…","title":"…","tier":"near"} | null,
  "versions":[…], "page_count": 12, "original_filename":"…", "mime_type":"application/pdf" }
// SearchResult
{ "document_id":"…", "title":"…", "doctype":"policy", "department_id":"hr",
  "snippet":"…<mark>remote work</mark>…", "page": 3, "heading_path":["2. Eligibility"],
  "score": 0.031, "tags":["HR"], "effective_date":"…", "superseded_by": null, "summary":"…" }
// Citation
{ "n":1, "document_id":"…", "title":"…", "chunk_id":"…", "page":3, "quote":"…" }
```

**Seeded dev users** (password-less dev login):
| username | departments |
|---|---|
| `alice` | finance (contributor), public (viewer) |
| `ben` | hr (contributor), public (viewer) |
| `chloe` | finance (viewer), hr (viewer), public (viewer) |
| `admin` | finance, hr, public (admin) |

---

## 8. Configuration (`.env.example`)

```bash
OPENROUTER_API_KEY=sk-or-...
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
EMBED_MODEL=baai/bge-m3
EMBED_DIM=1024
LLM_FAST_MODEL=google/gemini-3.5-flash-lite        # enrich + summaries
LLM_ANSWER_MODEL=anthropic/claude-haiku-4.5        # /ask
VISION_OCR_MODEL=qwen/qwen3-vl-32b-instruct        # scanned pages (EN/MS/ZH)
DATABASE_URL=postgresql://dms:dms@localhost:5432/dms
OPENSEARCH_URL=http://localhost:9200
S3_ENDPOINT=http://localhost:9000
S3_BUCKET=documents
S3_ACCESS_KEY=minioadmin
S3_SECRET_KEY=minioadmin
JWT_SECRET=dev-only-change-me
CORS_ORIGINS=http://localhost:5173
```

`docker-compose.yml` services: `pgvector/pgvector:pg17` (5432); `opensearchproject/opensearch:2.19.1` with `discovery.type=single-node`, `DISABLE_SECURITY_PLUGIN=true`, `DISABLE_INSTALL_DEMO_CONFIG=true`, `OPENSEARCH_JAVA_OPTS=-Xms1g -Xmx1g` (9200); `minio/minio server /data` (9000/9001). All three have healthchecks.

---

## 9. Demo corpus (`scripts/make_corpus.py` → `samples/corpus/`)

Synthetic documents for a fictional agency. **No real government content.**
| File | Dept | Purpose |
|---|---|---|
| `circular_2024_07_remote_work.pdf` | hr | Original circular, ref `PKP/HR/2024/07` |
| `circular_2026_03_remote_work.docx` | hr | **Supersedes** `PKP/HR/2024/07` (tests superseded handling) |
| `policy_procurement.docx` | finance | Multi-section policy (used for the version-edit demo) |
| `policy_procurement_v2.docx` | finance | Same document with one section changed (delta test) |
| `sop_claims_submission.pdf` | finance | SOP with numbered steps and a table |
| `quarterly_budget_q3_2026.xlsx` | finance | Spreadsheet extraction; the "quartely bud" typo test |
| `minutes_mesyuarat_jun_2026.pdf` | public | Meeting minutes **in Malay** |
| `guideline_data_sharing_zh.png` | public | **Scanned image** with Chinese text (OCR path) |
| `report_digital_services_2025_scanned.pdf` | public | 4 pages: 2 digital + 2 rasterized (per-page routing test) |
| `sop_claims_submission_copy.pdf` | finance | Byte-identical copy (exact-duplicate test) |
| `sop_claims_submission_resaved.pdf` | finance | Re-rendered copy with a changed footer (near-duplicate test) |

Seed tags: **finance** → Budget, Procurement, Claims, Audit · **hr** → Leave, Remote Work, Recruitment, Conduct · **public** → Digital Services, Data Governance, Meetings.
`samples/eval_queries.jsonl`: about 25 `{query, expected_document_file, user}` rows, mixing exact phrases, paraphrases, Malay/Chinese queries, typos, and thematic questions.

---

## 10. Build plan: parallel subagents, 60 minutes

### 10.0 Prerequisites (the user does these before the clock starts, about 5 min)
```bash
brew install uv orbstack          # or: brew install colima docker docker-compose && colima start --memory 6
open -a OrbStack                  # start the Docker engine
# get an OpenRouter key: https://openrouter.ai/keys → put it in backend/.env as OPENROUTER_API_KEY
```

### 10.1 Orchestration model
- **Lead** (the main Claude Code session) does Wave 0 alone, because it creates the **contracts** every agent codes against. It then launches each wave's agents **in one message** so they run concurrently, and runs integration at the end.
- **Rules for every agent:**
  1. Write **only** inside your owned paths. Never edit `pyproject.toml`, `config.py`, `ports.py`, `models.py`, `schemas.py`, `001_init.sql` or `mappings.py`. If you need a contract change, put it under `CONTRACT_REQUESTS` in your final report.
  2. Python 3.12, type hints, no new dependencies (all are pre-declared in Wave 0).
  3. Unit tests go in `tests/unit/<area>/` and use `dms_adapters.fakes`. Run `uv run pytest tests/unit/<area> -q` and make sure it **passes** before reporting.
  4. No network calls in unit tests. OpenRouter is only called by adapters and integration tests.
  5. Final report: files created, test result, known gaps, contract requests (≤ 15 lines).
- **Time boxes are hard.** At the end of a box, an agent ships what passes and lists the rest as gaps.

### 10.2 Timeline

```
T+0  ────────── Wave 0: Lead (10 min) ──────────────────────────────────────────┐
T+10 ┬─ A1 Extraction ─┬─ A2 Chunk/Version/Dedup ─┬─ A3 Adapters ─┬─ A4 Retrieval ─┬─ A5 Enrich/RAPTOR ─┬─ A6 Corpus/Eval ─┐  Wave 1 (25 min)
T+35 ┴────────────────────────── lead merge check (2 min) ─────────────────────────────────────────────────────────────┘
T+37 ┬─ B1 Workers pipeline ─┬─ B2 API service ─┬─ B3 Acceptance tests ─┐                                           Wave 2 (13 min)
T+50 ┴──────────────── Wave 3: Lead integration + demo run (10 min) ───┘
T+60  backend done → hand docs/api-contract.md + running :8000 to the frontend build
```

### 10.3 Wave 0: Lead (T+0 → T+10, sequential)
1. `uv init` workspace: root `pyproject.toml` with members `packages/*` and `services/*`, and **all** dependencies:
   `fastapi uvicorn[standard] python-multipart sse-starlette pydantic pydantic-settings pyjwt httpx psycopg[binary,pool] pgvector opensearch-py boto3 pymupdf python-docx openpyxl pillow datasketch scikit-learn numpy tenacity` · dev: `pytest pytest-asyncio respx reportlab`.
2. `docker-compose.yml`, `.env.example`, `Makefile`; run `make up` and wait for health.
3. `db/migrations/001_init.sql` (§5) and `make migrate`.
4. Contract files, written in full:
   - `dms_core/config.py`: settings (§8).
   - `dms_core/models.py`: `Block`, `Chunk`, `DocumentRow`, `VersionRow`, `TagRef`, `RaptorNode`, `SearchHit`, `SearchFilters`, `SearchResponse`, `Citation`, `EnrichmentResult`, `DeltaPlan`, `User`.
   - `dms_core/ports.py`: `Protocol`s with **exact signatures**:
     - `BlobStore.put(sha256, data, content_type)`, `.get(sha256) -> bytes`, `.exists(sha256) -> bool`
     - `Embedder.embed(texts: list[str]) -> list[list[float]]`
     - `Llm.complete(messages, *, model=None, json_schema=None, max_tokens=800) -> str`, `.stream(messages, *, model=None) -> AsyncIterator[str]`
     - `VisionOcr.transcribe(png_bytes: bytes, hint_lang: str|None) -> str`
     - `SearchIndex.ensure_indexes()`, `.upsert_chunks(docs)`, `.delete_chunks(ids)`, `.upsert_title(doc)`, `.search(index, body) -> dict`, `.msearch(...)`
     - `Repo`: document, version, chunk, tag, raptor and job CRUD (list every method)
     - `JobQueue.enqueue(document_id, version_id, stage)`, `.claim(stages) -> Job|None`, `.complete(job)`, `.fail(job, err)`
   - `dms_core/search/mappings.py`: both index bodies (§6.7).
   - `services/api/src/dms_api/schemas.py`: every request/response model in §7.
   - `dms_core/access/groups.py`: `allowed_groups(user) -> list[str]` (5 lines).
5. Package skeletons with empty `__init__.py`, so imports resolve.
6. Commit: `git init && git commit -m "wave0: contracts"`.

### 10.4 Wave 1: six parallel agents (T+10 → T+35)

| Agent | Owns (write access) | Builds | Done when |
|---|---|---|---|
| **A1 Extraction** | `dms_core/extract/**`, `tests/unit/extract/` | `filetype.py` (magic bytes → pdf/docx/xlsx/png/jpeg); `pdf.py` (PyMuPDF text layer, per-page coverage check, page render to PNG, font-size heading detection, `/Title`); `docx.py`; `xlsx.py`; `image.py`; `router.py` `extract(data, filename, ocr: VisionOcr) -> ExtractResult{blocks, page_count, embedded_title, ocr_pages[]}`; markdown→blocks parser for OCR output | Unit tests with generated fixtures (reportlab PDF with 1 blank "scanned" page + fake OCR) show OCR is called **only** for that page |
| **A2 Chunk · Version · Dedup** | `dms_core/chunking/**`, `versioning/**`, `dedup/**`, `tests/unit/{chunking,versioning,dedup}/` | Structure chunker (§6.2); `chunk_id`; merkle tree + diff + `delta_plan` (§6.3); `exact.py`, `minhash_lsh.py` (signature, bands, Jaccard), `semantic.py` (§6.4) | Tests: editing 1 of 10 sections changes ≤ 2 chunk IDs; merkle roots differ; ≥ 80 % reused; near-duplicate pair detected, unrelated pair not |
| **A3 Adapters** | `dms_adapters/**`, `tests/unit/adapters/`, `tests/integration/test_adapters.py` | OpenRouter client (httpx, tenacity retry, 429 backoff); `embedder.py` (batch 32, `/embeddings`); `llm.py` (`/chat/completions`, JSON mode via `response_format`, streaming SSE parsing); `vision_ocr.py` (image as base64 data URL); `minio_store.py` (boto3 + endpoint_url); `opensearch/index.py`; `postgres/repo.py` + `jobs.py` (SKIP LOCKED); **`fakes/`** for every port (FakeEmbedder = deterministic hash-seeded vectors) | Unit tests pass with `respx` mocks; integration test against docker (Postgres/OpenSearch/MinIO) passes; one live OpenRouter smoke call guarded by the env key |
| **A4 Retrieval** | `dms_core/search/**` (except `mappings.py`), `answer/**`, `access/guard.py`, `tests/unit/{search,answer}/` | `suggest_query.py`, `hybrid_query.py`, `fusion.py` (RRF), `facets.py`, `service.py` (`SearchService.search/suggest`, with the collapse, supersede down-rank and hydrate steps from §6.7); `answer/service.py` (`AskService.stream(user, question)` yields token and citations events); `guard.py` (`can_read(user, doc)`) | Tests with FakeSearchIndex: the RBAC filter is **always** present in every query body; RRF ordering is correct; citations map to chunks; ask with an empty result returns "couldn't find" |
| **A5 Enrich · RAPTOR** | `dms_core/enrich/**`, `raptor/**`, `tests/unit/{enrich,raptor}/` | Title cascade (§6.5); `prompts.py` (single JSON enrichment prompt + schema; RAPTOR cluster/root prompts); `doctype.py`/`metadata.py` (parse and validate LLM JSON, date normalization, supersedes match); `tags.py` (centroid similarity, centroid recompute); `raptor/cluster.py` (PCA + GMM + BIC) and `build.py` (tree build + incremental rebuild of dirty nodes) | Tests with FakeLlm/FakeEmbedder: cascade picks the correct source per fixture; RAPTOR on 30 chunks gives depth ≤ 3 with one root; a dirty-leaf rebuild touches only its ancestors |
| **A6 Corpus · Eval · Scripts** | `scripts/**`, `samples/**`, `docs/demo-script.md` | `make_corpus.py` builds every file in §9 (reportlab/python-docx/openpyxl/Pillow; rasterize pages for "scanned"; Chinese text needs a CJK font — use one that ships with macOS, e.g. `/System/Library/Fonts/PingFang.ttc`, or render Chinese into the PNG with Pillow); `eval_queries.jsonl`; `seed_demo.py` (departments, users, tags, uploads the corpus via the API); `eval_search.py` (top-5 hit rate for hybrid vs dense-only, as a table); `rebuild_index.py`; demo script | `python scripts/make_corpus.py` produces all 11 files; the scripts import cleanly (they run in Wave 3) |

**Lead merge check (T+35 → T+37):** run `uv run pytest tests/unit -q`, apply any accepted `CONTRACT_REQUESTS` (lead only), commit `wave1`.

### 10.5 Wave 2: three parallel agents (T+37 → T+50)

| Agent | Owns | Builds | Done when |
|---|---|---|---|
| **B1 Workers** | `services/workers/**`, `tests/unit/workers/` | `run.py`: poll loop that claims a job → dispatches to a stage → completes it or fails it with backoff; graceful SIGINT; `--once` flag for tests. Stages (§6): `extract`, `index` (chunk + embed + upsert chunks/titles + store embeddings), `enrich` (LLM JSON, title, doctype, meta, supersedes, tags, MinHash + semantic duplicate check), `summarize` (RAPTOR or single-shot; index summary nodes; set READY), `delta` (merkle diff → partial re-embed/upsert/delete → dirty RAPTOR rebuild → `delta_stats`). Each stage enqueues the next and updates `documents.status`. | Pipeline test with all fakes: upload → READY; new version → `delta_stats.reused ≥ 80 %` |
| **B2 API** | `services/api/**` (except `schemas.py`), `tests/unit/api/` | `main.py` (CORS, error envelope, lifespan that calls `ensure_indexes`), `auth.py` (dev-login JWT + `current_user` dependency), `deps.py` (wire real adapters from config; override with fakes in tests), routers for **every** endpoint in §7, including multipart upload with the tier-1 exact-duplicate short-circuit, the status endpoint, file download, tag operations, versions, suggest, search, and `/ask` over SSE (`sse-starlette`) | `TestClient` tests with fakes cover each route; a Finance user gets 403/404 on an HR doc; `/openapi.json` matches `schemas.py` |
| **B3 Acceptance** | `tests/acceptance/**`, `tests/integration/test_e2e.py` | Tests against the **running** stack (skipped unless `E2E=1`): mixed PDF OCR routing, exact duplicate skips processing, near duplicate flagged, one-section edit delta, `"quartely bud"` suggest, no cross-department leak (search, suggest **and** ask citations), supersede answer prefers the newer circular, rebuild-index restores search | Tests are collected cleanly; they run in Wave 3 |

### 10.6 Wave 3: Lead integration (T+50 → T+60)
```bash
make up migrate              # fresh DB + indexes
make api & make worker &     # :8000 + background worker
uv run python scripts/make_corpus.py
uv run python scripts/seed_demo.py
E2E=1 uv run pytest tests/acceptance -q
uv run python scripts/eval_search.py      # print top-5 hit rate: hybrid vs dense-only
```
Fix failures in priority order (§10.7). Then freeze `docs/api-contract.md` from `/openapi.json`, tag `v0.1-backend`, and hand it to the frontend.

### 10.7 Cut list (drop items from the bottom when time is short)
1. **Must:** upload → extract (incl. OCR) → index → `/search` with RBAC, `/documents`, `/status`
2. **Must:** `/suggest`, `/ask` with citations
3. **Should:** enrich (title / doctype / metadata / supersedes / tags)
4. **Should:** summaries (fall back to single-shot only)
5. **Could:** near-duplicate and semantic duplicate detection (keep exact)
6. **Could:** version delta (fall back to full re-index on a new version)

---

## 11. Frontend integration (after both builds finish)

1. Backend running on `:8000` with CORS `http://localhost:5173`; the frontend sets `VITE_API_BASE_URL=http://localhost:8000`.
2. The frontend generates its types from `http://localhost:8000/openapi.json` (e.g. `openapi-typescript`), or codes against `docs/api-contract.md` with mocks while the backend is being built.
3. **Integration checklist**
   - [ ] Dev login as `alice` and `ben`; the department switcher shows only their own departments.
   - [ ] Upload shows live status (`/status` polled every 1.5 s) through to READY, and a duplicate banner when `duplicate` is set.
   - [ ] Suggest box: 150–200 ms debounce, cancels in-flight requests (`AbortController`), ignores stale responses (sequence number), minimum 2 characters.
   - [ ] Search page: results, `<mark>` snippets, facets, "did you mean", superseded badge with a link to the newer doc.
   - [ ] Ask page: streams tokens over SSE (`fetch` + `ReadableStream`, since `EventSource` can't send a POST body); clicking a citation opens the doc at that page.
   - [ ] Document page: summary, editable title, tag confirm/remove/add, version history with `delta_stats`, download.
4. **AWS swap later (post-hackathon):** implement `dms_adapters/aws/*` for S3, Bedrock and Textract, plus the CDK stacks from the earlier AWS mapping (S3, RDS, OpenSearch Service, SQS + Step Functions, Lambda, Cognito). No changes are needed in `dms_core`.

## 12. Risks
| Risk | Mitigation |
|---|---|
| A one-hour budget is tight | Contract-first Wave 0, strict file ownership, hard time boxes, the §10.7 cut list |
| An OpenRouter model or ID changes | Every model is an env var; the `/health` check makes one cheap call per model at startup |
| OpenRouter rate limits during seeding | tenacity backoff; embed in batches; the worker processes one doc at a time |
| Docker isn't installed yet | §10.0 prerequisite (OrbStack/Colima) |
| OpenSearch memory on a 16 GB Mac | 1 GB heap, single node; models run remotely, so no local model memory is needed |
| Chinese OCR quality | Qwen3-VL is strong on CJK; `bench_ocr` stays out of scope |
| Uploading real government data to a third-party API | Demo corpus is synthetic only; for production, move to AWS Bedrock in-region (see §11.4) |
