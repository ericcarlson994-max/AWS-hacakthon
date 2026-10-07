import type { DocStatus, DocumentSummary, Folder } from "./types";

export const TYPE_COLORS: Record<string, [string, string]> = {
  CIRCULAR: ["#1F6FE5", "#fff"],
  SOP: ["#0B4FC2", "#fff"],
  MINUTES: ["#96BAF0", "#0B2A5C"],
  POLICY: ["#CDDEF6", "#15171C"],
  GUIDELINE: ["#4A8DEC", "#fff"],
  REPORT: ["#E9EDF3", "#15171C"],
  DOCUMENT: ["#E2E5EA", "#3A3E46"],
};

export const ROOT_TYPE: Record<string, string> = {
  policies: "POLICY",
  sops: "SOP",
  circulars: "CIRCULAR",
  guidelines: "GUIDELINE",
  reports: "REPORT",
  minutes: "MINUTES",
};

export const DOCTYPE_LABEL: Record<string, string> = {
  policy: "POLICY",
  sop: "SOP",
  circular: "CIRCULAR",
  guideline: "GUIDELINE",
  report: "REPORT",
  minutes: "MINUTES",
};

export const INBOX = "inbox";
export const ALL = "all";

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

export function typeLabel(doctype?: string | null): string {
  return (doctype && DOCTYPE_LABEL[doctype]) || "DOCUMENT";
}

export function typeColors(label: string): [string, string] {
  return TYPE_COLORS[label] || TYPE_COLORS.DOCUMENT;
}

export function fmtDate(value?: string | null): string {
  if (!value) return "—";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  return `${String(d.getDate()).padStart(2, "0")} ${MONTHS[d.getMonth()]} ${d.getFullYear()}`;
}

export function fmtSize(bytes?: number | null): string {
  if (!bytes) return "—";
  return bytes > 1e6 ? `${(bytes / 1e6).toFixed(1)} MB` : `${Math.max(1, Math.round(bytes / 1e3))} KB`;
}

export function initials(name: string): string {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]!.toUpperCase())
    .join("");
}

const STAGE_LABEL: Record<DocStatus, string> = {
  UPLOADED: "Extracting",
  EXTRACTED: "Indexing",
  INDEXED: "Enriching",
  ENRICHED: "Summarising",
  READY: "Indexed",
  FAILED: "Failed",
};

export function statusView(status: DocStatus): { label: string; color: string; busy: boolean } {
  if (status === "READY") return { label: "Indexed", color: "#2E7D5B", busy: false };
  if (status === "FAILED") return { label: "Failed", color: "#B42318", busy: false };
  return { label: STAGE_LABEL[status], color: "#4A8DEC", busy: true };
}

export function documentRef(doc: DocumentSummary): string {
  return doc.meta?.reference_no || doc.original_filename || "—";
}

export function folderPath(folders: Map<string, Folder>, id?: string | null): Folder[] {
  const path: Folder[] = [];
  let current = id ? folders.get(id) : undefined;
  const seen = new Set<string>();
  while (current && !seen.has(current.id)) {
    seen.add(current.id);
    path.unshift(current);
    current = current.parent_id ? folders.get(current.parent_id) : undefined;
  }
  return path;
}

export function pathLabel(folders: Map<string, Folder>, id?: string | null): string {
  const path = folderPath(folders, id);
  return path.length ? path.map((f) => f.name).join(" / ") : "Inbox";
}

export function childrenOf(folders: Folder[], parent: string | null): Folder[] {
  return folders.filter((f) => (f.parent_id ?? null) === parent).sort((a, b) => sortKey(a).localeCompare(sortKey(b)));
}

function sortKey(folder: Folder): string {
  const order = ["inbox", "policies", "sops", "circulars", "guidelines", "reports", "minutes"];
  const index = order.indexOf(folder.id);
  return index >= 0 ? `0${index}` : `1${folder.name.toLowerCase()}`;
}

export function descendants(folders: Folder[], id: string): string[] {
  const out = [id];
  for (let i = 0; i < out.length; i++) {
    folders.filter((f) => f.parent_id === out[i]).forEach((f) => out.push(f.id));
  }
  return out;
}

export function rootOf(folders: Map<string, Folder>, id: string): string | undefined {
  return folderPath(folders, id)[0]?.id;
}
