"use client";

import { useCallback, useEffect, useMemo, useRef, useState, type DragEvent } from "react";
import { useRouter } from "next/navigation";
import { AssistantPanel, stepLabel, type ChatMessage } from "./AssistantPanel";
import { DetailsPanel } from "./DetailsPanel";
import { Modal, type ModalState } from "./Modal";
import { ApiError, api, askStream, clearSession, getToken, uploadDocument, uploadVersion } from "@/lib/api";
import {
  ALL,
  INBOX,
  ROOT_TYPE,
  childrenOf,
  descendants,
  documentRef,
  fmtDate,
  folderPath,
  initials,
  pathLabel,
  rootOf,
  statusView,
  typeColors,
  typeLabel,
} from "@/lib/format";
import type { AskMode, ChatTurn, DocumentDetail, DocumentSummary, Folder, SearchFilters, User } from "@/lib/types";

type Upload = {
  key: string;
  name: string;
  folderId: string;
  progress: number;
  phase: "uploading" | "processing" | "failed";
  documentId?: string;
  duplicateOf?: string;
  error?: string;
};

type Menu = { kind: "folder" | "file"; id: string } | null;
type Scope = { folder?: string; ids?: string[] } | null;

const POLL_MS = 2000;
let keySeq = 0;
const nextKey = (prefix: string) => `${prefix}${++keySeq}`;

export function LibraryApp() {
  const router = useRouter();
  const [user, setUser] = useState<User | null>(null);
  const [folders, setFolders] = useState<Folder[]>([]);
  const [docs, setDocs] = useState<DocumentSummary[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [toast, setToast] = useState("");
  const [current, setCurrent] = useState<string>(ALL);
  const [expanded, setExpanded] = useState<Record<string, boolean>>({ sops: true, circulars: true, minutes: true });
  const [filter, setFilter] = useState("");
  const [selected, setSelected] = useState<Record<string, boolean>>({});
  const [menu, setMenu] = useState<Menu>(null);
  const [dragging, setDragging] = useState(false);
  const [dropFolder, setDropFolder] = useState<string | null>(null);
  const [uploads, setUploads] = useState<Upload[]>([]);
  const [uploadDept, setUploadDept] = useState("");
  const [tab, setTab] = useState<"assistant" | "details">("assistant");
  const [docId, setDocId] = useState<string | null>(null);
  const [detail, setDetail] = useState<DocumentDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [assistantOpen, setAssistantOpen] = useState(true);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [draft, setDraft] = useState("");
  const [thinking, setThinking] = useState(false);
  const [mode, setMode] = useState<AskMode>("agent");
  const [scope, setScope] = useState<Scope>(null);
  const [modal, setModal] = useState<ModalState | null>(null);
  const [modalError, setModalError] = useState("");
  const [modalBusy, setModalBusy] = useState(false);
  const [vw, setVw] = useState(1440);

  const fileInput = useRef<HTMLInputElement>(null);
  const versionInput = useRef<HTMLInputElement>(null);
  const dragDocId = useRef<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const fail = useCallback(
    (error: unknown) => {
      if (error instanceof ApiError && error.status === 401) {
        clearSession();
        window.location.href = "/#login";
        return;
      }
      setToast(error instanceof Error ? error.message : String(error));
    },
    [],
  );

  const refresh = useCallback(async () => {
    try {
      const [folderList, docList] = await Promise.all([api.folders(), api.documents(200)]);
      setFolders(folderList);
      setDocs(docList.items);
      setLoaded(true);
    } catch (error) {
      fail(error);
    }
  }, [fail]);

  useEffect(() => {
    if (!getToken()) {
      router.replace("/#login");
      return;
    }
    let cancelled = false;
    api
      .me()
      .then((me) => {
        if (cancelled) return;
        setUser(me);
        const writable = me.departments.find((d) => d.role !== "viewer");
        setUploadDept(writable?.id ?? "");
        return refresh();
      })
      .catch(fail);
    return () => {
      cancelled = true;
    };
  }, [router, refresh, fail]);

  useEffect(() => {
    const onResize = () => setVw(window.innerWidth);
    const frame = window.requestAnimationFrame(() => {
      onResize();
      if (window.innerWidth < 1180) setAssistantOpen(false);
    });
    window.addEventListener("resize", onResize);
    return () => {
      window.cancelAnimationFrame(frame);
      window.removeEventListener("resize", onResize);
    };
  }, []);

  const busy = docs.some((d) => statusView(d.status).busy) || uploads.some((u) => u.phase !== "failed");
  useEffect(() => {
    if (!busy) return;
    const timer = window.setInterval(refresh, POLL_MS);
    return () => window.clearInterval(timer);
  }, [busy, refresh]);

  useEffect(() => {
    if (!toast) return;
    const timer = window.setTimeout(() => setToast(""), 5000);
    return () => window.clearTimeout(timer);
  }, [toast]);

  const loadDetail = useCallback(
    async (id: string) => {
      setDetailLoading(true);
      try {
        setDetail(await api.document(id));
      } catch (error) {
        if (error instanceof ApiError && error.status === 404) setDetail(null);
        else fail(error);
      } finally {
        setDetailLoading(false);
      }
    },
    [fail],
  );

  const docStatusKey = docId ? docs.find((d) => d.id === docId)?.status : undefined;
  useEffect(() => {
    if (!docId) return;
    let stale = false;
    api
      .document(docId)
      .then((d) => !stale && setDetail(d))
      .catch((error) => !stale && !(error instanceof ApiError && error.status === 404) && fail(error));
    return () => {
      stale = true;
    };
  }, [docId, docStatusKey, fail]);

  const folderMap = useMemo(() => new Map(folders.map((f) => [f.id, f])), [folders]);
  const docFolder = useCallback((d: DocumentSummary) => (d.folder_id && folderMap.has(d.folder_id) ? d.folder_id : INBOX), [folderMap]);
  const filesIn = useCallback(
    (id: string) => {
      if (id === ALL) return docs;
      const set = new Set(descendants(folders, id));
      return docs.filter((d) => set.has(docFolder(d)));
    },
    [docs, folders, docFolder],
  );
  const departmentName = useCallback(
    (id: string) => user?.departments.find((d) => d.id === id)?.name ?? id,
    [user],
  );
  const canWrite = useCallback((doc: DocumentSummary) => {
    const role = user?.departments.find((d) => d.id === doc.department_id)?.role;
    return role === "contributor" || role === "admin";
  }, [user]);
  const canManageFolders = !!user?.departments.some((d) => d.role !== "viewer");

  const open = (id: string) => {
    if (id !== ALL) {
      const next = { ...expanded };
      folderPath(folderMap, id).forEach((f) => (next[f.id] = true));
      setExpanded(next);
    }
    setCurrent(id);
    setSelected({});
    setMenu(null);
    setScope(null);
  };

  const openDocument = (id: string) => {
    const doc = docs.find((d) => d.id === id);
    if (doc) {
      const folder = docFolder(doc);
      const next = { ...expanded };
      folderPath(folderMap, folder).forEach((f) => (next[f.id] = true));
      setExpanded(next);
    }
    setDocId(id);
    setDetail(null);
    setTab("details");
    setAssistantOpen(true);
    setMenu(null);
    void loadDetail(id);
  };

  const onFiles = async (list: FileList | File[] | null, folderId?: string) => {
    const files = Array.from(list ?? []);
    setDragging(false);
    setDropFolder(null);
    if (!files.length) return;
    if (!uploadDept) {
      setToast("You have read-only access. Ask an administrator for contributor rights to upload.");
      return;
    }
    const target = folderId ?? (current === ALL ? INBOX : current);
    const created = files.map((file) => ({ key: nextKey("u"), name: file.name, folderId: target, progress: 0, phase: "uploading" as const, file }));
    setUploads((prev) => [...created.map((c) => ({ key: c.key, name: c.name, folderId: c.folderId, progress: c.progress, phase: c.phase })), ...prev].slice(0, 8));
    await Promise.all(
      created.map(async ({ key, file }) => {
        try {
          const response = await uploadDocument(file, uploadDept, target, (fraction) =>
            setUploads((prev) => prev.map((u) => (u.key === key ? { ...u, progress: Math.round(fraction * 100) } : u))),
          );
          setUploads((prev) =>
            prev.map((u) =>
              u.key === key ? { ...u, progress: 100, phase: "processing", documentId: response.document_id, duplicateOf: response.duplicate?.title } : u,
            ),
          );
          if (response.duplicate) setToast(`“${file.name}” is ${response.duplicate.tier === "exact" ? "an exact" : "a near"} duplicate of “${response.duplicate.title}”.`);
        } catch (error) {
          setUploads((prev) => prev.map((u) => (u.key === key ? { ...u, phase: "failed", error: error instanceof Error ? error.message : "Upload failed" } : u)));
          if (error instanceof ApiError && error.status === 401) fail(error);
        }
      }),
    );
    await refresh();
  };

  const onNewVersion = async (file: File | undefined) => {
    if (!file || !docId) return;
    const key = nextKey("v");
    const doc = docs.find((d) => d.id === docId);
    setUploads((prev) => [{ key, name: `${doc?.title ?? file.name} (new version)`, folderId: doc ? docFolder(doc) : INBOX, progress: 0, phase: "uploading" as const }, ...prev].slice(0, 8));
    try {
      await uploadVersion(docId, file, (fraction) => setUploads((prev) => prev.map((u) => (u.key === key ? { ...u, progress: Math.round(fraction * 100) } : u))));
      setUploads((prev) => prev.map((u) => (u.key === key ? { ...u, phase: "processing", documentId: docId } : u)));
      await refresh();
    } catch (error) {
      setUploads((prev) => prev.map((u) => (u.key === key ? { ...u, phase: "failed", error: error instanceof Error ? error.message : "Upload failed" } : u)));
    }
  };

  const moveDocs = async (ids: string[], folderId: string) => {
    try {
      await Promise.all(ids.map((id) => api.updateDocument(id, { folder_id: folderId })));
    } catch (error) {
      fail(error);
    }
    await refresh();
  };

  const openModal = (m: ModalState) => {
    setModal({ value: "", ...m });
    setModalError("");
    setMenu(null);
  };

  const confirm = async () => {
    if (!modal) return;
    const m = modal;
    const value = (m.value ?? "").trim();
    if (m.hasInput && !value) {
      setModalError("Enter a name.");
      return;
    }
    if (m.kind === "move" && !m.target) {
      setModalError("Choose a destination folder.");
      return;
    }
    setModalBusy(true);
    try {
      if (m.kind === "newFolder") {
        const folder = await api.createFolder(value, m.parent ?? null);
        if (m.parent) setExpanded((e) => ({ ...e, [m.parent!]: true }));
        setFolders((f) => [...f, folder]);
      } else if (m.kind === "renameFolder" && m.id) {
        await api.updateFolder(m.id, { name: value });
      } else if (m.kind === "renameFile" && m.id) {
        await api.updateDocument(m.id, { title: value });
        if (m.id === docId) void loadDetail(m.id);
      } else if (m.kind === "move" && m.ids && m.target) {
        await Promise.all(m.ids.map((id) => api.updateDocument(id, { folder_id: m.target! })));
        setSelected({});
      } else if (m.kind === "deleteFolder" && m.id) {
        const parent = folderMap.get(m.id)?.parent_id ?? null;
        const removed = new Set(descendants(folders, m.id));
        await api.deleteFolder(m.id);
        if (removed.has(current)) setCurrent(parent ?? ALL);
      } else if (m.kind === "deleteFiles" && m.ids) {
        await Promise.all(m.ids.map((id) => api.deleteDocument(id)));
        setSelected({});
        if (docId && m.ids.includes(docId)) {
          setDocId(null);
          setDetail(null);
        }
      }
      setModal(null);
      await refresh();
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) fail(error);
      else setModalError(error instanceof Error ? error.message : "Something went wrong.");
    } finally {
      setModalBusy(false);
    }
  };

  const renameFolder = (id: string) => {
    const f = folderMap.get(id);
    if (f) openModal({ kind: "renameFolder", id, value: f.name, title: "Rename folder", body: "Documents inside keep their place.", cta: "Rename", hasInput: true });
  };
  const deleteFolder = (id: string) => {
    const f = folderMap.get(id);
    if (!f) return;
    const n = filesIn(id).length;
    const sub = descendants(folders, id).length - 1;
    openModal({
      kind: "deleteFolder",
      id,
      title: "Delete folder",
      body: `“${f.name}”${sub ? ` and ${sub} subfolder${sub > 1 ? "s" : ""}` : ""} will be removed${n ? `, along with ${n} document${n > 1 ? "s" : ""}` : ""}. This can't be undone.`,
      cta: "Delete",
      danger: true,
    });
  };
  const moveFiles = (ids: string[]) =>
    openModal({ kind: "move", ids, target: null, title: ids.length > 1 ? `Move ${ids.length} documents` : "Move document", body: "Choose a destination folder.", cta: "Move here", isMove: true });
  const deleteFiles = (ids: string[]) =>
    openModal({ kind: "deleteFiles", ids, title: ids.length > 1 ? `Delete ${ids.length} documents` : "Delete document", body: "They will be removed from the library and the search index.", cta: "Delete", danger: true });
  const renameFile = (id: string) => {
    const d = docs.find((x) => x.id === id);
    if (d) openModal({ kind: "renameFile", id, value: d.title, title: "Rename document", body: "The reference number stays the same.", cta: "Rename", hasInput: true });
  };

  const scopeDocs = (): DocumentSummary[] => {
    if (scope?.ids) return docs.filter((d) => scope.ids!.includes(d.id));
    return filesIn(scope?.folder ?? current);
  };
  const scopeName = (): string => {
    if (scope?.ids) return scope.ids.length === 1 ? docs.find((d) => d.id === scope.ids![0])?.title ?? "1 document" : `${scope.ids.length} selected documents`;
    const id = scope?.folder ?? current;
    return id === ALL ? "Entire library" : pathLabel(folderMap, id);
  };
  const askWith = (next: Scope, question = "") => {
    abortRef.current?.abort();
    setScope(next);
    setTab("assistant");
    setAssistantOpen(true);
    setMenu(null);
    setMessages([]);
    setDraft(question);
  };

  const ask = async (raw: string) => {
    const question = raw.trim();
    if (!question || thinking) return;
    const inScope = scopeDocs();
    const wholeLibrary = !scope && current === ALL;
    const ready = inScope.filter((d) => d.status === "READY");
    const userMsg: ChatMessage = { id: nextKey("m"), role: "user", text: question, citations: [], steps: [], streaming: false, mode };
    const botId = nextKey("m");
    const history: ChatTurn[] = messages
      .filter((m) => m.text && !m.error)
      .slice(-12)
      .map((m) => ({ role: m.role === "user" ? "user" : "assistant", content: m.text }));
    setDraft("");
    if (!wholeLibrary && ready.length === 0) {
      setMessages((prev) => [...prev, userMsg, { id: botId, role: "bot", text: "There are no indexed documents in this scope yet.", citations: [], steps: [], streaming: false, mode }]);
      return;
    }
    const filters: SearchFilters | undefined = wholeLibrary ? undefined : { document_ids: ready.map((d) => d.id) };
    setMessages((prev) => [...prev, userMsg, { id: botId, role: "bot", text: "", citations: [], steps: [], streaming: true, mode }]);
    setThinking(true);
    const controller = new AbortController();
    abortRef.current = controller;
    const patch = (fn: (m: ChatMessage) => ChatMessage) => setMessages((prev) => prev.map((m) => (m.id === botId ? fn(m) : m)));
    try {
      await askStream(
        question,
        { mode, filters, history: mode === "agent" ? history : [], signal: controller.signal },
        {
          onToken: (text) => patch((m) => ({ ...m, text: m.text + text })),
          onStep: (step) => patch((m) => ({ ...m, text: "", steps: [...m.steps, step] })),
          onCitations: (citations) => patch((m) => ({ ...m, citations })),
          onError: (message) => patch((m) => ({ ...m, error: message })),
        },
      );
    } catch (error) {
      if (!(error instanceof DOMException && error.name === "AbortError")) {
        if (error instanceof ApiError && error.status === 401) fail(error);
        patch((m) => ({ ...m, error: error instanceof Error ? error.message : "The assistant is unavailable." }));
      }
    } finally {
      patch((m) => ({ ...m, streaming: false }));
      setThinking(false);
      abortRef.current = null;
    }
  };

  const signOut = () => {
    abortRef.current?.abort();
    clearSession();
    window.location.href = "/";
  };

  const q = filter.trim().toLowerCase();
  const currentFolder = current === ALL ? undefined : folderMap.get(current);

  const treeRows: { id: string; name: string; depth: number; kids: boolean }[] = [{ id: ALL, name: "All documents", depth: 0, kids: false }];
  const walk = (parent: string | null, depth: number) =>
    childrenOf(folders, parent).forEach((f) => {
      const kids = childrenOf(folders, f.id).length > 0;
      treeRows.push({ id: f.id, name: f.name, depth, kids });
      if (kids && expanded[f.id]) walk(f.id, depth + 1);
    });
  walk(null, 0);

  const dropOn = (id: string) => (e: DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDropFolder(null);
    setDragging(false);
    if (dragDocId.current) {
      const moving = dragDocId.current;
      dragDocId.current = null;
      void moveDocs(selected[moving] ? Object.keys(selected) : [moving], id);
    } else if (e.dataTransfer?.files?.length) {
      void onFiles(e.dataTransfer.files, id);
    }
  };

  const subfolders = childrenOf(folders, current === ALL ? null : current);

  let list = current !== ALL && !q ? docs.filter((d) => docFolder(d) === current) : filesIn(current);
  if (q) list = list.filter((d) => `${d.title} ${documentRef(d)} ${typeLabel(d.doctype)} ${d.original_filename ?? ""}`.toLowerCase().includes(q));
  list = [...list].sort((a, b) => (b.updated_at > a.updated_at ? 1 : -1));
  const pendingRows = uploads.filter((u) => u.phase === "uploading" && (current === ALL || u.folderId === current) && !q);
  const selIds = Object.keys(selected).filter((id) => docs.some((d) => d.id === id));
  const total = filesIn(current).length;

  const overlay = vw < 1180;
  const mainW = vw - (vw < 760 ? 24 : 240) - (assistantOpen && !overlay ? 392 : 0);
  const compact = mainW < 620;
  const tableCols = compact ? "28px minmax(0,1fr) 92px 28px" : "28px minmax(0,1fr) 96px 120px 110px 28px";
  const gridCols = vw < 760 ? "minmax(0,1fr)" : `216px minmax(0,1fr)${assistantOpen && !overlay ? " minmax(320px,380px)" : ""}`;

  const scoped = scopeDocs();
  const scopeReady = scoped.filter((d) => d.status === "READY").length;
  const lastBot = [...messages].reverse().find((m) => m.role === "bot");
  const lastStep = lastBot?.steps[lastBot.steps.length - 1];
  const thinkingLabel = lastStep ? `${stepLabel(lastStep)}…` : mode === "agent" ? "Planning research…" : `Searching ${scopeReady} documents…`;
  const suggestions =
    scope?.ids?.length === 1
      ? ["Summarise this document", "What actions or deadlines does it set?", "Who does this apply to?"]
      : ["What is the current policy on remote work?", "What changed in the latest procurement policy?", "How do I submit a claim and by when?"];

  const selectedDoc = docId ? docs.find((d) => d.id === docId) ?? null : null;
  const supersededTitle = (detail ?? selectedDoc)?.superseded_by ? docs.find((d) => d.id === (detail ?? selectedDoc)!.superseded_by)?.title ?? null : null;
  const visibleUploads = uploads.map((u) => {
    const doc = u.documentId ? docs.find((d) => d.id === u.documentId) : undefined;
    if (u.phase === "failed") return { ...u, label: "Failed", color: "#B42318", progress: 100 };
    if (u.phase === "uploading") return { ...u, label: `${u.progress}%`, color: "#1F6FE5" };
    if (u.duplicateOf) return { ...u, label: "Duplicate", color: "#2E7D5B", progress: 100 };
    const view = doc ? statusView(doc.status) : { label: "Processing", color: "#4A8DEC", busy: true };
    return { ...u, label: view.busy ? view.label : view.label === "Indexed" ? "Ready" : view.label, color: view.busy ? "#1F6FE5" : view.color, progress: 100 };
  });
  const upBusy = visibleUploads.filter((u) => u.label !== "Ready" && u.label !== "Failed" && u.label !== "Duplicate").length;

  const crumbs = [{ label: "Library", id: ALL }, ...(current === ALL ? [] : folderPath(folderMap, current).map((f) => ({ label: `/ ${f.name}`, id: f.id })))];
  const emptyText = !loaded
    ? "Loading library…"
    : q
      ? `No documents match “${filter}”.`
      : subfolders.length
        ? "No documents directly in this folder. Open a subfolder or upload here."
        : "This folder is empty. Drag files here or upload.";
  const writableDepts = user?.departments.filter((d) => d.role !== "viewer") ?? [];
  const uploadDeptName = writableDepts.find((d) => d.id === uploadDept)?.name;

  return (
    <div className="app-shell">
      <header style={{ display: "flex", alignItems: "center", gap: 24, padding: "14px 20px", borderBottom: "1px solid var(--line)", flexShrink: 0 }}>
        <button onClick={() => open(ALL)} className="link-btn" style={{ display: "flex", alignItems: "center", gap: 14 }}>
          <span style={{ fontWeight: 600, fontSize: 20, letterSpacing: "-.02em" }}>GOVSEARCH</span>
          <span style={{ fontSize: 9, lineHeight: 1.3, color: "var(--ink-2)", textTransform: "uppercase", letterSpacing: ".02em", textAlign: "left" }}>
            Agency
            <br />
            library
          </span>
        </button>
        <div style={{ flex: 1, maxWidth: 520, display: "flex", alignItems: "center", gap: 10, background: "rgba(255,255,255,.7)", border: "1px solid rgba(255,255,255,.95)", borderRadius: 999, padding: "9px 16px" }}>
          <span className="mono" style={{ fontSize: 11, color: "var(--ink-4)" }}>
            ⌕
          </span>
          <input
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && filter.trim() && list.length === 0) askWith(null, filter.trim());
            }}
            placeholder="Filter by name or reference"
            style={{ flex: 1, minWidth: 0, border: 0, background: "transparent", outline: "none", font: "inherit", fontSize: 13, color: "var(--ink)" }}
          />
        </div>
        <div className="caps" style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 18 }}>
          <button className="link-btn" onClick={() => setAssistantOpen(!assistantOpen)}>
            {assistantOpen ? "Hide assistant" : "Show assistant"}
          </button>
          {user && (
            <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
              <span style={{ width: 30, height: 30, borderRadius: "50%", background: "#C9D6EA", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 11, color: "#0B2A5C" }}>{initials(user.display_name)}</span>
              <span style={{ lineHeight: 1.3 }}>
                {user.display_name}
                <br />
                <span style={{ color: "var(--ink-3)", fontWeight: 500 }}>{user.departments.filter((d) => d.id !== "public").map((d) => d.name).join(" · ") || "Agency"}</span>
              </span>
            </div>
          )}
          <button className="link-btn" onClick={signOut}>
            [ Sign out ]
          </button>
        </div>
      </header>

      <input ref={fileInput} type="file" multiple accept=".pdf,.docx,.xlsx,.png,.jpg,.jpeg,application/pdf,image/png,image/jpeg,application/vnd.openxmlformats-officedocument.wordprocessingml.document,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" style={{ display: "none" }} onChange={(e) => { void onFiles(e.target.files); e.target.value = ""; }} />
      <input ref={versionInput} type="file" accept=".pdf,.docx,.xlsx,.png,.jpg,.jpeg,application/pdf,image/png,image/jpeg,application/vnd.openxmlformats-officedocument.wordprocessingml.document,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" style={{ display: "none" }} onChange={(e) => { void onNewVersion(e.target.files?.[0]); e.target.value = ""; }} />

      <div style={{ flex: 1, minHeight: 0, display: "grid", gridTemplateColumns: gridCols, gap: 12, padding: 12 }}>
        {vw >= 760 && (
          <aside style={{ minHeight: 0, display: "flex", flexDirection: "column", gap: 14, padding: "6px 4px", overflow: "auto" }}>
            <div style={{ display: "flex", gap: 8 }}>
              <button className="pill pill-primary" style={{ flex: 1, padding: 11 }} onClick={() => fileInput.current?.click()} disabled={!uploadDept}>
                ↑ Upload
              </button>
              <button
                className="pill pill-ghost"
                style={{ flex: 1, padding: 11 }}
                disabled={!canManageFolders}
                onClick={() =>
                  openModal({
                    kind: "newFolder",
                    parent: current === ALL ? null : current,
                    title: "New folder",
                    body: current === ALL ? "Creates a top-level folder in the library." : `Creates a folder inside ${currentFolder?.name}.`,
                    cta: "Create",
                    hasInput: true,
                  })
                }
              >
                + Folder
              </button>
            </div>
            {writableDepts.length > 1 && (
              <label className="mono" style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 10, color: "var(--ink-3)", padding: "0 6px" }}>
                UPLOAD AS
                <select value={uploadDept} onChange={(e) => setUploadDept(e.target.value)} style={{ flex: 1, minWidth: 0, border: "1px solid var(--line)", background: "rgba(255,255,255,.7)", borderRadius: 8, padding: "5px 6px", font: "inherit", fontSize: 11 }}>
                  {writableDepts.map((d) => (
                    <option key={d.id} value={d.id}>
                      {d.name}
                    </option>
                  ))}
                </select>
              </label>
            )}
            <div className="caps" style={{ color: "var(--ink-3)", padding: "8px 10px 0" }}>
              Library
            </div>
            <nav style={{ display: "flex", flexDirection: "column", gap: 2 }}>
              {treeRows.map((n) => (
                <div
                  key={n.id}
                  className={`tree-row${current === n.id ? " active" : ""}${dropFolder === n.id ? " drop" : ""}`}
                  style={{ paddingLeft: 10 + n.depth * 16 }}
                  onClick={() => open(n.id)}
                  onDragOver={(e) => {
                    if (n.id === ALL) return;
                    e.preventDefault();
                    if (dropFolder !== n.id) setDropFolder(n.id);
                  }}
                  onDragLeave={() => dropFolder === n.id && setDropFolder(null)}
                  onDrop={n.id === ALL ? (e) => e.preventDefault() : dropOn(n.id)}
                >
                  <span
                    className="mono"
                    style={{ width: 14, fontSize: 10, color: "var(--ink-4)", textAlign: "center" }}
                    onClick={(e) => {
                      if (!n.kids) return;
                      e.stopPropagation();
                      setExpanded({ ...expanded, [n.id]: !expanded[n.id] });
                    }}
                  >
                    {n.kids ? (expanded[n.id] ? "▾" : "▸") : ""}
                  </span>
                  <span className="ellipsis" style={{ flex: 1, minWidth: 0 }}>
                    {n.name}
                  </span>
                  <span className="mono" style={{ fontSize: 10, color: "var(--ink-4)" }}>
                    {filesIn(n.id).length}
                  </span>
                </div>
              ))}
            </nav>
          </aside>
        )}

        <main
          className="glass"
          style={{ position: "relative", minHeight: 0, display: "flex", flexDirection: "column", overflow: "hidden" }}
          onDragOver={(e) => {
            e.preventDefault();
            if (!dragDocId.current && e.dataTransfer?.types?.includes("Files") && !dragging) setDragging(true);
          }}
          onDragLeave={(e) => {
            if (!e.currentTarget.contains(e.relatedTarget as Node)) setDragging(false);
          }}
          onDrop={(e) => {
            e.preventDefault();
            dragDocId.current = null;
            setDragging(false);
            if (e.dataTransfer?.files?.length) void onFiles(e.dataTransfer.files);
          }}
        >
          {menu && <div onClick={() => setMenu(null)} style={{ position: "absolute", inset: 0, zIndex: 40 }} />}

          <div style={{ padding: "22px 26px 18px", display: "flex", flexDirection: "column", gap: 14, borderBottom: "1px solid rgba(21,23,28,.08)" }}>
            <div className="mono" style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 10, color: "var(--ink-3)", flexWrap: "wrap" }}>
              {crumbs.map((c) => (
                <button key={c.id} className="link-btn" style={{ color: "var(--ink-3)" }} onClick={() => open(c.id)}>
                  {c.label}
                </button>
              ))}
            </div>
            <div style={{ display: "flex", alignItems: "flex-end", justifyContent: "space-between", gap: 20, flexWrap: "wrap" }}>
              <h1 style={{ margin: 0, fontWeight: 400, fontSize: "clamp(24px,2.4vw,34px)", lineHeight: 1, textTransform: "uppercase", letterSpacing: "-.01em" }}>
                {current === ALL ? "All documents" : currentFolder?.name ?? ""}
              </h1>
              <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
                <span className="mono" style={{ fontSize: 10, color: "var(--ink-3)" }}>
                  {String(total).padStart(2, "0")} DOCUMENTS
                </span>
                {current !== ALL && (
                  <div className="caps" style={{ display: "flex", gap: 14 }}>
                    <button className="link-btn" onClick={() => askWith({ folder: current })}>
                      Ask
                    </button>
                    {canManageFolders && current !== INBOX && (
                      <>
                        <button className="link-btn" onClick={() => renameFolder(current)}>
                          Rename
                        </button>
                        <button className="link-btn danger" onClick={() => deleteFolder(current)}>
                          Delete
                        </button>
                      </>
                    )}
                  </div>
                )}
              </div>
            </div>
          </div>

          <div style={{ flex: 1, minHeight: 0, overflow: "auto", padding: "20px 26px 90px", display: "flex", flexDirection: "column", gap: 22 }}>
            {subfolders.length > 0 && !q && (
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill,minmax(150px,1fr))", gap: 12 }}>
                {subfolders.map((f) => {
                  const root = rootOf(folderMap, f.id) ?? "";
                  const [bg, ink] = typeColors(ROOT_TYPE[root] ?? "DOCUMENT");
                  const isMenu = menu?.kind === "folder" && menu.id === f.id;
                  return (
                    <div
                      key={f.id}
                      style={{ position: "relative", paddingTop: 10, outline: dropFolder === f.id ? "2px dashed var(--blue)" : undefined, borderRadius: 12 }}
                      onDragOver={(e) => {
                        e.preventDefault();
                        if (dropFolder !== f.id) setDropFolder(f.id);
                      }}
                      onDragLeave={() => dropFolder === f.id && setDropFolder(null)}
                      onDrop={dropOn(f.id)}
                    >
                      <div style={{ position: "absolute", left: 0, top: 0, width: "46%", height: 16, borderRadius: "9px 9px 0 0", background: bg }} />
                      <div className="folder-card" style={{ background: bg, color: ink }} onClick={() => open(f.id)}>
                        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                          <span className="mono" style={{ fontSize: 10, opacity: 0.8 }}>
                            {String(filesIn(f.id).length).padStart(2, "0")}
                          </span>
                          <button
                            onClick={(e) => {
                              e.stopPropagation();
                              setMenu(isMenu ? null : { kind: "folder", id: f.id });
                            }}
                            style={{ background: "none", border: 0, padding: "0 2px", fontSize: 14, lineHeight: 1, color: "inherit", cursor: "pointer", opacity: 0.7 }}
                          >
                            ⋯
                          </button>
                        </div>
                        <span style={{ fontSize: 13, fontWeight: 500, lineHeight: 1.25 }}>{f.name}</span>
                      </div>
                      {isMenu && (
                        <div className="menu" style={{ right: 6, top: 40, minWidth: 140 }}>
                          <button onClick={() => askWith({ folder: f.id })}>Ask about this folder</button>
                          {canManageFolders && f.id !== INBOX && (
                            <>
                              <button onClick={() => renameFolder(f.id)}>Rename</button>
                              <button className="danger" onClick={() => deleteFolder(f.id)}>
                                Delete
                              </button>
                            </>
                          )}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            )}

            <div style={{ display: "flex", flexDirection: "column" }}>
              <div className="caps" style={{ display: "grid", gridTemplateColumns: tableCols, gap: 12, alignItems: "center", padding: "0 10px 10px", borderBottom: "1px solid rgba(21,23,28,.1)", color: "var(--ink-3)" }}>
                <input
                  type="checkbox"
                  checked={list.length > 0 && list.every((d) => selected[d.id])}
                  onChange={() => {
                    const all = list.length > 0 && list.every((d) => selected[d.id]);
                    setSelected(all ? {} : Object.fromEntries(list.map((d) => [d.id, true])));
                  }}
                  style={{ accentColor: "var(--blue)", width: 15, height: 15, margin: 0 }}
                />
                <span>Document</span>
                {!compact && <span>Type</span>}
                {!compact && <span>Updated</span>}
                <span>Status</span>
                <span />
              </div>

              {pendingRows.map((u) => (
                <div key={u.key} className="doc-row" style={{ gridTemplateColumns: tableCols, cursor: "default" }}>
                  <span />
                  <div style={{ minWidth: 0, display: "flex", flexDirection: "column", gap: 3 }}>
                    <span className="ellipsis" style={{ fontSize: 13, fontWeight: 500 }}>
                      {u.name}
                    </span>
                    <span className="mono ellipsis" style={{ fontSize: 10, color: "var(--ink-3)" }}>
                      Uploading to {pathLabel(folderMap, u.folderId)}
                      {uploadDeptName ? ` · ${uploadDeptName}` : ""}
                    </span>
                  </div>
                  {!compact && <span />}
                  {!compact && <span />}
                  <span className="mono" style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 10, color: "var(--blue)" }}>
                    <span style={{ width: 6, height: 6, borderRadius: "50%", background: "var(--blue)" }} />
                    Uploading {u.progress}%
                  </span>
                  <span />
                  <div style={{ position: "absolute", left: 50, right: 10, bottom: 0, height: 2, background: "rgba(31,111,229,.15)", borderRadius: 2 }}>
                    <div style={{ height: "100%", width: `${u.progress}%`, background: "var(--blue)", borderRadius: 2 }} />
                  </div>
                </div>
              ))}

              {list.map((d) => {
                const label = typeLabel(d.doctype);
                const [typeBg, typeInk] = typeColors(label);
                const status = statusView(d.status);
                const isMenu = menu?.kind === "file" && menu.id === d.id;
                const folder = docFolder(d);
                const where = current === ALL || q || folder !== current ? ` · ${pathLabel(folderMap, folder)}` : "";
                const writable = canWrite(d);
                return (
                  <div
                    key={d.id}
                    className="doc-row"
                    draggable={writable}
                    onDragStart={(e) => {
                      dragDocId.current = d.id;
                      e.dataTransfer.effectAllowed = "move";
                      e.dataTransfer.setData("text/plain", d.id);
                    }}
                    onDragEnd={() => {
                      dragDocId.current = null;
                      setDropFolder(null);
                    }}
                    onClick={() => openDocument(d.id)}
                    style={{ gridTemplateColumns: tableCols, background: docId === d.id ? "rgba(220,232,250,.7)" : selected[d.id] ? "rgba(255,255,255,.6)" : "transparent" }}
                  >
                    <input
                      type="checkbox"
                      checked={!!selected[d.id]}
                      onClick={(e) => e.stopPropagation()}
                      onChange={() => {
                        const next = { ...selected };
                        if (next[d.id]) delete next[d.id];
                        else next[d.id] = true;
                        setSelected(next);
                      }}
                      style={{ accentColor: "var(--blue)", width: 15, height: 15, margin: 0 }}
                    />
                    <div style={{ minWidth: 0, display: "flex", flexDirection: "column", gap: 3 }}>
                      <span className="ellipsis" style={{ fontSize: 13, fontWeight: 500 }}>
                        {d.title}
                        {d.superseded_by && (
                          <span className="mono" style={{ marginLeft: 8, fontSize: 9, color: "var(--red)", fontWeight: 400 }}>
                            SUPERSEDED
                          </span>
                        )}
                      </span>
                      <span className="mono ellipsis" style={{ fontSize: 10, color: "var(--ink-3)" }}>
                        {documentRef(d)}
                        {where}
                      </span>
                    </div>
                    {!compact && (
                      <span className="mono" style={{ justifySelf: "start", fontSize: 9, letterSpacing: ".06em", padding: "3px 8px", borderRadius: 999, background: typeBg, color: typeInk }}>
                        {label}
                      </span>
                    )}
                    {!compact && (
                      <span className="mono" style={{ fontSize: 11, color: "var(--ink-2)" }}>
                        {fmtDate(d.updated_at)}
                      </span>
                    )}
                    <span className="mono" style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 10, color: status.color }}>
                      {status.busy ? <span className="spinner" style={{ width: 8, height: 8 }} /> : <span style={{ width: 6, height: 6, borderRadius: "50%", background: status.color }} />}
                      {status.label}
                    </span>
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        setMenu(isMenu ? null : { kind: "file", id: d.id });
                      }}
                      style={{ background: "none", border: 0, padding: 0, fontSize: 15, color: "var(--ink-3)", cursor: "pointer" }}
                    >
                      ⋯
                    </button>
                    {isMenu && (
                      <div className="menu" style={{ right: 10, top: 38 }} onClick={(e) => e.stopPropagation()}>
                        <button onClick={() => askWith({ ids: [d.id] })}>Ask about this</button>
                        <button onClick={() => openDocument(d.id)}>Details</button>
                        {writable && (
                          <>
                            <button onClick={() => renameFile(d.id)}>Rename</button>
                            <button onClick={() => moveFiles([d.id])}>Move to…</button>
                            <button className="danger" onClick={() => deleteFiles([d.id])}>
                              Delete
                            </button>
                          </>
                        )}
                      </div>
                    )}
                  </div>
                );
              })}

              {list.length === 0 && pendingRows.length === 0 && (
                <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 14, padding: "56px 20px", textAlign: "center" }}>
                  <span style={{ fontSize: 13, color: "var(--ink-2)" }}>{emptyText}</span>
                  {loaded && q && (
                    <button className="pill pill-ghost" onClick={() => askWith(null, filter.trim())}>
                      Ask the assistant instead
                    </button>
                  )}
                  {loaded && !q && uploadDept && (
                    <button className="pill pill-ghost" onClick={() => fileInput.current?.click()}>
                      Upload files
                    </button>
                  )}
                </div>
              )}
            </div>
          </div>

          {selIds.length > 0 && (
            <div
              className="caps"
              style={{ position: "absolute", left: "50%", bottom: 20, transform: "translateX(-50%)", display: "flex", alignItems: "center", gap: 18, background: "var(--ink)", color: "#fff", borderRadius: 999, padding: "10px 12px 10px 20px", boxShadow: "0 20px 40px rgba(20,30,60,.25)", whiteSpace: "nowrap", zIndex: 30 }}
            >
              <span className="mono" style={{ fontWeight: 400 }}>
                {selIds.length} selected
              </span>
              <button className="link-btn" style={{ color: "var(--blue-soft)" }} onClick={() => askWith({ ids: selIds })}>
                Ask assistant
              </button>
              <button className="link-btn" style={{ color: "#fff" }} onClick={() => moveFiles(selIds.filter((id) => { const d = docs.find((x) => x.id === id); return d && canWrite(d); }))}>
                Move
              </button>
              <button className="link-btn" style={{ color: "#fff" }} onClick={() => deleteFiles(selIds.filter((id) => { const d = docs.find((x) => x.id === id); return d && canWrite(d); }))}>
                Delete
              </button>
              <button onClick={() => setSelected({})} style={{ border: 0, borderRadius: 999, background: "rgba(255,255,255,.12)", color: "#fff", padding: "7px 12px", font: "inherit", letterSpacing: "inherit", cursor: "pointer" }}>
                Clear
              </button>
            </div>
          )}

          {dragging && (
            <div style={{ position: "absolute", inset: 10, zIndex: 45, border: "2px dashed var(--blue)", borderRadius: 18, background: "rgba(220,232,250,.85)", display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 10, pointerEvents: "none" }}>
              <span style={{ fontWeight: 400, fontSize: 26, textTransform: "uppercase" }}>Drop to upload</span>
              <span className="mono" style={{ fontSize: 11, color: "var(--blue-deep)" }}>
                into {current === ALL ? "Inbox" : currentFolder?.name}
                {uploadDeptName ? ` · as ${uploadDeptName}` : ""}
              </span>
            </div>
          )}

          {visibleUploads.length > 0 && (
            <div style={{ position: "absolute", right: 16, bottom: 16, width: 300, background: "rgba(255,255,255,.95)", borderRadius: 16, boxShadow: "0 20px 50px rgba(20,30,60,.16)", padding: 14, zIndex: 35, display: "flex", flexDirection: "column", gap: 10 }}>
              <div className="caps" style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <span>{upBusy ? `Processing ${upBusy} of ${visibleUploads.length}` : `${visibleUploads.length} uploaded`}</span>
                <button className="link-btn" style={{ color: "var(--ink-3)" }} onClick={() => setUploads([])}>
                  Close
                </button>
              </div>
              {visibleUploads.map((u) => (
                <div key={u.key} style={{ display: "flex", flexDirection: "column", gap: 5 }} title={u.error ?? u.duplicateOf ?? ""}>
                  <div style={{ display: "flex", justifyContent: "space-between", gap: 10, fontSize: 12 }}>
                    <span className="ellipsis">{u.name}</span>
                    <span className="mono" style={{ fontSize: 10, color: u.color, flexShrink: 0 }}>
                      {u.label}
                    </span>
                  </div>
                  <div style={{ height: 3, background: "#E6EAF0", borderRadius: 3 }}>
                    <div style={{ height: "100%", width: `${u.progress}%`, background: u.color, borderRadius: 3, animation: u.label !== "Ready" && u.phase === "processing" ? "pulse 1.2s infinite" : undefined }} />
                  </div>
                </div>
              ))}
            </div>
          )}

          {toast && (
            <div style={{ position: "absolute", left: 16, bottom: 16, maxWidth: 420, background: "var(--ink)", color: "#fff", borderRadius: 14, padding: "10px 14px", fontSize: 12, lineHeight: 1.4, zIndex: 36, boxShadow: "0 20px 40px rgba(20,30,60,.25)" }} onClick={() => setToast("")}>
              {toast}
            </div>
          )}
        </main>

        {overlay && assistantOpen && <div onClick={() => setAssistantOpen(false)} style={{ position: "fixed", inset: 0, zIndex: 54, background: "rgba(30,34,42,.18)" }} />}
        {assistantOpen && (
          <aside
            className="glass"
            style={{
              minHeight: 0,
              display: "flex",
              flexDirection: "column",
              overflow: "hidden",
              background: "rgba(248,249,251,.82)",
              ...(overlay ? { position: "fixed", top: 64, right: 12, bottom: 12, width: "min(400px,calc(100vw - 24px))", zIndex: 55, background: "#F6F7F9", boxShadow: "0 30px 80px rgba(20,30,60,.25)" } : {}),
            }}
          >
            <div style={{ display: "flex", gap: 4, padding: 10, borderBottom: "1px solid rgba(21,23,28,.08)" }}>
              {(["assistant", "details"] as const).map((t) => (
                <button
                  key={t}
                  className="pill"
                  onClick={() => setTab(t)}
                  style={{ flex: 1, border: 0, padding: 9, background: tab === t ? "var(--ink)" : "transparent", color: tab === t ? "#fff" : "var(--ink)" }}
                >
                  {t === "assistant" ? "Assistant" : "Details"}
                </button>
              ))}
            </div>
            {tab === "assistant" ? (
              <AssistantPanel
                scopeLabel={`IN SCOPE: ${scopeName()} · ${scoped.length}`}
                messages={messages}
                thinking={thinking}
                thinkingLabel={thinkingLabel}
                draft={draft}
                mode={mode}
                suggestions={suggestions}
                citeColors={(id) => typeColors(typeLabel(docs.find((d) => d.id === id)?.doctype))}
                onDraft={setDraft}
                onAsk={(text) => void ask(text)}
                onStop={() => abortRef.current?.abort()}
                onMode={setMode}
                onNewChat={() => {
                  abortRef.current?.abort();
                  setMessages([]);
                  setScope(null);
                  setDraft("");
                }}
                onOpenDocument={openDocument}
              />
            ) : (
              <DetailsPanel
                doc={detail && detail.id === docId ? detail : null}
                summary={selectedDoc}
                loading={detailLoading}
                folderLabel={selectedDoc ? pathLabel(folderMap, docFolder(selectedDoc)) : ""}
                departmentName={selectedDoc ? departmentName(selectedDoc.department_id) : ""}
                canWrite={!!selectedDoc && canWrite(selectedDoc)}
                supersededTitle={supersededTitle}
                onAsk={() => docId && askWith({ ids: [docId] })}
                onMove={() => docId && moveFiles([docId])}
                onRename={() => docId && renameFile(docId)}
                onDelete={() => docId && deleteFiles([docId])}
                onNewVersion={() => versionInput.current?.click()}
                onDownload={async () => {
                  if (!docId) return;
                  try {
                    const blob = await api.downloadFile(docId);
                    const url = URL.createObjectURL(blob);
                    const a = document.createElement("a");
                    a.href = url;
                    a.download = selectedDoc?.original_filename || detail?.original_filename || "document";
                    a.click();
                    setTimeout(() => URL.revokeObjectURL(url), 2000);
                  } catch (error) {
                    fail(error);
                  }
                }}
                onOpenDocument={openDocument}
              />
            )}
          </aside>
        )}
      </div>

      {modal && (
        <Modal modal={modal} error={modalError} busy={modalBusy} folders={folders} onChange={(m) => { setModal(m); setModalError(""); }} onClose={() => setModal(null)} onConfirm={() => void confirm()} />
      )}
    </div>
  );
}
