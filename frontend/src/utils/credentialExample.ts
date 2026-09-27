export type CurlShell = "linux" | "windows";

export interface ExampleModel {
  id: string;
  model_type: string;
}

export function preferredShell(userAgent: string): CurlShell {
  return /windows/i.test(userAgent) ? "windows" : "linux";
}

export function buildCurlExample(
  key: string, model: ExampleModel, origin: string, shell: CurlShell,
): string | null {
  const type = model.model_type;
  let path: string;
  let payload: Record<string, unknown>;
  if (type === "llm" || type === "vlm") {
    path = "/v1/chat/completions";
    payload = { model: model.id, messages: [{ role: "user", content: "Hello" }], max_tokens: 128 };
  } else if (type === "embedding") {
    path = "/v1/embeddings";
    payload = { model: model.id, input: "Hello" };
  } else if (type === "rerank") {
    path = "/v1/rerank";
    payload = { model: model.id, query: "Hello", documents: ["Hello world", "Another result"] };
  } else if (type === "ocr") {
    path = "/v1/ocr";
    payload = { model: model.id, image_url: "https://example.com/image.png" };
  } else if (type === "text_to_image") {
    path = "/v1/images/generations";
    payload = { model: model.id, prompt: "A sunrise over the sea", n: 1 };
  } else {
    return null;
  }

  const url = new URL(path, origin).toString();
  const body = JSON.stringify(payload);
  if (shell === "windows") {
    // A here-string avoids Windows PowerShell 5.1 stripping JSON quotes from native arguments.
    const quote = (value: string) => `"${value.replace(/`/g, "``").replace(/"/g, '`"')}"`;
    return [
      "$OutputEncoding = [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)",
      "$body = @'",
      body,
      "'@",
      "$body | curl.exe -X POST " + quote(url)
        + " -H " + quote(`Authorization: Bearer ${key}`)
        + " -H \"Content-Type: application/json\" --data-binary \"@-\"",
    ].join("\r\n");
  }
  const quote = (value: string) => `'${value.replace(/'/g, "'\"'\"'")}'`;
  return [
    `curl -X POST ${quote(url)} \\`,
    `  -H ${quote(`Authorization: Bearer ${key}`)} \\`,
    `  -H ${quote("Content-Type: application/json")} \\`,
    `  --data-raw ${quote(body)}`,
  ].join("\n");
}
