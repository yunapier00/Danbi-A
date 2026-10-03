// POST 응답의 text/event-stream을 읽는다 (EventSource는 GET만 되므로 fetch 스트림을 직접 파싱).

export interface SSEEvent {
  event: string;
  data: unknown;
}

/** 버퍼에서 완성된 이벤트(빈 줄로 끝난 블록)를 꺼내고 남은 조각을 돌려준다. */
export function parseSSE(buffer: string): { events: SSEEvent[]; rest: string } {
  const events: SSEEvent[] = [];
  let rest = buffer.replace(/\r\n/g, "\n");
  let i: number;
  while ((i = rest.indexOf("\n\n")) >= 0) {
    const block = rest.slice(0, i);
    rest = rest.slice(i + 2);
    let event = "message";
    let data = "";
    for (const line of block.split("\n")) {
      if (line.startsWith("event: ")) event = line.slice(7);
      else if (line.startsWith("data: ")) data += line.slice(6);
    }
    if (data) events.push({ event, data: JSON.parse(data) });
  }
  return { events, rest };
}

export async function* readSSE(res: Response): AsyncGenerator<SSEEvent> {
  if (!res.body) return;
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const { events, rest } = parseSSE(buffer);
    buffer = rest;
    yield* events;
  }
}
