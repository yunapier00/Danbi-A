import { describe, expect, it } from "vitest";
import { compact, ms, niceMax, pct } from "./format";
import { renderMarkdown } from "./markdown";
import { parseSSE } from "./sse";

describe("parseSSE", () => {
  it("완성된 이벤트만 꺼내고 나머지는 남긴다", () => {
    const buf = 'event: session\ndata: {"session_id":"s1"}\n\nevent: token\ndata: {"text":"안';
    const { events, rest } = parseSSE(buf);
    expect(events).toEqual([{ event: "session", data: { session_id: "s1" } }]);
    expect(rest).toBe('event: token\ndata: {"text":"안');
    const more = parseSSE(rest + '녕"}\n\n');
    expect(more.events).toEqual([{ event: "token", data: { text: "안녕" } }]);
    expect(more.rest).toBe("");
  });
  it("CRLF 줄바꿈도 읽는다", () => {
    expect(parseSSE('event: done\r\ndata: {"elapsed":1}\r\n\r\n').events).toEqual([{ event: "done", data: { elapsed: 1 } }]);
  });
});

describe("format", () => {
  it("숫자·시간을 사람이 읽는 형태로", () => {
    expect(compact(1234)).toBe("1,234");
    expect(compact(43242)).toBe("43.2K");
    expect(compact(1_100_000)).toBe("1.1M");
    expect(ms(0)).toBe("0");
    expect(ms(850)).toBe("850ms");
    expect(ms(4223)).toBe("4.2초");
    expect(pct(1, 3)).toBe("33%");
    expect(pct(1, 0)).toBe("–");
    expect(niceMax(17)).toBe(20);
    expect(niceMax(0)).toBe(1);
  });
});

describe("renderMarkdown", () => {
  it("마크다운을 렌더링하고 위험한 HTML은 지운다", () => {
    const html = renderMarkdown('**굵게**\n\n<img src=x onerror="alert(1)"><script>alert(2)</script>[링크](https://x.kr)');
    expect(html).toContain("<strong>굵게</strong>");
    expect(html).not.toContain("onerror");
    expect(html).not.toContain("<script");
    expect(html).toContain('target="_blank"');
    expect(html).toContain('rel="noopener noreferrer"');
  });
  it("javascript: 링크를 막는다", () => {
    expect(renderMarkdown("[x](javascript:alert(1))")).not.toContain("javascript:");
  });
});

describe("fixKoreanEmphasis", () => {
  it("조사가 붙은 굵게 표시를 살린다", () => {
    expect(renderMarkdown("첫차는 **정문(상징탑)**에서 회차")).toContain("<strong>정문(상징탑)</strong>에서");
    expect(renderMarkdown("**08:15**입니다")).toContain("<strong>08:15</strong>입니다");
  });
  it("코드 안의 별표는 건드리지 않는다", () => {
    expect(renderMarkdown("`**a**` 그대로")).toContain("<code>**a**</code>");
    expect(renderMarkdown("```\n**b**\n```")).toContain("**b**");
  });
  it("강조 안에 스크립트를 넣어도 정제된다", () => {
    expect(renderMarkdown("**<img src=x onerror=alert(1)>**")).not.toContain("onerror");
  });
});
