# GovDocs Search: 5-Minute Demo

Prerequisites: `make up migrate`, `make api` and `make worker` running, `make corpus` and `make seed` completed. Open the frontend at http://localhost:5173 (or use the curl commands in `docs/api-contract.md`).

## 0:00 – 0:30 Setting the scene

"JPDN is a fictional state digital services department. Its officers deal with circulars, policies, SOPs, budgets, minutes in Malay and guidelines in Chinese, some of them scanned. Finding the current rule is slow. GovDocs Search makes all of it searchable, summarized and access-controlled."

Log in as **chloe** (finance, hr and public viewer) and show the document list: 10 seeded documents with doctypes, tags and READY status.

## 0:30 – 1:15 Upload and live status

1. Log in as **admin** and upload `samples/corpus/report_digital_services_2025_scanned.pdf` to `public` (or show the already-seeded one).
2. Point out the status stepper: UPLOADED → EXTRACTED → INDEXED → ENRICHED → READY.
3. Open the document: pages 1 and 3 came from the text layer, pages 2 and 4 were OCR'd because they are images. Show the AI title, doctype `report` and summary.

## 1:15 – 2:00 Suggest and typo tolerance

Type `quartely bud` in the search box. The suggestion **Quarterly Budget Q3 2026** appears despite the typo. Open it: the spreadsheet rows were extracted as `header: value` lines, so a search for `overtime exceeded allocation` lands on the budget notes.

## 2:00 – 2:45 Hybrid search across languages

1. Search `how many days can I work from home each week`. The 2026 circular ranks first; the 2024 circular shows a **Superseded** badge linking to the newer one.
2. Search in Malay: `prestasi perbelanjaan suku kedua` returns the June 2026 minutes.
3. Search in Chinese: `个人数据保护` returns the data sharing guideline that was only an image.
4. Show the facets (doctype, tags, department).

## 2:45 – 3:30 Ask with citations

Ask: **"What is the current policy on remote work?"** The answer streams in, states three days per week from 1 March 2026, notes that PKP/HR/2026/03 supersedes PKP/HR/2024/07 (two days), and cites both. Click a citation to open the circular at that page.

## 3:30 – 4:10 Access control

Log in as **alice** (finance + public). Repeat the remote work search and ask: zero hits from the HR circulars, and the assistant says it could not find the answer. Suggest for `remote` returns nothing from HR. Log in as **ben** (hr + public): no procurement or budget documents.

## 4:10 – 4:40 Duplicates

Show `sop_claims_submission_copy.pdf`: flagged as an **exact** duplicate at upload and not processed again. Show `sop_claims_submission_resaved.pdf`: only the footer changed, flagged as a **near** duplicate after enrichment, as a soft warning.

## 4:40 – 5:00 Versioning with delta

Open the Procurement Policy, version history. Version 2 (`policy_procurement_v2.docx`) changed only section 4 (procurement thresholds). The version's `delta_stats` show a handful of added and removed chunks, most chunks reused, and only the changed chunks re-embedded.

Close: "Saved, understood, findable, and only by the people who should see it."
