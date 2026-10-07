"use client";

import { useEffect, useRef, type CSSProperties, type FormEvent, type KeyboardEvent } from "react";
import { Markdown } from "./Markdown";
import type { AgentStep, AskMode, Citation } from "@/lib/types";

export type ChatMessage = {
  id: string;
  role: "user" | "bot";
  text: string;
  citations: Citation[];
  steps: AgentStep[];
  streaming: boolean;
  mode: AskMode;
  error?: string;
};

type Props = {
  scopeLabel: string;
  messages: ChatMessage[];
  thinking: boolean;
  thinkingLabel: string;
  draft: string;
  mode: AskMode;
  suggestions: string[];
  citeColors: (documentId: string) => [string, string];
  onDraft: (value: string) => void;
  onAsk: (question: string) => void;
  onStop: () => void;
  onMode: (mode: AskMode) => void;
  onNewChat: () => void;
  onOpenDocument: (documentId: string) => void;
};

const PLURAL: Record<string, string> = {
  policy: "policies",
  sop: "SOPs",
  circular: "circulars",
  guideline: "guidelines",
  report: "reports",
  minutes: "minutes",
  other: "other documents",
};

const plural = (doctype: unknown) => PLURAL[String(doctype)] ?? `${String(doctype)}s`;

export function stepLabel(step: AgentStep): string {
  const input = step.input || {};
  const quoted = (v: unknown) => `“${String(v)}”`;
  switch (step.tool) {
    case "search_documents":
      return `Searched ${quoted(input.query ?? "")}${input.doctype ? ` in ${plural(input.doctype)}` : ""}`;
    case "get_document":
      return "Read document details";
    case "get_document_versions":
      return "Compared versions";
    case "list_documents":
      return `Listed ${input.doctype ? plural(input.doctype) : "documents"}`;
    case "rag_fallback":
      return "Quick answer (agent unavailable)";
    default:
      return step.tool;
  }
}

const STEP_ICON: Record<string, string> = {
  search_documents: "⌕",
  get_document: "▤",
  get_document_versions: "⟲",
  list_documents: "☰",
  rag_fallback: "·",
};

function kicker(message: ChatMessage): string {
  if (message.error) return "ERROR";
  const docs = new Set(message.citations.map((c) => c.document_id)).size;
  if (message.streaming) return message.mode === "agent" ? "AGENT · WORKING" : "ANSWERING";
  if (docs) return `ANSWER · ${docs} SOURCE${docs > 1 ? "S" : ""}${message.mode === "agent" ? ` · ${message.steps.length} STEP${message.steps.length === 1 ? "" : "S"}` : ""}`;
  return "NO SOURCES FOUND";
}

export function AssistantPanel(props: Props) {
  const { messages, thinking } = props;
  const chatRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = chatRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages, thinking]);

  const send = (e: FormEvent) => {
    e.preventDefault();
    props.onAsk(props.draft);
  };
  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      props.onAsk(props.draft);
    }
  };
  const modeBtn = (mode: AskMode): CSSProperties => ({
    border: 0,
    borderRadius: 999,
    padding: "5px 10px",
    font: "inherit",
    letterSpacing: "inherit",
    cursor: "pointer",
    background: props.mode === mode ? "var(--ink)" : "transparent",
    color: props.mode === mode ? "#fff" : "var(--ink)",
  });

  return (
    <div style={{ flex: 1, minHeight: 0, display: "flex", flexDirection: "column" }}>
      <div style={{ padding: "16px 20px 12px", display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12 }}>
        <div style={{ display: "flex", flexDirection: "column", gap: 4, minWidth: 0 }}>
          <span style={{ fontSize: 20, fontWeight: 400, textTransform: "uppercase" }}>Ask GovSearch</span>
          <span className="mono ellipsis" style={{ fontSize: 10, color: "var(--blue)" }}>
            {props.scopeLabel}
          </span>
        </div>
        <button className="link-btn caps" style={{ flexShrink: 0 }} onClick={props.onNewChat}>
          [ New chat ]
        </button>
      </div>
      <div style={{ padding: "0 20px 10px", display: "flex", alignItems: "center", gap: 8 }}>
        <div className="caps" style={{ display: "flex", gap: 2, background: "rgba(255,255,255,.6)", borderRadius: 999, padding: 3 }}>
          <button type="button" style={modeBtn("rag")} onClick={() => props.onMode("rag")} title="One search, fast answer">
            Quick
          </button>
          <button type="button" style={modeBtn("agent")} onClick={() => props.onMode("agent")} title="Research agent: plans, runs several searches, compares versions">
            Research agent
          </button>
        </div>
        <span className="mono" style={{ fontSize: 9, color: "var(--ink-3)" }}>
          {props.mode === "agent" ? "multi-step · ~10s" : "single search · ~3s"}
        </span>
      </div>
      <div ref={chatRef} style={{ flex: 1, minHeight: 0, overflow: "auto", padding: "4px 20px 16px", display: "flex", flexDirection: "column", gap: 16 }}>
        {messages.length === 0 && !thinking && (
          <div style={{ display: "flex", flexDirection: "column", gap: 10, paddingTop: 8 }}>
            <p style={{ margin: "0 0 6px", fontSize: 13, lineHeight: 1.5, color: "var(--ink-2)" }}>
              Ask a question in English, Bahasa Melayu or 中文. Answers come only from documents in scope, with sources.
            </p>
            {props.suggestions.map((text) => (
              <button key={text} className="suggestion" onClick={() => props.onAsk(text)}>
                {text}
              </button>
            ))}
          </div>
        )}
        {messages.map((m) =>
          m.role === "user" ? (
            <div key={m.id} style={{ alignSelf: "flex-end", maxWidth: "85%", background: "var(--ink)", color: "#fff", borderRadius: "16px 16px 4px 16px", padding: "10px 14px", fontSize: 13, lineHeight: 1.45, whiteSpace: "pre-wrap" }}>
              {m.text}
            </div>
          ) : (
            <div key={m.id} style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              <div className="mono" style={{ fontSize: 9, letterSpacing: ".06em", color: m.error ? "var(--red)" : "var(--blue)" }}>
                {kicker(m)}
              </div>
              {m.steps.length > 0 && (
                <div style={{ display: "flex", flexDirection: "column", gap: 4, borderLeft: "2px solid rgba(31,111,229,.25)", paddingLeft: 10 }}>
                  {m.steps.map((s, i) => (
                    <span key={i} className="mono ellipsis" style={{ fontSize: 10, color: "var(--ink-3)" }}>
                      <span style={{ color: "var(--blue)", marginRight: 6 }}>{STEP_ICON[s.tool] ?? "·"}</span>
                      {stepLabel(s)}
                    </span>
                  ))}
                </div>
              )}
              {m.text && (
                <div style={{ fontSize: 14, lineHeight: 1.55, color: "var(--ink)" }}>
                  <Markdown
                    text={m.text}
                    onCite={(n) => {
                      const c = m.citations.find((x) => x.n === n);
                      if (c) props.onOpenDocument(c.document_id);
                    }}
                  />
                </div>
              )}
              {m.error && <div style={{ fontSize: 13, color: "var(--red)" }}>{m.error}</div>}
              {m.citations.length > 0 && (
                <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                  {m.citations.map((c) => {
                    const [bg, ink] = props.citeColors(c.document_id);
                    return (
                      <button key={`${c.n}-${c.chunk_id}`} className="cite-btn" style={{ background: bg, color: ink }} onClick={() => props.onOpenDocument(c.document_id)} title={c.quote}>
                        <span className="mono" style={{ fontSize: 10, opacity: 0.85 }}>
                          [{c.n}]
                        </span>
                        <span style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column", gap: 2 }}>
                          <span className="ellipsis" style={{ fontSize: 12, fontWeight: 500 }}>
                            {c.title}
                          </span>
                          <span className="mono ellipsis" style={{ fontSize: 9, opacity: 0.85 }}>
                            {c.page ? `p.${c.page} · ` : ""}
                            {c.quote.replace(/\s+/g, " ").slice(0, 80)}
                          </span>
                        </span>
                      </button>
                    );
                  })}
                </div>
              )}
            </div>
          ),
        )}
        {thinking && (
          <div className="mono" style={{ display: "flex", alignItems: "center", gap: 10, fontSize: 10, color: "var(--blue)" }}>
            <span className="spinner" />
            <span className="ellipsis">{props.thinkingLabel}</span>
            <button className="link-btn caps" style={{ marginLeft: "auto", color: "var(--ink-3)" }} onClick={props.onStop}>
              Stop
            </button>
          </div>
        )}
      </div>
      <form onSubmit={send} style={{ margin: "0 14px 14px", display: "flex", alignItems: "flex-end", gap: 8, background: "#fff", border: "1px solid rgba(21,23,28,.1)", borderRadius: 20, padding: "8px 8px 8px 16px" }}>
        <textarea
          value={props.draft}
          onChange={(e) => props.onDraft(e.target.value)}
          onKeyDown={onKey}
          rows={2}
          placeholder="Ask about these documents…"
          style={{ flex: 1, minWidth: 0, border: 0, outline: "none", resize: "none", font: "inherit", fontSize: 13, lineHeight: 1.45, color: "var(--ink)", background: "transparent", padding: "6px 0" }}
        />
        <button type="submit" className="pill pill-primary" style={{ padding: "10px 16px" }} disabled={thinking || !props.draft.trim()}>
          Ask
        </button>
      </form>
    </div>
  );
}
