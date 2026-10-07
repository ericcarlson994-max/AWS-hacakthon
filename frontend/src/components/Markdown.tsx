"use client";

import { Fragment, type ReactNode } from "react";

type Props = { text: string; onCite?: (n: number) => void };

const INLINE = /(\*\*[^*]+\*\*|`[^`]+`|\[\d+(?:\s*,\s*\d+)*\]|\*[^*\s][^*]*\*)/g;

function inline(text: string, onCite: Props["onCite"], keyBase: string): ReactNode[] {
  const out: ReactNode[] = [];
  let last = 0;
  let index = 0;
  for (const match of text.matchAll(INLINE)) {
    const token = match[0];
    const at = match.index ?? 0;
    if (at > last) out.push(text.slice(last, at));
    const key = `${keyBase}-${index++}`;
    if (token.startsWith("**")) out.push(<strong key={key}>{token.slice(2, -2)}</strong>);
    else if (token.startsWith("`")) out.push(<code key={key}>{token.slice(1, -1)}</code>);
    else if (token.startsWith("[")) {
      const numbers = token
        .slice(1, -1)
        .split(",")
        .map((n) => Number(n.trim()));
      out.push(
        <Fragment key={key}>
          {numbers.map((n) => (
            <span key={n} className="cite-ref" role="button" tabIndex={0} onClick={() => onCite?.(n)} onKeyDown={(e) => e.key === "Enter" && onCite?.(n)}>
              [{n}]
            </span>
          ))}
        </Fragment>,
      );
    } else out.push(<em key={key}>{token.slice(1, -1)}</em>);
    last = at + token.length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

function isTableRow(line: string) {
  return /^\s*\|.*\|\s*$/.test(line);
}

function cells(line: string) {
  return line.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((c) => c.trim());
}

export function Markdown({ text, onCite }: Props) {
  const lines = text.replace(/\r/g, "").split("\n");
  const blocks: ReactNode[] = [];
  let i = 0;
  let key = 0;
  while (i < lines.length) {
    const line = lines[i]!;
    if (!line.trim()) {
      i++;
      continue;
    }
    const heading = /^(#{1,4})\s+(.*)$/.exec(line);
    if (heading) {
      blocks.push(<h4 key={key++}>{inline(heading[2]!, onCite, `h${key}`)}</h4>);
      i++;
      continue;
    }
    if (isTableRow(line)) {
      const rows: string[][] = [];
      while (i < lines.length && isTableRow(lines[i]!)) {
        if (!/^\s*\|?[\s:-]+(\|[\s:-]+)+\|?\s*$/.test(lines[i]!)) rows.push(cells(lines[i]!));
        i++;
      }
      const [head, ...body] = rows;
      blocks.push(
        <table key={key++}>
          {head && (
            <thead>
              <tr>{head.map((c, j) => <th key={j}>{inline(c, onCite, `th${key}-${j}`)}</th>)}</tr>
            </thead>
          )}
          <tbody>
            {body.map((row, r) => (
              <tr key={r}>{row.map((c, j) => <td key={j}>{inline(c, onCite, `td${key}-${r}-${j}`)}</td>)}</tr>
            ))}
          </tbody>
        </table>,
      );
      continue;
    }
    if (/^\s*[-*•]\s+/.test(line)) {
      const items: string[] = [];
      while (i < lines.length && /^\s*[-*•]\s+/.test(lines[i]!)) items.push(lines[i++]!.replace(/^\s*[-*•]\s+/, ""));
      blocks.push(<ul key={key++}>{items.map((it, j) => <li key={j}>{inline(it, onCite, `ul${key}-${j}`)}</li>)}</ul>);
      continue;
    }
    if (/^\s*\d+[.)]\s+/.test(line)) {
      const items: string[] = [];
      while (i < lines.length && /^\s*\d+[.)]\s+/.test(lines[i]!)) items.push(lines[i++]!.replace(/^\s*\d+[.)]\s+/, ""));
      blocks.push(<ol key={key++}>{items.map((it, j) => <li key={j}>{inline(it, onCite, `ol${key}-${j}`)}</li>)}</ol>);
      continue;
    }
    const para: string[] = [];
    while (i < lines.length && lines[i]!.trim() && !isTableRow(lines[i]!) && !/^(#{1,4})\s|^\s*[-*•]\s+|^\s*\d+[.)]\s+/.test(lines[i]!)) {
      para.push(lines[i++]!);
    }
    blocks.push(<p key={key++}>{inline(para.join(" "), onCite, `p${key}`)}</p>);
  }
  return <div className="answer">{blocks}</div>;
}
