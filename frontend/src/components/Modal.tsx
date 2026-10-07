"use client";

import { useEffect, useRef, type FormEvent } from "react";
import type { Folder } from "@/lib/types";
import { childrenOf } from "@/lib/format";

export type ModalState = {
  kind: "newFolder" | "renameFolder" | "renameFile" | "move" | "deleteFolder" | "deleteFiles";
  title: string;
  body: string;
  cta: string;
  value?: string;
  id?: string;
  ids?: string[];
  parent?: string | null;
  target?: string | null;
  danger?: boolean;
  hasInput?: boolean;
  isMove?: boolean;
};

type Props = {
  modal: ModalState;
  error: string;
  busy: boolean;
  folders: Folder[];
  onChange: (modal: ModalState) => void;
  onClose: () => void;
  onConfirm: () => void;
};

export function Modal({ modal, error, busy, folders, onChange, onClose, onConfirm }: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (modal.hasInput) {
      const t = setTimeout(() => inputRef.current?.focus(), 30);
      return () => clearTimeout(t);
    }
  }, [modal.hasInput]);

  const targets: { folder: Folder; depth: number }[] = [];
  const walk = (parent: string | null, depth: number) =>
    childrenOf(folders, parent).forEach((f) => {
      targets.push({ folder: f, depth });
      walk(f.id, depth + 1);
    });
  if (modal.isMove) walk(null, 0);

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!busy) onConfirm();
  };

  return (
    <div style={{ position: "fixed", inset: 0, zIndex: 60, display: "flex", alignItems: "center", justifyContent: "center", padding: 20 }}>
      <div onClick={onClose} style={{ position: "absolute", inset: 0, background: "rgba(30,34,42,.22)", backdropFilter: "blur(3px)", WebkitBackdropFilter: "blur(3px)" }} />
      <form
        onSubmit={submit}
        style={{ position: "relative", width: "min(420px,100%)", background: "rgba(248,249,251,.96)", border: "1.5px solid #fff", borderRadius: 24, padding: 26, boxShadow: "0 40px 80px rgba(20,30,60,.2)", display: "flex", flexDirection: "column", gap: 18 }}
      >
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          <span style={{ fontSize: 22, fontWeight: 400, textTransform: "uppercase" }}>{modal.title}</span>
          <span style={{ fontSize: 13, lineHeight: 1.5, color: "var(--ink-2)" }}>{modal.body}</span>
        </div>
        {modal.hasInput && (
          <input
            ref={inputRef}
            className="text-input"
            value={modal.value ?? ""}
            onChange={(e) => onChange({ ...modal, value: e.target.value })}
            placeholder={modal.kind === "renameFile" ? "Document title" : "Folder name"}
          />
        )}
        {modal.isMove && (
          <div style={{ maxHeight: 260, overflow: "auto", display: "flex", flexDirection: "column", gap: 2, background: "#fff", borderRadius: 12, padding: 6 }}>
            {targets.map(({ folder, depth }) => {
              const selected = modal.target === folder.id;
              return (
                <button
                  key={folder.id}
                  type="button"
                  onClick={() => onChange({ ...modal, target: folder.id })}
                  style={{ textAlign: "left", border: 0, borderRadius: 8, padding: `8px 10px 8px ${10 + depth * 16}px`, font: "inherit", fontSize: 13, cursor: "pointer", background: selected ? "var(--blue)" : "transparent", color: selected ? "#fff" : "var(--ink)" }}
                >
                  {folder.name}
                </button>
              );
            })}
          </div>
        )}
        {error && <span style={{ fontSize: 12, color: "var(--red)" }}>{error}</span>}
        <div style={{ display: "flex", justifyContent: "flex-end", gap: 10 }}>
          <button type="button" className="pill pill-ghost" onClick={onClose}>
            Cancel
          </button>
          <button type="submit" className={`pill ${modal.danger ? "pill-danger" : "pill-primary"}`} disabled={busy}>
            {busy ? "Working…" : modal.cta}
          </button>
        </div>
      </form>
    </div>
  );
}
