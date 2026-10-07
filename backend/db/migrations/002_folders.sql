CREATE TABLE IF NOT EXISTS folders (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  parent_id TEXT NULL REFERENCES folders(id) ON DELETE CASCADE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS folders_sibling_name_idx ON folders ((coalesce(parent_id, '')), (lower(name)));
CREATE INDEX IF NOT EXISTS folders_parent_idx ON folders (parent_id);

ALTER TABLE documents
  ADD COLUMN IF NOT EXISTS folder_id TEXT REFERENCES folders(id) ON DELETE SET NULL,
  ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ;
CREATE INDEX IF NOT EXISTS documents_folder_idx ON documents (folder_id);

INSERT INTO folders (id, name, parent_id) VALUES
  ('inbox', 'Inbox', NULL),
  ('policies', 'Policies', NULL),
  ('sops', 'SOPs', NULL),
  ('circulars', 'Circulars', NULL),
  ('guidelines', 'Guidelines', NULL),
  ('reports', 'Reports', NULL),
  ('minutes', 'Minutes', NULL)
ON CONFLICT DO NOTHING;

INSERT INTO folders (id, name, parent_id) VALUES
  ('sop-fin', 'Finance', 'sops'),
  ('sop-hr', 'Human resources', 'sops'),
  ('circ-2024', '2024', 'circulars'),
  ('circ-2026', '2026', 'circulars'),
  ('min-mgmt', 'Management meetings', 'minutes')
ON CONFLICT DO NOTHING;

UPDATE documents SET folder_id = CASE
    WHEN doctype = 'policy' THEN 'policies'
    WHEN doctype = 'sop' AND department_id = 'finance' THEN 'sop-fin'
    WHEN doctype = 'sop' AND department_id = 'hr' THEN 'sop-hr'
    WHEN doctype = 'sop' THEN 'sops'
    WHEN doctype = 'circular' AND left(meta->>'effective_date', 4) = '2024' THEN 'circ-2024'
    WHEN doctype = 'circular' AND left(meta->>'effective_date', 4) = '2026' THEN 'circ-2026'
    WHEN doctype = 'circular' THEN 'circulars'
    WHEN doctype = 'guideline' THEN 'guidelines'
    WHEN doctype = 'report' THEN 'reports'
    WHEN doctype = 'minutes' THEN 'min-mgmt'
    ELSE 'inbox'
  END
WHERE folder_id IS NULL AND deleted_at IS NULL;
