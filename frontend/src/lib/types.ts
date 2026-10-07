export type Role = "viewer" | "contributor" | "admin";

export type Membership = { id: string; name: string; role: Role };

export type User = {
  id: string;
  username: string;
  display_name: string;
  departments: Membership[];
};

export type LoginResponse = { token: string; user: User };

export type DocStatus = "UPLOADED" | "EXTRACTED" | "INDEXED" | "ENRICHED" | "READY" | "FAILED";

export type TagRef = {
  id: number;
  name: string;
  status: "suggested" | "confirmed";
  source: "ai" | "user";
  similarity?: number | null;
};

export type DocumentMeta = {
  agency?: string | null;
  reference_no?: string | null;
  effective_date?: string | null;
  supersedes_ref?: string | null;
  language?: string | null;
};

export type DuplicateInfo = { document_id: string; title: string; tier: "exact" | "near" | "semantic" };

export type DeltaStats = {
  added: number;
  removed: number;
  reused: number;
  reembedded: number;
  raptor_nodes_refreshed: number;
};

export type VersionOut = {
  version_no: number;
  created_at: string;
  uploaded_by?: string | null;
  original_filename: string;
  merkle_root?: string | null;
  delta_stats?: DeltaStats | null;
};

export type DocumentSummary = {
  id: string;
  title: string;
  doctype?: string | null;
  department_id: string;
  status: DocStatus;
  tags: TagRef[];
  meta: DocumentMeta;
  superseded_by?: string | null;
  created_at: string;
  updated_at: string;
  current_version_no?: number | null;
  folder_id?: string | null;
  size_bytes?: number | null;
  original_filename?: string | null;
  created_by?: string | null;
  page_count?: number | null;
};

export type DocumentDetail = DocumentSummary & {
  title_source: string;
  title_confidence: number;
  root_summary?: string | null;
  duplicate?: DuplicateInfo | null;
  versions: VersionOut[];
  mime_type?: string | null;
  status_detail?: string | null;
};

export type DocumentList = { items: DocumentSummary[]; total: number; page: number };

export type Folder = { id: string; name: string; parent_id: string | null; doc_count: number };

export type UploadResponse = {
  document_id: string;
  version_id: string;
  status: DocStatus;
  duplicate?: DuplicateInfo | null;
};

export type SearchFilters = {
  doctype?: string[];
  department_id?: string[];
  tags?: string[];
  document_ids?: string[];
  include_superseded?: boolean;
};

export type Citation = {
  n: number;
  document_id: string;
  title: string;
  chunk_id: string;
  page?: number | null;
  quote: string;
};

export type AskMode = "rag" | "agent";

export type ChatTurn = { role: "user" | "assistant"; content: string };

export type AgentStep = { tool: string; input: Record<string, unknown> };

export type AskHandlers = {
  onToken: (text: string) => void;
  onStep: (step: AgentStep) => void;
  onCitations: (citations: Citation[]) => void;
  onError: (message: string) => void;
};
