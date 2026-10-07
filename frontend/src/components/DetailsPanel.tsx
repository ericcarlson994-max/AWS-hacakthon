"use client";

import type { DocumentDetail, DocumentSummary } from "@/lib/types";
import { documentRef, fmtDate, fmtSize, statusView, typeColors, typeLabel } from "@/lib/format";

type Props = {
  doc: DocumentDetail | null;
  summary: DocumentSummary | null;
  loading: boolean;
  folderLabel: string;
  departmentName: string;
  canWrite: boolean;
  supersededTitle: string | null;
  onAsk: () => void;
  onMove: () => void;
  onRename: () => void;
  onDelete: () => void;
  onDownload: () => void;
  onNewVersion: () => void;
  onOpenDocument: (id: string) => void;
};

export function DetailsPanel(props: Props) {
  const base = props.doc ?? props.summary;
  if (!base) {
    return (
      <div style={{ flex: 1, minHeight: 0, overflow: "auto", padding: 20 }}>
        <p style={{ margin: 0, fontSize: 13, color: "var(--ink-3)" }}>Select a document to see its summary and details.</p>
      </div>
    );
  }
  const label = typeLabel(base.doctype);
  const [bg, ink] = typeColors(label);
  const status = statusView(base.status);
  const detail = props.doc;
  const latest = detail?.versions?.length ? detail.versions[detail.versions.length - 1] : null;

  return (
    <div style={{ flex: 1, minHeight: 0, overflow: "auto", padding: 20, display: "flex", flexDirection: "column", gap: 18 }}>
      <div
        style={{ borderRadius: 18, padding: 18, minHeight: 150, display: "flex", flexDirection: "column", justifyContent: "space-between", gap: 16, background: `linear-gradient(160deg,rgba(255,255,255,.35),rgba(255,255,255,0) 55%),${bg}`, color: ink, boxShadow: "0 14px 28px rgba(20,40,90,.18)" }}
      >
        <div style={{ display: "flex", justifyContent: "space-between" }}>
          <span className="mono" style={{ fontSize: 9, letterSpacing: ".06em", padding: "3px 8px", borderRadius: 999, background: "rgba(255,255,255,.25)" }}>
            {label}
          </span>
          <span className="mono" style={{ fontSize: 10 }}>
            {fmtSize(base.size_bytes)}
          </span>
        </div>
        <div style={{ fontSize: 17, fontWeight: 500, lineHeight: 1.3 }}>{base.title}</div>
        <div className="mono" style={{ fontSize: 10, opacity: 0.9 }}>
          {documentRef(base)}
          {base.meta?.effective_date ? ` · effective ${fmtDate(base.meta.effective_date)}` : ""}
        </div>
      </div>

      {base.superseded_by && (
        <button
          onClick={() => props.onOpenDocument(base.superseded_by!)}
          style={{ textAlign: "left", border: "1px solid rgba(180,35,24,.25)", background: "#FDF2F1", color: "var(--red)", borderRadius: 12, padding: "10px 12px", font: "inherit", fontSize: 12, cursor: "pointer" }}
        >
          Superseded by {props.supersededTitle ? `“${props.supersededTitle}”` : "a newer document"} →
        </button>
      )}
      {detail?.duplicate && (
        <button
          onClick={() => props.onOpenDocument(detail.duplicate!.document_id)}
          style={{ textAlign: "left", border: "1px solid rgba(31,111,229,.25)", background: "#EEF4FD", color: "var(--blue-deep)", borderRadius: 12, padding: "10px 12px", font: "inherit", fontSize: 12, cursor: "pointer" }}
        >
          {detail.duplicate.tier === "exact" ? "Exact" : "Near"} duplicate of “{detail.duplicate.title}” →
        </button>
      )}

      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        <span className="caps" style={{ color: "var(--ink-3)" }}>
          Summary
        </span>
        {props.loading && !detail ? (
          <span className="mono" style={{ fontSize: 10, color: "var(--blue)", animation: "pulse 1.2s infinite" }}>
            Loading…
          </span>
        ) : (
          <p style={{ margin: 0, fontSize: 13, lineHeight: 1.55, color: "var(--ink)" }}>
            {detail?.root_summary || (status.busy ? "A summary will appear once indexing completes." : "No summary available.")}
          </p>
        )}
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "auto 1fr", gap: "8px 16px", fontSize: 12 }}>
        <span style={{ color: "var(--ink-3)" }}>Folder</span>
        <span>{props.folderLabel}</span>
        <span style={{ color: "var(--ink-3)" }}>Owner</span>
        <span>{props.departmentName}</span>
        <span style={{ color: "var(--ink-3)" }}>Updated</span>
        <span className="mono" style={{ fontSize: 11 }}>
          {fmtDate(base.updated_at)}
        </span>
        <span style={{ color: "var(--ink-3)" }}>Status</span>
        <span style={{ color: status.color }}>
          {status.label}
          {base.status === "FAILED" && detail?.status_detail ? ` — ${detail.status_detail}` : ""}
        </span>
        {base.page_count ? (
          <>
            <span style={{ color: "var(--ink-3)" }}>Pages</span>
            <span className="mono" style={{ fontSize: 11 }}>
              {base.page_count}
            </span>
          </>
        ) : null}
        {base.meta?.language ? (
          <>
            <span style={{ color: "var(--ink-3)" }}>Language</span>
            <span className="mono" style={{ fontSize: 11 }}>
              {base.meta.language.toUpperCase()}
            </span>
          </>
        ) : null}
        <span style={{ color: "var(--ink-3)" }}>Version</span>
        <span className="mono" style={{ fontSize: 11 }}>
          v{base.current_version_no ?? 1}
          {latest?.delta_stats ? ` · ${latest.delta_stats.reused} reused, ${latest.delta_stats.reembedded} re-embedded` : ""}
        </span>
      </div>

      {base.tags.length > 0 && (
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
          {base.tags.map((t) => (
            <span
              key={t.id}
              className="mono"
              style={{ fontSize: 9, letterSpacing: ".06em", padding: "4px 9px", borderRadius: 999, background: t.status === "confirmed" ? "#CDDEF6" : "rgba(255,255,255,.7)", border: "1px solid rgba(21,23,28,.08)", color: "var(--ink-2)" }}
            >
              {t.name.toUpperCase()}
              {t.source === "ai" && t.status === "suggested" ? " · AI" : ""}
            </span>
          ))}
        </div>
      )}

      {detail && detail.versions.length > 1 && (
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          <span className="caps" style={{ color: "var(--ink-3)" }}>
            Versions
          </span>
          {[...detail.versions].reverse().map((v) => (
            <div key={v.version_no} className="mono" style={{ display: "flex", justifyContent: "space-between", gap: 10, fontSize: 10, color: "var(--ink-2)" }}>
              <span className="ellipsis">
                v{v.version_no} · {v.original_filename}
              </span>
              <span style={{ flexShrink: 0 }}>{fmtDate(v.created_at)}</span>
            </div>
          ))}
        </div>
      )}

      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        <button className="pill pill-primary" onClick={props.onAsk}>
          Ask about this
        </button>
        <button className="pill pill-ghost" onClick={props.onDownload}>
          Download
        </button>
        {props.canWrite && (
          <>
            <button className="pill pill-ghost" onClick={props.onNewVersion}>
              New version
            </button>
            <button className="pill pill-ghost" onClick={props.onMove}>
              Move
            </button>
            <button className="pill pill-ghost" onClick={props.onRename}>
              Rename
            </button>
            <button className="pill pill-ghost" style={{ color: "var(--red)" }} onClick={props.onDelete}>
              Delete
            </button>
          </>
        )}
      </div>
    </div>
  );
}
