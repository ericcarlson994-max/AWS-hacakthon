# GovSearch — frontend

**Team:** Marcus Yeo Kuok Huang · Eric Carlson Anak Herryson · See the [project README](../README.md) for the overview.

Next.js 16 (App Router, React 19, TypeScript) web app for GovSearch. It talks to the FastAPI backend in `../backend`.

## Pages

| Route | What it shows |
|---|---|
| `/` | Landing page: scroll-driven 3D story, then the sign-in section (`#login`) |
| `/library` | The library: folder tree and cards, document table with live processing status, uploads with progress, bulk move and delete, and the **Ask GovSearch** panel with Quick and Research agent modes, cited answers and a Details tab with the AI summary |

## Run locally

```bash
cp .env.example .env.local
npm install
npm run dev            # http://localhost:3000
```

The backend must be reachable at `NEXT_PUBLIC_API_BASE_URL` (default `http://localhost:8000`). Sign in on the landing page with a demo officer email such as `alice@jpdn.sarawak.gov.my`, `ben@…`, `chloe@…` or `admin@…`. The pilot build maps the email's username to the backend's demo users and does not check passwords yet.

## Deploy to Vercel

[![Deploy with Vercel](https://vercel.com/button)](https://vercel.com/new/clone?repository-url=https%3A%2F%2Fgithub.com%2Fericcarlson994-max%2FAWS-hacakthon&root-directory=frontend&project-name=govsearch&env=NEXT_PUBLIC_API_BASE_URL&envDescription=Public%20HTTPS%20URL%20of%20the%20GovSearch%20FastAPI%20backend)

**Dashboard**

1. Vercel → Add New → Project → import the GitHub repository.
2. Set **Root Directory** to `frontend`. Framework, install (`npm ci`) and build (`npm run build`) come from `vercel.json`.
3. Add the environment variable `NEXT_PUBLIC_API_BASE_URL` = your backend's public **HTTPS** URL (an HTTPS page cannot call an HTTP API).
4. Deploy.

**CLI**

```bash
cd frontend
npx vercel link
npx vercel env add NEXT_PUBLIC_API_BASE_URL production
npx vercel --prod
```

**Then allow the Vercel domain on the backend** (`backend/.env`) and restart the API:

```bash
CORS_ORIGINS=http://localhost:3000,https://your-app.vercel.app
CORS_ORIGIN_REGEX=https://.*\.vercel\.app
```

`NEXT_PUBLIC_` variables are baked in at build time, so redeploy after changing the backend URL.

**Where the backend runs.** Vercel hosts only this frontend. The backend needs Docker services (Postgres, OpenSearch, S3-compatible storage) and an always-on worker, so host it separately: a single AWS EC2 instance running `docker compose` is the simplest, or a Cloudflare Tunnel / ngrok from a laptop for a live demo.

## Secrets

`.env*` is git-ignored except `.env.example`. Enable the secret-blocking pre-commit hook once per clone with `git config core.hooksPath .githooks` (from the repository root use `backend/.githooks`).

`design-reference/` holds the original Claude Design files this UI was built from.
