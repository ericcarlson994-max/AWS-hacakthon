# GovSearch — frontend

Next.js 16 (App Router, React 19, TypeScript) client for the GovSearch FastAPI backend in `../backend`.

## Routes

- `/` — landing page with the scroll story and the sign-in section (`#login`)
- `/library` — document library: folder tree, folder cards, document table, uploads with live pipeline status, bulk move/delete, and the **Ask GovSearch** panel (Quick RAG or Research agent mode, cited answers, Details tab)

## Run

```bash
cp .env.example .env.local
npm install
npm run dev
```

The backend must be running on `NEXT_PUBLIC_API_BASE_URL` (default `http://localhost:8000`, see `../backend/README.md`). Sign in on the landing page with an officer email such as `alice@jpdn.sarawak.gov.my`, `ben@…`, `chloe@…` or `admin@…`; the pilot build maps the email's local part to the backend's dev users and does not verify passwords yet.

## Secrets

`.env*` is git-ignored except `.env.example`. Enable the secret-blocking pre-commit hook once per clone with `git config core.hooksPath .githooks`.

`design-reference/` holds the original Claude Design files this UI was built from.
