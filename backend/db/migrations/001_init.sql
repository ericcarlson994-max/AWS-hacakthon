CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS departments (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS users (
  id TEXT PRIMARY KEY,
  username TEXT UNIQUE NOT NULL,
  display_name TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS user_departments (
  user_id TEXT NOT NULL REFERENCES users(id),
  department_id TEXT NOT NULL REFERENCES departments(id),
  role TEXT NOT NULL CHECK (role IN ('viewer','contributor','admin')),
  PRIMARY KEY (user_id, department_id)
);

CREATE TABLE IF NOT EXISTS documents (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  department_id TEXT NOT NULL REFERENCES departments(id),
  title TEXT NOT NULL DEFAULT 'Untitled document',
  title_source TEXT NOT NULL DEFAULT 'default',
  title_confidence REAL NOT NULL DEFAULT 0,
  doctype TEXT,
  meta JSONB NOT NULL DEFAULT '{}',
  superseded_by UUID REFERENCES documents(id),
  duplicate_of UUID REFERENCES documents(id),
  duplicate_tier TEXT,
  root_summary TEXT,
  minhash BYTEA,
  status TEXT NOT NULL DEFAULT 'UPLOADED',
  status_detail TEXT,
  current_version_id UUID,
  created_by TEXT REFERENCES users(id),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS documents_department_idx ON documents (department_id);
CREATE INDEX IF NOT EXISTS documents_reference_idx ON documents ((meta->>'reference_no'));

CREATE TABLE IF NOT EXISTS versions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  document_id UUID NOT NULL REFERENCES documents(id),
  version_no INT NOT NULL,
  blob_sha256 TEXT NOT NULL,
  original_filename TEXT NOT NULL,
  mime_type TEXT NOT NULL,
  size_bytes BIGINT NOT NULL,
  page_count INT,
  blocks JSONB,
  embedded_title TEXT,
  merkle_root TEXT,
  chunk_manifest JSONB,
  delta_stats JSONB,
  uploaded_by TEXT REFERENCES users(id),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (document_id, version_no)
);
CREATE INDEX IF NOT EXISTS versions_sha_idx ON versions (blob_sha256);

CREATE TABLE IF NOT EXISTS chunks (
  id TEXT PRIMARY KEY,
  document_id UUID NOT NULL REFERENCES documents(id),
  ord INT NOT NULL DEFAULT 0,
  text TEXT NOT NULL,
  heading_path TEXT[] NOT NULL DEFAULT '{}',
  page_from INT,
  page_to INT,
  token_count INT NOT NULL DEFAULT 0,
  embedding vector(1024)
);
CREATE INDEX IF NOT EXISTS chunks_document_idx ON chunks (document_id);

CREATE TABLE IF NOT EXISTS minhash_bands (
  band INT NOT NULL,
  bucket TEXT NOT NULL,
  document_id UUID NOT NULL REFERENCES documents(id),
  PRIMARY KEY (band, bucket, document_id)
);

CREATE TABLE IF NOT EXISTS tags (
  id SERIAL PRIMARY KEY,
  name TEXT NOT NULL,
  department_id TEXT REFERENCES departments(id),
  centroid vector(1024),
  UNIQUE (name, department_id)
);

CREATE TABLE IF NOT EXISTS document_tags (
  document_id UUID NOT NULL REFERENCES documents(id),
  tag_id INT NOT NULL REFERENCES tags(id),
  source TEXT NOT NULL CHECK (source IN ('ai','user')),
  status TEXT NOT NULL CHECK (status IN ('suggested','confirmed')),
  similarity REAL,
  PRIMARY KEY (document_id, tag_id)
);

CREATE TABLE IF NOT EXISTS raptor_nodes (
  id TEXT PRIMARY KEY,
  document_id UUID NOT NULL REFERENCES documents(id),
  version_no INT NOT NULL,
  level INT NOT NULL,
  summary_text TEXT NOT NULL,
  embedding vector(1024),
  children TEXT[] NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS raptor_document_idx ON raptor_nodes (document_id, version_no);

CREATE TABLE IF NOT EXISTS jobs (
  id BIGSERIAL PRIMARY KEY,
  document_id UUID NOT NULL,
  version_id UUID,
  stage TEXT NOT NULL CHECK (stage IN ('extract','index','enrich','summarize','delta')),
  status TEXT NOT NULL DEFAULT 'queued' CHECK (status IN ('queued','running','done','failed')),
  attempts INT NOT NULL DEFAULT 0,
  run_after TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_error TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS jobs_claim_idx ON jobs (status, run_after);
CREATE INDEX IF NOT EXISTS jobs_document_idx ON jobs (document_id);
