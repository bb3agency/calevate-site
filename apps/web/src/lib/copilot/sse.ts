/**
 * A `text/event-stream` parser, because `EventSource` cannot be used here.
 *
 * THE BROWSER'S `EventSource` ISSUES A GET AND NOTHING ELSE. Its constructor takes a URL
 * and an `EventSourceInit`, and that dictionary has exactly one member — `withCredentials`
 * (WHATWG HTML, "the EventSource interface"). There is no method, no headers and no body,
 * so `POST /v1/copilot/ask` with a screen description in the body is not expressible by
 * it at any length. `fetch` + a `ReadableStream` is the only way, and the price of that is
 * this file: the framing is ours to do.
 *
 * Only the parts of the format this endpoint uses are implemented, and the omissions are
 * deliberate rather than partial:
 *
 * - `event:` and `data:` are read. `id:` and `retry:` are IGNORED, because both exist to
 *   serve `EventSource`'s automatic reconnection and there is no automatic reconnection
 *   here (see `stream.ts`, which decides explicitly what a dropped stream does).
 * - Multiple `data:` lines on one event are joined with `\n`, per the spec. Our server
 *   sends one, but a JSON payload with a newline in it is one server-side change away
 *   from arriving as two.
 * - A leading space after the colon is stripped once, per the spec — `data: {…}` and
 *   `data:{…}` are the same event, and getting this wrong makes `JSON.parse` fail on a
 *   perfectly well-formed stream.
 * - A line beginning with `:` is a comment (the conventional keep-alive) and is dropped.
 *
 * ## Chunk boundaries are the whole reason this is a stateful object
 *
 * A `ReadableStream` chunk has nothing to do with an event: `event: fill\ndata: {"item`
 * and `s":[…]}\n\n` is a normal pair of reads. The buffer is therefore kept ACROSS pushes
 * and only complete records (terminated by a blank line) are emitted. `tests/copilot*`
 * feeds a stream split at a byte inside a JSON value for exactly this reason.
 */

export interface SseEvent {
  /** The `event:` name, or `"message"` — the format's own default. */
  event: string;
  data: string;
}

export interface SseParser {
  /** Feed decoded text; returns every event completed by it (often none). */
  push: (chunk: string) => SseEvent[];
  /** True when a partial record is still buffered — i.e. the stream was cut mid-event. */
  hasPartial: () => boolean;
}

export function createSseParser(): SseParser {
  let buffer = "";

  const parseRecord = (record: string): SseEvent | null => {
    let event = "message";
    const data: string[] = [];
    for (const rawLine of record.split("\n")) {
      // `\r` survives a `\r\n`-framed stream once the record split has taken the `\n`.
      const line = rawLine.endsWith("\r") ? rawLine.slice(0, -1) : rawLine;
      if (line === "" || line.startsWith(":")) continue;
      const colon = line.indexOf(":");
      const field = colon === -1 ? line : line.slice(0, colon);
      let value = colon === -1 ? "" : line.slice(colon + 1);
      if (value.startsWith(" ")) value = value.slice(1);
      if (field === "event") event = value;
      else if (field === "data") data.push(value);
    }
    // A record with no `data:` at all is a comment block or a bare `id:` — nothing to
    // dispatch, and emitting it would make every consumer test for empty payloads.
    if (data.length === 0) return null;
    return { event, data: data.join("\n") };
  };

  return {
    push(chunk: string): SseEvent[] {
      buffer += chunk;
      const out: SseEvent[] = [];
      // Records end at a blank line, which is `\n\n` or `\r\n\r\n`. Normalising the
      // whole buffer's line endings would be simpler and wrong: it would rewrite `\r`
      // characters inside a JSON string value.
      for (;;) {
        const lf = buffer.indexOf("\n\n");
        const crlf = buffer.indexOf("\r\n\r\n");
        const at = lf === -1 ? crlf : crlf === -1 ? lf : Math.min(lf, crlf);
        if (at === -1) break;
        const width = at === crlf && (lf === -1 || crlf <= lf) ? 4 : 2;
        const record = buffer.slice(0, at);
        buffer = buffer.slice(at + width);
        const parsed = parseRecord(record);
        if (parsed !== null) out.push(parsed);
      }
      return out;
    },
    hasPartial(): boolean {
      return buffer.trim() !== "";
    },
  };
}
