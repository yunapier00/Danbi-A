import DOMPurify from "dompurify";
import { marked } from "marked";
import { useMemo } from "react";

// 답변·도구 결과는 신뢰할 수 없는 데이터다. 마크다운을 HTML로 바꾼 뒤 반드시 DOMPurify로 정제한다.
DOMPurify.addHook("afterSanitizeAttributes", (node) => {
  if (node.tagName === "A") {
    node.setAttribute("target", "_blank");
    node.setAttribute("rel", "noopener noreferrer");
  }
});

const BOLD = /\*\*(?=\S)([^*\n]+?)(?<=\S)\*\*/g;

/**
 * CommonMark는 닫는 `**` 앞이 문장부호이고 뒤가 글자면 강조를 닫지 않는다.
 * 한국어는 `**정문(상징탑)**에서`처럼 조사가 바로 붙어 이 규칙에 자주 걸리므로,
 * 코드(펜스·인라인) 밖의 `**…**` 쌍을 미리 <strong>으로 바꾼다. (결과는 아래에서 DOMPurify가 정제한다)
 */
export function fixKoreanEmphasis(md: string): string {
  let inFence = false;
  return md.split("\n").map((line) => {
    if (/^\s*(```|~~~)/.test(line)) { inFence = !inFence; return line; }
    if (inFence) return line;
    // 인라인 코드(`...`) 조각은 건너뛴다: 홀수 번째 조각이 코드
    return line.split(/(`[^`]*`)/).map((part, i) => (i % 2 ? part : part.replace(BOLD, "<strong>$1</strong>"))).join("");
  }).join("\n");
}

export function renderMarkdown(md: string): string {
  const html = marked.parse(fixKoreanEmphasis(md || ""), { breaks: true, async: false }) as string;
  return DOMPurify.sanitize(html);
}

export function Markdown({ text, className }: { text: string; className?: string }) {
  const html = useMemo(() => renderMarkdown(text), [text]);
  return <div className={className} dangerouslySetInnerHTML={{ __html: html }} />;
}
