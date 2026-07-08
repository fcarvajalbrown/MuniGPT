// smoke-chat.mjs — A2 acceptance check.
//
// Sends one Spanish query to a RUNNING backend /chat endpoint and verifies the
// SSE contract the frontend depends on: a citations event, then token events,
// then done. Exits non-zero if either citations or tokens are missing.
//
//   node scripts/smoke-chat.mjs            # hits http://127.0.0.1:8000
//   MUNIGPT_API=http://127.0.0.1:8001 node scripts/smoke-chat.mjs

const API = process.env.MUNIGPT_API ?? "http://127.0.0.1:8000";
const QUERY = "¿Qué obligaciones de ciberseguridad tienen las municipalidades?";

const res = await fetch(`${API}/chat`, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ message: QUERY, history: [] }),
});

if (!res.ok || !res.body) {
  console.error(`FAIL: /chat responded ${res.status}`);
  process.exit(1);
}

const reader = res.body.getReader();
const decoder = new TextDecoder();
let buffer = "";
let citations = null;
let tokenText = "";
let tokenCount = 0;
let done = false;

outer: while (!done) {
  const { value, done: streamDone } = await reader.read();
  if (streamDone) break;
  buffer += decoder.decode(value, { stream: true });
  let sep;
  while ((sep = buffer.indexOf("\n\n")) !== -1) {
    const frame = buffer.slice(0, sep);
    buffer = buffer.slice(sep + 2);
    for (const line of frame.split("\n")) {
      if (!line.startsWith("data: ")) continue;
      const evt = JSON.parse(line.slice(6));
      if (evt.type === "citations") {
        citations = evt.citations;
      } else if (evt.type === "token") {
        tokenText += evt.content;
        tokenCount++;
      } else if (evt.type === "error") {
        console.error("FAIL: error event:", evt.message);
        process.exit(1);
      } else if (evt.type === "done") {
        done = true;
        break outer;
      }
    }
  }
}

console.log(`citations: ${citations ? citations.length : 0}`);
if (citations) {
  for (const c of citations) console.log(`  - ${c.source} (chunk ${c.chunk_index})`);
}
console.log(`tokens: ${tokenCount}`);
console.log(`answer preview: ${tokenText.slice(0, 200).replace(/\n/g, " ")}`);

if (!citations || citations.length === 0) {
  console.error("FAIL: no citations event");
  process.exit(1);
}
if (tokenCount === 0) {
  console.error("FAIL: no token events");
  process.exit(1);
}
console.log("A2 chat SSE smoke: PASS");
