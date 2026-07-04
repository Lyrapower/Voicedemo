import { readFileSync } from "node:fs";
import { join } from "node:path";
import type { PluginContext } from "@lmstudio/sdk";

const GATEWAY_URL =
  process.env.ASTER_GATEWAY_URL?.trim() || "http://127.0.0.1:8501/v1/chat/completions";
const MODEL = process.env.ASTER_GATEWAY_MODEL?.trim() || "demo/aster";

function loadSystemPrompt(): string {
  const fromEnv = process.env.ASTER_CHAT_SYSTEM_PROMPT?.trim();
  if (fromEnv) {
    return fromEnv;
  }
  const candidates = [
    join(__dirname, "..", ".aster_system_prompt"),
    join(__dirname, ".aster_system_prompt"),
  ];
  for (const path of candidates) {
    try {
      const text = readFileSync(path, "utf8").trim();
      if (text) {
        return text;
      }
    } catch {
      /* try next */
    }
  }
  return "";
}

const SYSTEM_PROMPT = loadSystemPrompt();

function withSystemPrompt(messages: Array<{ role: string; content: string }>) {
  if (!SYSTEM_PROMPT) {
    return messages;
  }
  if (messages.some((m) => m.role === "system" && m.content.trim())) {
    return messages;
  }
  return [{ role: "system", content: SYSTEM_PROMPT }, ...messages];
}

export async function main(ctx: PluginContext): Promise<void> {
  ctx.withGenerator(async (ctl, history) => {
    const messages: Array<{ role: string; content: string }> = [];
    for (const turn of history) {
      const role = turn.getRole?.() ?? (turn as { role?: string }).role ?? "user";
      const content = turn.getText?.() ?? String((turn as { content?: string }).content ?? "");
      if (!content.trim()) {
        continue;
      }
      messages.push({ role, content });
    }
    if (messages.length === 0) {
      ctl.fragmentGenerated("[gateway] empty history");
      return;
    }

    const payload = withSystemPrompt(messages);
    const resp = await fetch(GATEWAY_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        model: MODEL,
        messages: payload,
        max_tokens: 400,
        temperature: 0.7,
        stream: false,
      }),
    });
    if (!resp.ok) {
      const errText = await resp.text();
      throw new Error(`gateway ${resp.status}: ${errText.slice(0, 240)}`);
    }
    const data = (await resp.json()) as {
      served_by?: string;
      response?: string;
      choices?: Array<{ message?: { content?: string } }>;
    };
    const text =
      data.choices?.[0]?.message?.content?.trim() ||
      String(data.response || "").trim() ||
      "[gateway] empty response";
    ctl.fragmentGenerated(text);
  });
}
