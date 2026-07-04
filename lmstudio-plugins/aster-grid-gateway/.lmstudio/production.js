var __defProp = Object.defineProperty;
var __getOwnPropNames = Object.getOwnPropertyNames;
var __esm = (fn, res) => function __init() {
  return fn && (res = (0, fn[__getOwnPropNames(fn)[0]])(fn = 0)), res;
};
var __export = (target, all) => {
  for (var name in all)
    __defProp(target, name, { get: all[name], enumerable: true });
};

// Users/ciciwang/Desktop/demo/lmstudio-plugins/aster-grid-gateway/src/index.ts
var src_exports = {};
__export(src_exports, {
  main: () => main
});
function loadSystemPrompt() {
  const fromEnv = process.env.ASTER_CHAT_SYSTEM_PROMPT?.trim();
  if (fromEnv) {
    return fromEnv;
  }
  const candidates = [
    (0, import_node_path.join)(__dirname, "..", ".aster_system_prompt"),
    (0, import_node_path.join)(__dirname, ".aster_system_prompt")
  ];
  for (const path of candidates) {
    try {
      const text = (0, import_node_fs.readFileSync)(path, "utf8").trim();
      if (text) {
        return text;
      }
    } catch {
    }
  }
  return "";
}
function withSystemPrompt(messages) {
  if (!SYSTEM_PROMPT) {
    return messages;
  }
  if (messages.some((m) => m.role === "system" && m.content.trim())) {
    return messages;
  }
  return [{ role: "system", content: SYSTEM_PROMPT }, ...messages];
}
async function main(ctx) {
  ctx.withGenerator(async (ctl, history) => {
    const messages = [];
    for (const turn of history) {
      const role = turn.getRole?.() ?? turn.role ?? "user";
      const content = turn.getText?.() ?? String(turn.content ?? "");
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
        stream: false
      })
    });
    if (!resp.ok) {
      const errText = await resp.text();
      throw new Error(`gateway ${resp.status}: ${errText.slice(0, 240)}`);
    }
    const data = await resp.json();
    const text = data.choices?.[0]?.message?.content?.trim() || String(data.response || "").trim() || "[gateway] empty response";
    ctl.fragmentGenerated(text);
  });
}
var import_node_fs, import_node_path, GATEWAY_URL, MODEL, SYSTEM_PROMPT;
var init_src = __esm({
  "Users/ciciwang/Desktop/demo/lmstudio-plugins/aster-grid-gateway/src/index.ts"() {
    import_node_fs = require("node:fs");
    import_node_path = require("node:path");
    GATEWAY_URL = process.env.ASTER_GATEWAY_URL?.trim() || "http://127.0.0.1:8501/v1/chat/completions";
    MODEL = process.env.ASTER_GATEWAY_MODEL?.trim() || "demo/aster";
    SYSTEM_PROMPT = loadSystemPrompt();
  }
});

// Users/ciciwang/Desktop/demo/lmstudio-plugins/aster-grid-gateway/.lmstudio/entry.ts
var import_sdk = require("@lmstudio/sdk");
var clientIdentifier = process.env.LMS_PLUGIN_CLIENT_IDENTIFIER;
var clientPasskey = process.env.LMS_PLUGIN_CLIENT_PASSKEY;
var baseUrl = process.env.LMS_PLUGIN_BASE_URL;
var client = new import_sdk.LMStudioClient({
  clientIdentifier,
  clientPasskey,
  baseUrl
});
globalThis.__LMS_PLUGIN_CONTEXT = true;
var predictionLoopHandlerSet = false;
var promptPreprocessorSet = false;
var configSchematicsSet = false;
var globalConfigSchematicsSet = false;
var toolsProviderSet = false;
var generatorSet = false;
var selfRegistrationHost = client.plugins.getSelfRegistrationHost();
var pluginContext = {
  withPredictionLoopHandler: (generate) => {
    if (predictionLoopHandlerSet) {
      throw new Error("PredictionLoopHandler already registered");
    }
    if (toolsProviderSet) {
      throw new Error("PredictionLoopHandler cannot be used with a tools provider");
    }
    predictionLoopHandlerSet = true;
    selfRegistrationHost.setPredictionLoopHandler(generate);
    return pluginContext;
  },
  withPromptPreprocessor: (preprocess) => {
    if (promptPreprocessorSet) {
      throw new Error("PromptPreprocessor already registered");
    }
    promptPreprocessorSet = true;
    selfRegistrationHost.setPromptPreprocessor(preprocess);
    return pluginContext;
  },
  withConfigSchematics: (configSchematics) => {
    if (configSchematicsSet) {
      throw new Error("Config schematics already registered");
    }
    configSchematicsSet = true;
    selfRegistrationHost.setConfigSchematics(configSchematics);
    return pluginContext;
  },
  withGlobalConfigSchematics: (globalConfigSchematics) => {
    if (globalConfigSchematicsSet) {
      throw new Error("Global config schematics already registered");
    }
    globalConfigSchematicsSet = true;
    selfRegistrationHost.setGlobalConfigSchematics(globalConfigSchematics);
    return pluginContext;
  },
  withToolsProvider: (toolsProvider) => {
    if (toolsProviderSet) {
      throw new Error("Tools provider already registered");
    }
    if (predictionLoopHandlerSet) {
      throw new Error("Tools provider cannot be used with a predictionLoopHandler");
    }
    toolsProviderSet = true;
    selfRegistrationHost.setToolsProvider(toolsProvider);
    return pluginContext;
  },
  withGenerator: (generator) => {
    if (generatorSet) {
      throw new Error("Generator already registered");
    }
    generatorSet = true;
    selfRegistrationHost.setGenerator(generator);
    return pluginContext;
  }
};
Promise.resolve().then(() => (init_src(), src_exports)).then(async (module2) => {
  return await module2.main(pluginContext);
}).then(() => {
  selfRegistrationHost.initCompleted();
}).catch((error) => {
  console.error("Failed to execute the main function of the plugin.");
  console.error(error);
});
//# sourceMappingURL=data:application/json;base64,ewogICJ2ZXJzaW9uIjogMywKICAic291cmNlcyI6IFsiLi4vLi4vLi4vLi4vLi4vLi4vRGVza3RvcC9kZW1vL2xtc3R1ZGlvLXBsdWdpbnMvYXN0ZXItZ3JpZC1nYXRld2F5L3NyYy9pbmRleC50cyIsICIuLi8uLi8uLi8uLi8uLi8uLi9EZXNrdG9wL2RlbW8vbG1zdHVkaW8tcGx1Z2lucy9hc3Rlci1ncmlkLWdhdGV3YXkvLmxtc3R1ZGlvL2VudHJ5LnRzIl0sCiAgInNvdXJjZXNDb250ZW50IjogWyJpbXBvcnQgeyByZWFkRmlsZVN5bmMgfSBmcm9tIFwibm9kZTpmc1wiO1xuaW1wb3J0IHsgam9pbiB9IGZyb20gXCJub2RlOnBhdGhcIjtcbmltcG9ydCB0eXBlIHsgUGx1Z2luQ29udGV4dCB9IGZyb20gXCJAbG1zdHVkaW8vc2RrXCI7XG5cbmNvbnN0IEdBVEVXQVlfVVJMID1cbiAgcHJvY2Vzcy5lbnYuQVNURVJfR0FURVdBWV9VUkw/LnRyaW0oKSB8fCBcImh0dHA6Ly8xMjcuMC4wLjE6ODUwMS92MS9jaGF0L2NvbXBsZXRpb25zXCI7XG5jb25zdCBNT0RFTCA9IHByb2Nlc3MuZW52LkFTVEVSX0dBVEVXQVlfTU9ERUw/LnRyaW0oKSB8fCBcImRlbW8vYXN0ZXJcIjtcblxuZnVuY3Rpb24gbG9hZFN5c3RlbVByb21wdCgpOiBzdHJpbmcge1xuICBjb25zdCBmcm9tRW52ID0gcHJvY2Vzcy5lbnYuQVNURVJfQ0hBVF9TWVNURU1fUFJPTVBUPy50cmltKCk7XG4gIGlmIChmcm9tRW52KSB7XG4gICAgcmV0dXJuIGZyb21FbnY7XG4gIH1cbiAgY29uc3QgY2FuZGlkYXRlcyA9IFtcbiAgICBqb2luKF9fZGlybmFtZSwgXCIuLlwiLCBcIi5hc3Rlcl9zeXN0ZW1fcHJvbXB0XCIpLFxuICAgIGpvaW4oX19kaXJuYW1lLCBcIi5hc3Rlcl9zeXN0ZW1fcHJvbXB0XCIpLFxuICBdO1xuICBmb3IgKGNvbnN0IHBhdGggb2YgY2FuZGlkYXRlcykge1xuICAgIHRyeSB7XG4gICAgICBjb25zdCB0ZXh0ID0gcmVhZEZpbGVTeW5jKHBhdGgsIFwidXRmOFwiKS50cmltKCk7XG4gICAgICBpZiAodGV4dCkge1xuICAgICAgICByZXR1cm4gdGV4dDtcbiAgICAgIH1cbiAgICB9IGNhdGNoIHtcbiAgICAgIC8qIHRyeSBuZXh0ICovXG4gICAgfVxuICB9XG4gIHJldHVybiBcIlwiO1xufVxuXG5jb25zdCBTWVNURU1fUFJPTVBUID0gbG9hZFN5c3RlbVByb21wdCgpO1xuXG5mdW5jdGlvbiB3aXRoU3lzdGVtUHJvbXB0KG1lc3NhZ2VzOiBBcnJheTx7IHJvbGU6IHN0cmluZzsgY29udGVudDogc3RyaW5nIH0+KSB7XG4gIGlmICghU1lTVEVNX1BST01QVCkge1xuICAgIHJldHVybiBtZXNzYWdlcztcbiAgfVxuICBpZiAobWVzc2FnZXMuc29tZSgobSkgPT4gbS5yb2xlID09PSBcInN5c3RlbVwiICYmIG0uY29udGVudC50cmltKCkpKSB7XG4gICAgcmV0dXJuIG1lc3NhZ2VzO1xuICB9XG4gIHJldHVybiBbeyByb2xlOiBcInN5c3RlbVwiLCBjb250ZW50OiBTWVNURU1fUFJPTVBUIH0sIC4uLm1lc3NhZ2VzXTtcbn1cblxuZXhwb3J0IGFzeW5jIGZ1bmN0aW9uIG1haW4oY3R4OiBQbHVnaW5Db250ZXh0KTogUHJvbWlzZTx2b2lkPiB7XG4gIGN0eC53aXRoR2VuZXJhdG9yKGFzeW5jIChjdGwsIGhpc3RvcnkpID0+IHtcbiAgICBjb25zdCBtZXNzYWdlczogQXJyYXk8eyByb2xlOiBzdHJpbmc7IGNvbnRlbnQ6IHN0cmluZyB9PiA9IFtdO1xuICAgIGZvciAoY29uc3QgdHVybiBvZiBoaXN0b3J5KSB7XG4gICAgICBjb25zdCByb2xlID0gdHVybi5nZXRSb2xlPy4oKSA/PyAodHVybiBhcyB7IHJvbGU/OiBzdHJpbmcgfSkucm9sZSA/PyBcInVzZXJcIjtcbiAgICAgIGNvbnN0IGNvbnRlbnQgPSB0dXJuLmdldFRleHQ/LigpID8/IFN0cmluZygodHVybiBhcyB7IGNvbnRlbnQ/OiBzdHJpbmcgfSkuY29udGVudCA/PyBcIlwiKTtcbiAgICAgIGlmICghY29udGVudC50cmltKCkpIHtcbiAgICAgICAgY29udGludWU7XG4gICAgICB9XG4gICAgICBtZXNzYWdlcy5wdXNoKHsgcm9sZSwgY29udGVudCB9KTtcbiAgICB9XG4gICAgaWYgKG1lc3NhZ2VzLmxlbmd0aCA9PT0gMCkge1xuICAgICAgY3RsLmZyYWdtZW50R2VuZXJhdGVkKFwiW2dhdGV3YXldIGVtcHR5IGhpc3RvcnlcIik7XG4gICAgICByZXR1cm47XG4gICAgfVxuXG4gICAgY29uc3QgcGF5bG9hZCA9IHdpdGhTeXN0ZW1Qcm9tcHQobWVzc2FnZXMpO1xuICAgIGNvbnN0IHJlc3AgPSBhd2FpdCBmZXRjaChHQVRFV0FZX1VSTCwge1xuICAgICAgbWV0aG9kOiBcIlBPU1RcIixcbiAgICAgIGhlYWRlcnM6IHsgXCJDb250ZW50LVR5cGVcIjogXCJhcHBsaWNhdGlvbi9qc29uXCIgfSxcbiAgICAgIGJvZHk6IEpTT04uc3RyaW5naWZ5KHtcbiAgICAgICAgbW9kZWw6IE1PREVMLFxuICAgICAgICBtZXNzYWdlczogcGF5bG9hZCxcbiAgICAgICAgbWF4X3Rva2VuczogNDAwLFxuICAgICAgICB0ZW1wZXJhdHVyZTogMC43LFxuICAgICAgICBzdHJlYW06IGZhbHNlLFxuICAgICAgfSksXG4gICAgfSk7XG4gICAgaWYgKCFyZXNwLm9rKSB7XG4gICAgICBjb25zdCBlcnJUZXh0ID0gYXdhaXQgcmVzcC50ZXh0KCk7XG4gICAgICB0aHJvdyBuZXcgRXJyb3IoYGdhdGV3YXkgJHtyZXNwLnN0YXR1c306ICR7ZXJyVGV4dC5zbGljZSgwLCAyNDApfWApO1xuICAgIH1cbiAgICBjb25zdCBkYXRhID0gKGF3YWl0IHJlc3AuanNvbigpKSBhcyB7XG4gICAgICBzZXJ2ZWRfYnk/OiBzdHJpbmc7XG4gICAgICByZXNwb25zZT86IHN0cmluZztcbiAgICAgIGNob2ljZXM/OiBBcnJheTx7IG1lc3NhZ2U/OiB7IGNvbnRlbnQ/OiBzdHJpbmcgfSB9PjtcbiAgICB9O1xuICAgIGNvbnN0IHRleHQgPVxuICAgICAgZGF0YS5jaG9pY2VzPy5bMF0/Lm1lc3NhZ2U/LmNvbnRlbnQ/LnRyaW0oKSB8fFxuICAgICAgU3RyaW5nKGRhdGEucmVzcG9uc2UgfHwgXCJcIikudHJpbSgpIHx8XG4gICAgICBcIltnYXRld2F5XSBlbXB0eSByZXNwb25zZVwiO1xuICAgIGN0bC5mcmFnbWVudEdlbmVyYXRlZCh0ZXh0KTtcbiAgfSk7XG59XG4iLCAiaW1wb3J0IHsgTE1TdHVkaW9DbGllbnQsIHR5cGUgUGx1Z2luQ29udGV4dCB9IGZyb20gXCJAbG1zdHVkaW8vc2RrXCI7XG5cbmRlY2xhcmUgdmFyIHByb2Nlc3M6IGFueTtcblxuLy8gV2UgcmVjZWl2ZSBydW50aW1lIGluZm9ybWF0aW9uIGluIHRoZSBlbnZpcm9ubWVudCB2YXJpYWJsZXMuXG5jb25zdCBjbGllbnRJZGVudGlmaWVyID0gcHJvY2Vzcy5lbnYuTE1TX1BMVUdJTl9DTElFTlRfSURFTlRJRklFUjtcbmNvbnN0IGNsaWVudFBhc3NrZXkgPSBwcm9jZXNzLmVudi5MTVNfUExVR0lOX0NMSUVOVF9QQVNTS0VZO1xuY29uc3QgYmFzZVVybCA9IHByb2Nlc3MuZW52LkxNU19QTFVHSU5fQkFTRV9VUkw7XG5cbmNvbnN0IGNsaWVudCA9IG5ldyBMTVN0dWRpb0NsaWVudCh7XG4gIGNsaWVudElkZW50aWZpZXIsXG4gIGNsaWVudFBhc3NrZXksXG4gIGJhc2VVcmwsXG59KTtcblxuKGdsb2JhbFRoaXMgYXMgYW55KS5fX0xNU19QTFVHSU5fQ09OVEVYVCA9IHRydWU7XG5cbmxldCBwcmVkaWN0aW9uTG9vcEhhbmRsZXJTZXQgPSBmYWxzZTtcbmxldCBwcm9tcHRQcmVwcm9jZXNzb3JTZXQgPSBmYWxzZTtcbmxldCBjb25maWdTY2hlbWF0aWNzU2V0ID0gZmFsc2U7XG5sZXQgZ2xvYmFsQ29uZmlnU2NoZW1hdGljc1NldCA9IGZhbHNlO1xubGV0IHRvb2xzUHJvdmlkZXJTZXQgPSBmYWxzZTtcbmxldCBnZW5lcmF0b3JTZXQgPSBmYWxzZTtcblxuY29uc3Qgc2VsZlJlZ2lzdHJhdGlvbkhvc3QgPSBjbGllbnQucGx1Z2lucy5nZXRTZWxmUmVnaXN0cmF0aW9uSG9zdCgpO1xuXG5jb25zdCBwbHVnaW5Db250ZXh0OiBQbHVnaW5Db250ZXh0ID0ge1xuICB3aXRoUHJlZGljdGlvbkxvb3BIYW5kbGVyOiAoZ2VuZXJhdGUpID0+IHtcbiAgICBpZiAocHJlZGljdGlvbkxvb3BIYW5kbGVyU2V0KSB7XG4gICAgICB0aHJvdyBuZXcgRXJyb3IoXCJQcmVkaWN0aW9uTG9vcEhhbmRsZXIgYWxyZWFkeSByZWdpc3RlcmVkXCIpO1xuICAgIH1cbiAgICBpZiAodG9vbHNQcm92aWRlclNldCkge1xuICAgICAgdGhyb3cgbmV3IEVycm9yKFwiUHJlZGljdGlvbkxvb3BIYW5kbGVyIGNhbm5vdCBiZSB1c2VkIHdpdGggYSB0b29scyBwcm92aWRlclwiKTtcbiAgICB9XG5cbiAgICBwcmVkaWN0aW9uTG9vcEhhbmRsZXJTZXQgPSB0cnVlO1xuICAgIHNlbGZSZWdpc3RyYXRpb25Ib3N0LnNldFByZWRpY3Rpb25Mb29wSGFuZGxlcihnZW5lcmF0ZSk7XG4gICAgcmV0dXJuIHBsdWdpbkNvbnRleHQ7XG4gIH0sXG4gIHdpdGhQcm9tcHRQcmVwcm9jZXNzb3I6IChwcmVwcm9jZXNzKSA9PiB7XG4gICAgaWYgKHByb21wdFByZXByb2Nlc3NvclNldCkge1xuICAgICAgdGhyb3cgbmV3IEVycm9yKFwiUHJvbXB0UHJlcHJvY2Vzc29yIGFscmVhZHkgcmVnaXN0ZXJlZFwiKTtcbiAgICB9XG4gICAgcHJvbXB0UHJlcHJvY2Vzc29yU2V0ID0gdHJ1ZTtcbiAgICBzZWxmUmVnaXN0cmF0aW9uSG9zdC5zZXRQcm9tcHRQcmVwcm9jZXNzb3IocHJlcHJvY2Vzcyk7XG4gICAgcmV0dXJuIHBsdWdpbkNvbnRleHQ7XG4gIH0sXG4gIHdpdGhDb25maWdTY2hlbWF0aWNzOiAoY29uZmlnU2NoZW1hdGljcykgPT4ge1xuICAgIGlmIChjb25maWdTY2hlbWF0aWNzU2V0KSB7XG4gICAgICB0aHJvdyBuZXcgRXJyb3IoXCJDb25maWcgc2NoZW1hdGljcyBhbHJlYWR5IHJlZ2lzdGVyZWRcIik7XG4gICAgfVxuICAgIGNvbmZpZ1NjaGVtYXRpY3NTZXQgPSB0cnVlO1xuICAgIHNlbGZSZWdpc3RyYXRpb25Ib3N0LnNldENvbmZpZ1NjaGVtYXRpY3MoY29uZmlnU2NoZW1hdGljcyk7XG4gICAgcmV0dXJuIHBsdWdpbkNvbnRleHQ7XG4gIH0sXG4gIHdpdGhHbG9iYWxDb25maWdTY2hlbWF0aWNzOiAoZ2xvYmFsQ29uZmlnU2NoZW1hdGljcykgPT4ge1xuICAgIGlmIChnbG9iYWxDb25maWdTY2hlbWF0aWNzU2V0KSB7XG4gICAgICB0aHJvdyBuZXcgRXJyb3IoXCJHbG9iYWwgY29uZmlnIHNjaGVtYXRpY3MgYWxyZWFkeSByZWdpc3RlcmVkXCIpO1xuICAgIH1cbiAgICBnbG9iYWxDb25maWdTY2hlbWF0aWNzU2V0ID0gdHJ1ZTtcbiAgICBzZWxmUmVnaXN0cmF0aW9uSG9zdC5zZXRHbG9iYWxDb25maWdTY2hlbWF0aWNzKGdsb2JhbENvbmZpZ1NjaGVtYXRpY3MpO1xuICAgIHJldHVybiBwbHVnaW5Db250ZXh0O1xuICB9LFxuICB3aXRoVG9vbHNQcm92aWRlcjogKHRvb2xzUHJvdmlkZXIpID0+IHtcbiAgICBpZiAodG9vbHNQcm92aWRlclNldCkge1xuICAgICAgdGhyb3cgbmV3IEVycm9yKFwiVG9vbHMgcHJvdmlkZXIgYWxyZWFkeSByZWdpc3RlcmVkXCIpO1xuICAgIH1cbiAgICBpZiAocHJlZGljdGlvbkxvb3BIYW5kbGVyU2V0KSB7XG4gICAgICB0aHJvdyBuZXcgRXJyb3IoXCJUb29scyBwcm92aWRlciBjYW5ub3QgYmUgdXNlZCB3aXRoIGEgcHJlZGljdGlvbkxvb3BIYW5kbGVyXCIpO1xuICAgIH1cblxuICAgIHRvb2xzUHJvdmlkZXJTZXQgPSB0cnVlO1xuICAgIHNlbGZSZWdpc3RyYXRpb25Ib3N0LnNldFRvb2xzUHJvdmlkZXIodG9vbHNQcm92aWRlcik7XG4gICAgcmV0dXJuIHBsdWdpbkNvbnRleHQ7XG4gIH0sXG4gIHdpdGhHZW5lcmF0b3I6IChnZW5lcmF0b3IpID0+IHtcbiAgICBpZiAoZ2VuZXJhdG9yU2V0KSB7XG4gICAgICB0aHJvdyBuZXcgRXJyb3IoXCJHZW5lcmF0b3IgYWxyZWFkeSByZWdpc3RlcmVkXCIpO1xuICAgIH1cblxuICAgIGdlbmVyYXRvclNldCA9IHRydWU7XG4gICAgc2VsZlJlZ2lzdHJhdGlvbkhvc3Quc2V0R2VuZXJhdG9yKGdlbmVyYXRvcik7XG4gICAgcmV0dXJuIHBsdWdpbkNvbnRleHQ7XG4gIH0sXG59O1xuXG5pbXBvcnQoXCIuLy4uL3NyYy9pbmRleC50c1wiKS50aGVuKGFzeW5jIG1vZHVsZSA9PiB7XG4gIHJldHVybiBhd2FpdCBtb2R1bGUubWFpbihwbHVnaW5Db250ZXh0KTtcbn0pLnRoZW4oKCkgPT4ge1xuICBzZWxmUmVnaXN0cmF0aW9uSG9zdC5pbml0Q29tcGxldGVkKCk7XG59KS5jYXRjaCgoZXJyb3IpID0+IHtcbiAgY29uc29sZS5lcnJvcihcIkZhaWxlZCB0byBleGVjdXRlIHRoZSBtYWluIGZ1bmN0aW9uIG9mIHRoZSBwbHVnaW4uXCIpO1xuICBjb25zb2xlLmVycm9yKGVycm9yKTtcbn0pO1xuIl0sCiAgIm1hcHBpbmdzIjogIjs7Ozs7Ozs7Ozs7QUFBQTtBQUFBO0FBQUE7QUFBQTtBQVFBLFNBQVMsbUJBQTJCO0FBQ2xDLFFBQU0sVUFBVSxRQUFRLElBQUksMEJBQTBCLEtBQUs7QUFDM0QsTUFBSSxTQUFTO0FBQ1gsV0FBTztBQUFBLEVBQ1Q7QUFDQSxRQUFNLGFBQWE7QUFBQSxRQUNqQix1QkFBSyxXQUFXLE1BQU0sc0JBQXNCO0FBQUEsUUFDNUMsdUJBQUssV0FBVyxzQkFBc0I7QUFBQSxFQUN4QztBQUNBLGFBQVcsUUFBUSxZQUFZO0FBQzdCLFFBQUk7QUFDRixZQUFNLFdBQU8sNkJBQWEsTUFBTSxNQUFNLEVBQUUsS0FBSztBQUM3QyxVQUFJLE1BQU07QUFDUixlQUFPO0FBQUEsTUFD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QUFNLElBQUksTUFBTSw0REFBNEQ7QUFBQSxJQUM5RTtBQUVBLCtCQUEyQjtBQUMzQix5QkFBcUIseUJBQXlCLFFBQVE7QUFDdEQsV0FBTztBQUFBLEVBQ1Q7QUFBQSxFQUNBLHdCQUF3QixDQUFDLGVBQWU7QUFDdEMsUUFBSSx1QkFBdUI7QUFDekIsWUFBTSxJQUFJLE1BQU0sdUNBQXVDO0FBQUEsSUFDekQ7QUFDQSw0QkFBd0I7QUFDeEIseUJBQXFCLHNCQUFzQixVQUFVO0FBQ3JELFdBQU87QUFBQSxFQUNUO0FBQUEsRUFDQSxzQkFBc0IsQ0FBQyxxQkFBcUI7QUFDMUMsUUFBSSxxQkFBcUI7QUFDdkIsWUFBTSxJQUFJLE1BQU0sc0NBQXNDO0FBQUEsSUFDeEQ7QUFDQSwwQkFBc0I7QUFDdEIseUJBQXFCLG9CQUFvQixnQkFBZ0I7QUFDekQsV0FBTztBQUFBLEVBQ1Q7QUFBQSxFQUNBLDRCQUE0QixDQUFDLDJCQUEyQjtBQUN0RCxRQUFJLDJCQUEyQjtBQUM3QixZQUFNLElBQUksTUFBTSw2Q0FBNkM7QUFBQSxJQUMvRDtBQUNBLGdDQUE0QjtBQUM1Qix5QkFBcUIsMEJBQTBCLHNCQUFzQjtBQUNyRSxXQUFPO0FBQUEsRUFDVDtBQUFBLEVBQ0EsbUJBQW1CLENBQUMsa0JBQWtCO0FBQ3BDLFFBQUksa0JBQWtCO0FBQ3BCLFlBQU0sSUFBSSxNQUFNLG1DQUFtQztBQUFBLElBQ3JEO0FBQ0EsUUFBSSwwQkFBMEI7QUFDNUIsWUFBTSxJQUFJLE1BQU0sNERBQTREO0FBQUEsSUFDOUU7QUFFQSx1QkFBbUI7QUFDbkIseUJBQXFCLGlCQUFpQixhQUFhO0FBQ25ELFdBQU87QUFBQSxFQUNUO0FBQUEsRUFDQSxlQUFlLENBQUMsY0FBYztBQUM1QixRQUFJLGNBQWM7QUFDaEIsWUFBTSxJQUFJLE1BQU0sOEJBQThCO0FBQUEsSUFDaEQ7QUFFQSxtQkFBZTtBQUNmLHlCQUFxQixhQUFhLFNBQVM7QUFDM0MsV0FBTztBQUFBLEVBQ1Q7QUFDRjtBQUVBLHdEQUE0QixLQUFLLE9BQU1BLFlBQVU7QUFDL0MsU0FBTyxNQUFNQSxRQUFPLEtBQUssYUFBYTtBQUN4QyxDQUFDLEVBQUUsS0FBSyxNQUFNO0FBQ1osdUJBQXFCLGNBQWM7QUFDckMsQ0FBQyxFQUFFLE1BQU0sQ0FBQyxVQUFVO0FBQ2xCLFVBQVEsTUFBTSxvREFBb0Q7QUFDbEUsVUFBUSxNQUFNLEtBQUs7QUFDckIsQ0FBQzsiLAogICJuYW1lcyI6IFsibW9kdWxlIl0KfQo=
