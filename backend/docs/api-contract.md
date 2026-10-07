# GovDocs Search API Contract

Source of truth: spec section 7 (hackathonprd.md). The live OpenAPI schema is at `http://localhost:8000/openapi.json` and interactive docs at `http://localhost:8000/docs`.


Base URL `http://localhost:8000`. All endpoints except `/health` and `/auth/dev-login` require `Authorization: Bearer <token>`. CORS allows `http://localhost:3000` and `http://localhost:5173` (env `CORS_ORIGINS`, comma-separated). The OpenAPI spec is served at `/openapi.json` and the docs at `/docs`. Errors use the shape `{ "error": { "code": "...", "message": "..." } }`.

| Method & path | Request | Response |
|---|---|---|
| `GET /health` | — | `{status:"ok", deps:{postgres,opensearch,minio,openrouter}}` |
| `POST /auth/dev-login` | `{username}` | `{token, user:{id, display_name, departments:[{id,name,role}]}}` |
| `GET /me` | — | same `user` object |
| `GET /departments` | — | `[{id,name}]`: only the user's departments |
| `GET /folders` | — | `[Folder]`: every folder (agency-wide tree); `doc_count` = non-deleted documents the caller can read directly in that folder |
| `POST /folders` | `{name, parent_id?}` | `201 Folder`; `400` empty name, `404` unknown parent, `409` sibling with the same name (case-insensitive), `403` without contributor/admin role in any department |
| `PATCH /folders/{id}` | `{name?, parent_id?}` (`parent_id:null` moves to root) | `Folder`; same codes as POST, `400` when moving into itself/its subtree, `400` for renaming or moving `inbox` |
| `DELETE /folders/{id}` | — | `204`; deletes the folder and all subfolders and soft-deletes every document in them. `400` for `inbox`, `404` unknown, `409 {error:{code:"forbidden_contents"}}` (nothing deleted) if any contained document is not writable by the caller |
| `POST /documents` | multipart: `file`, `department_id`, `folder_id?` (default `inbox`, `404` if unknown) | `202 {document_id, version_id, status, duplicate:{document_id,title,tier}\|null}` |
| `GET /documents` | `?department_id&doctype&tag&status&folder_id&recursive=false&page=1&page_size=20&sort=-created_at` (`page_size` ≤ 200; `folder_id` = exact folder, `recursive=true` includes subfolders, `404` if unknown folder) | `{items:[DocumentSummary], total, page}` |
| `GET /documents/{id}` | — | `DocumentDetail` |
| `GET /documents/{id}/status` | — | `{status, status_detail, stages:[{stage,status,updated_at}]}` (poll every 1.5 s until `READY`/`FAILED`) |
| `GET /documents/{id}/file` | `?version_no` | file stream (original filename) |
| `PATCH /documents/{id}` | `{title?, doctype?, folder_id?}` | `DocumentDetail` (`title_source` becomes `user` on title change; `folder_id` moves the document, `404` if unknown, `null` moves to `inbox`); requires write access |
| `DELETE /documents/{id}` | — | `204`; soft-delete (hidden from list/get/search, removed from the search index). `404` if not readable, `403` if not writable. Documents with `superseded_by` pointing to it are left unchanged |
| `POST /documents/{id}/tags` | `{name}` | `TagRef[]` |
| `PUT /documents/{id}/tags/{tag_id}` | `{status:"confirmed"}` | `TagRef[]` |
| `DELETE /documents/{id}/tags/{tag_id}` | — | `TagRef[]` |
| `POST /documents/{id}/versions` | multipart `file` | `202 {version_id, version_no, status}` |
| `GET /documents/{id}/versions` | — | `[{version_no, created_at, uploaded_by, original_filename, merkle_root, delta_stats}]` |
| `GET /suggest` | `?q=` (≥ 2 chars) | `{documents:[{id,title,doctype,department_id}], tags:[{id,name}]}` |
| `POST /search` | `{query, filters?:{doctype[],department_id[],tags[],document_ids[],date_from,date_to,include_superseded}, page?, page_size?}` (`document_ids` restricts results to those documents) | `{results:[SearchResult], facets:{doctype:[{value,count}],tags:[…],department_id:[…]}, total, did_you_mean\|null, took_ms}` |
| `POST /ask` | `{question, filters?, mode?: "rag"\|"agent", history?: [{role:"user"\|"assistant", content}]}` (`filters` has the search shape; `document_ids` scopes RAG retrieval, every agent search and agent `list_documents`) | **SSE**: `event: step` `{tool, input}` (agent mode only, one per tool call) … `event: token` `{text}` … `event: citations` `{citations:[Citation]}` … `event: done` `{tool_calls?, sources?}`; on failure `event: error` `{message}` |
| `GET /tags` | `?department_id` | `[{id,name,department_id,doc_count}]` |

**Shapes**
```jsonc
// DocumentSummary
{ "id": "uuid", "title": "…", "doctype": "circular", "department_id": "finance",
  "status": "READY", "tags": [{"id":1,"name":"Budget","status":"confirmed"}],
  "meta": {"agency":"…","reference_no":"…","effective_date":"2026-01-01"},
  "superseded_by": null, "created_at": "…", "current_version_no": 2,
  "folder_id": "policies", "updated_at": "…", "size_bytes": 48211,
  "original_filename": "policy_procurement.docx", "created_by": "alice", "page_count": 4 }
// DocumentDetail = DocumentSummary + {
  "title_source":"heading", "title_confidence":0.82, "root_summary":"…",
  "duplicate": {"document_id":"…","title":"…","tier":"near"} | null,
  "versions":[…], "mime_type":"application/pdf", "status_detail": null }
// Folder
{ "id": "sop-fin", "name": "Finance", "parent_id": "sops", "doc_count": 4 }
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



## Folders and auto-filing

Folders are agency-wide (not per department). Seeded tree: `inbox` Inbox, `policies` Policies, `sops` SOPs (`sop-fin` Finance, `sop-hr` Human resources), `circulars` Circulars (`circ-2024` 2024, `circ-2026` 2026), `guidelines` Guidelines, `reports` Reports, `minutes` Minutes (`min-mgmt` Management meetings). New folder ids are a slug of the name plus a short random suffix. Uploads land in `inbox` unless `folder_id` is given. When enrichment detects the doctype of a document that is still in `inbox` (or has no folder), the worker files it: policy → `policies`, sop → `sop-fin`/`sop-hr` by department else `sops`, circular → `circ-2024`/`circ-2026` by `meta.effective_date` year else `circulars`, guideline → `guidelines`, report → `reports`, minutes → `min-mgmt`; `other` stays in `inbox`. Documents a user has moved out of `inbox` are never re-filed.

## Status lifecycle

`UPLOADED → EXTRACTED → INDEXED → ENRICHED → READY` (or `FAILED` with `status_detail`). An exact duplicate upload returns `duplicate.tier = "exact"` immediately and skips processing. Near and semantic duplicates appear later in `DocumentDetail.duplicate` as a soft warning.

## curl examples

```bash
API=http://localhost:8000

curl -s $API/health

TOKEN=$(curl -s -X POST $API/auth/dev-login -H 'Content-Type: application/json' \
  -d '{"username":"alice"}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["token"])')
AUTH="Authorization: Bearer $TOKEN"

curl -s $API/me -H "$AUTH"
curl -s $API/departments -H "$AUTH"

curl -s -X POST $API/documents -H "$AUTH" \
  -F file=@samples/corpus/sop_claims_submission.pdf -F department_id=finance

curl -s "$API/documents/$DOC_ID/status" -H "$AUTH"
curl -s "$API/documents?department_id=finance&page=1&page_size=20&sort=-created_at" -H "$AUTH"
curl -s "$API/documents/$DOC_ID" -H "$AUTH"
curl -s -OJ "$API/documents/$DOC_ID/file?version_no=1" -H "$AUTH"

curl -s -X PATCH "$API/documents/$DOC_ID" -H "$AUTH" -H 'Content-Type: application/json' \
  -d '{"title":"SOP: Claims Submission (2025)"}'

curl -s $API/folders -H "$AUTH"
curl -s -X POST $API/folders -H "$AUTH" -H 'Content-Type: application/json' -d '{"name":"Budget 2027","parent_id":"circulars"}'
curl -s -X PATCH "$API/folders/$FOLDER_ID" -H "$AUTH" -H 'Content-Type: application/json' -d '{"name":"Budget FY2027"}'
curl -s -X DELETE "$API/folders/$FOLDER_ID" -H "$AUTH"
curl -s "$API/documents?folder_id=sops&recursive=true&page_size=200" -H "$AUTH"
curl -s -X PATCH "$API/documents/$DOC_ID" -H "$AUTH" -H 'Content-Type: application/json' -d '{"folder_id":"policies"}'
curl -s -X DELETE "$API/documents/$DOC_ID" -H "$AUTH"

curl -s -X POST "$API/documents/$DOC_ID/tags" -H "$AUTH" -H 'Content-Type: application/json' -d '{"name":"Claims"}'
curl -s -X PUT "$API/documents/$DOC_ID/tags/3" -H "$AUTH" -H 'Content-Type: application/json' -d '{"status":"confirmed"}'
curl -s -X DELETE "$API/documents/$DOC_ID/tags/3" -H "$AUTH"

curl -s -X POST "$API/documents/$DOC_ID/versions" -H "$AUTH" -F file=@samples/corpus/policy_procurement_v2.docx
curl -s "$API/documents/$DOC_ID/versions" -H "$AUTH"

curl -s "$API/suggest?q=quartely%20bud" -H "$AUTH"

curl -s -X POST $API/search -H "$AUTH" -H 'Content-Type: application/json' -d '{
  "query": "procurement thresholds",
  "filters": {"doctype": ["policy"], "include_superseded": false},
  "page": 1, "page_size": 10
}'

curl -N -X POST $API/ask -H "$AUTH" -H 'Content-Type: application/json' \
  -d '{"question":"What is the current policy on remote work?"}'

curl -s "$API/tags?department_id=finance" -H "$AUTH"
```

Error example:

```json
{ "error": { "code": "not_found", "message": "Document not found" } }
```

## Agent mode (`mode: "agent"`)

`mode: "rag"` (default) does one search and one answer: fast, about 2 to 3 s.
`mode: "agent"` runs a Strands Agents research agent (Claude Haiku 4.5 through OpenRouter). It plans and calls tools, then writes one cited answer, in about 6 to 15 s. Use it for comparisons, version-change questions and questions that need several searches. Tools: `search_documents`, `get_document`, `get_document_versions` (returns the exact added and removed passages), `list_documents`. Every tool runs as the calling user, so department isolation is identical to `/search`.

- Render each `step` event as a progress line, for example "Searching: remote work circular 2026" or "Reading version history".
- `history` is optional chat context (the last 6 turns are used). Send previous user and assistant messages to support follow-up questions.
- Citation numbers can be sparse (for example [1], [6], [7]) because they number every source the agent saw. Map them through the `citations` event, not by array index.
- With no OpenRouter key the agent falls back to RAG and sends one `step` with `tool: "rag_fallback"`.

## Consuming `/ask` (SSE over POST)

`EventSource` cannot send a POST body, so use `fetch` and read the `ReadableStream`. Events are separated by a blank line; each has an `event:` line and a JSON `data:` line.

```ts
type Citation = { n: number; document_id: string; title: string; chunk_id: string; page: number | null; quote: string };

export async function ask(
  question: string,
  token: string,
  handlers: { onToken: (text: string) => void; onCitations: (citations: Citation[]) => void; onDone: () => void },
  signal?: AbortSignal,
) {
  const response = await fetch(`${import.meta.env.VITE_API_BASE_URL}/ask`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "text/event-stream", Authorization: `Bearer ${token}` },
    body: JSON.stringify({ question }),
    signal,
  });
  if (!response.ok || !response.body) throw new Error(`ask failed: ${response.status}`);

  const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += value.replace(/\r\n/g, "\n");
    let boundary: number;
    while ((boundary = buffer.indexOf("\n\n")) !== -1) {
      const rawEvent = buffer.slice(0, boundary);
      buffer = buffer.slice(boundary + 2);
      let eventName = "message";
      const dataLines: string[] = [];
      for (const line of rawEvent.split("\n")) {
        if (line.startsWith("event:")) eventName = line.slice(6).trim();
        else if (line.startsWith("data:")) dataLines.push(line.slice(5).trimStart());
      }
      const data = dataLines.length ? JSON.parse(dataLines.join("\n")) : {};
      if (eventName === "token") handlers.onToken(data.text);
      else if (eventName === "citations") handlers.onCitations(data.citations);
      else if (eventName === "done") handlers.onDone();
    }
  }
}
```

## Frontend integration notes

- Set `VITE_API_BASE_URL=http://localhost:8000`; CORS allows `http://localhost:3000` and `http://localhost:5173` (env `CORS_ORIGINS`, comma-separated).
- Generate types with `npx openapi-typescript http://localhost:8000/openapi.json -o src/api/schema.ts`.
- Suggest box: 150–200 ms debounce, `AbortController` per request, ignore stale responses via a sequence number, minimum 2 characters.
- Poll `/documents/{id}/status` every 1.5 s until `READY` or `FAILED`.
- Show a superseded badge when `superseded_by` is set and link to the newer document.
