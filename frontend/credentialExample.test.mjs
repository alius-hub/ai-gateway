import assert from "node:assert/strict";
import test from "node:test";

import { buildCurlExample, preferredShell } from "./src/utils/credentialExample.ts";

const origin = "http://localhost:5173";
const key = "agw_example";

test("defaults to Windows PowerShell only on Windows", () => {
  assert.equal(preferredShell("Mozilla/5.0 (Windows NT 10.0; Win64; x64)"), "windows");
  assert.equal(preferredShell("Mozilla/5.0 (X11; Linux x86_64)"), "linux");
  assert.equal(preferredShell("Mozilla/5.0 (Macintosh; Intel Mac OS X)"), "linux");
});

test("builds shell-safe examples for the selected model type", () => {
  for (const [model_type, path] of [
    ["llm", "/v1/chat/completions"], ["vlm", "/v1/chat/completions"],
    ["embedding", "/v1/embeddings"], ["rerank", "/v1/rerank"],
    ["ocr", "/v1/ocr"], ["text_to_image", "/v1/images/generations"],
  ]) {
    const model = { id: "demo", model_type };
    const linux = buildCurlExample(key, model, origin, "linux");
    const windows = buildCurlExample(key, model, origin, "windows");
    assert.ok(linux?.includes(`${origin}${path}`));
    assert.ok(windows?.includes(`${origin}${path}`));
    assert.ok(linux?.includes(`Authorization: Bearer ${key}`));
    assert.ok(windows?.includes(`Authorization: Bearer ${key}`));
    assert.match(windows, /\$body = @'\r\n\{"model":"demo"/);
    assert.match(windows, /\r\n'@\r\n\$body \| curl\.exe/);
    assert.equal(JSON.parse(linux.match(/--data-raw '(.+)'/)?.[1] ?? "{}").model, "demo");
  }
  assert.equal(buildCurlExample(key, { id: "audio", model_type: "tts" }, origin, "linux"), null);
});

test("quotes unusual model names and preserves Unicode in the PowerShell body", () => {
  const model = { id: "l'avis 中文", model_type: "llm" };
  const linux = buildCurlExample(key, model, origin, "linux");
  const windows = buildCurlExample(key, model, origin, "windows");
  assert.ok(linux?.includes("'\"'\"'"));
  assert.ok(windows?.includes('"model":"l\'avis 中文"'));
  assert.ok(windows?.includes("UTF8Encoding"));
});
