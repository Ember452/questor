/** readFrames 字节层测试：心跳过滤、跨块分帧、多行 data 拼接。 */

import { describe, expect, it } from "vitest";

import { readFrames } from "./wireRuntime";

function sseResponse(chunks: string[]): Response {
  const encoder = new TextEncoder();
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
      controller.close();
    },
  });
  return new Response(stream);
}

async function collect(chunks: string[]) {
  const out: Array<{ seq: number; frame: unknown }> = [];
  for await (const item of readFrames(sseResponse(chunks))) out.push(item);
  return out;
}

describe("readFrames", () => {
  it("心跳块（无 id）被跳过，不得变成帧、不得回卷游标", async () => {
    const items = await collect([
      'id: 3\nevent: frame\ndata: {"kind":"notice","level":"info","text":"a"}\n\n',
      'event: heartbeat\ndata: {"watermark":3}\n\n',
      'id: 4\nevent: frame\ndata: {"kind":"notice","level":"info","text":"b"}\n\n',
    ]);
    expect(items).toHaveLength(2);
    expect(items[0]?.seq).toBe(3);
    expect(items[1]?.seq).toBe(4);
  });

  it("跨 TCP 块的帧能正确拼接", async () => {
    const items = await collect([
      'id: 1\nevent: fra',
      'me\ndata: {"kind":"notice","level":"info","text":"split"}\n\n',
    ]);
    expect(items).toHaveLength(1);
    expect((items[0]?.frame as { kind: string }).kind).toBe("notice");
  });
});
