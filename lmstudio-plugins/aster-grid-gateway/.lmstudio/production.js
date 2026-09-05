var __defProp = Object.defineProperty;
var __getOwnPropNames = Object.getOwnPropertyNames;
var __esm = (fn, res) => function __init() {
  return fn && (res = (0, fn[__getOwnPropNames(fn)[0]])(fn = 0)), res;
};
var __export = (target, all) => {
  for (var name in all)
    __defProp(target, name, { get: all[name], enumerable: true });
};

// Users/ciciwang/Projects/demo/lmstudio-plugins/aster-grid-gateway/src/index.ts
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
  "Users/ciciwang/Projects/demo/lmstudio-plugins/aster-grid-gateway/src/index.ts"() {
    import_node_fs = require("node:fs");
    import_node_path = require("node:path");
    GATEWAY_URL = process.env.ASTER_GATEWAY_URL?.trim() || "http://127.0.0.1:8501/v1/chat/completions";
    MODEL = process.env.ASTER_GATEWAY_MODEL?.trim() || "demo/aster";
    SYSTEM_PROMPT = loadSystemPrompt();
  }
});

// Users/ciciwang/Projects/demo/lmstudio-plugins/aster-grid-gateway/.lmstudio/entry.ts
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
//# sourceMappingURL=data:application/json;base64,ewogICJ2ZXJzaW9uIjogMywKICAic291cmNlcyI6IFsiLi4vLi4vLi4vLi4vLi4vLi4vUHJvamVjdHMvZGVtby9sbXN0dWRpby1wbHVnaW5zL2FzdGVyLWdyaWQtZ2F0ZXdheS9zcmMvaW5kZXgudHMiLCAiLi4vLi4vLi4vLi4vLi4vLi4vUHJvamVjdHMvZGVtby9sbXN0dWRpby1wbHVnaW5zL2FzdGVyLWdyaWQtZ2F0ZXdheS8ubG1zdHVkaW8vZW50cnkudHMiXSwKICAic291cmNlc0NvbnRlbnQiOiBbImltcG9ydCB7IHJlYWRGaWxlU3luYyB9IGZyb20gXCJub2RlOmZzXCI7XG5pbXBvcnQgeyBqb2luIH0gZnJvbSBcIm5vZGU6cGF0aFwiO1xuaW1wb3J0IHR5cGUgeyBQbHVnaW5Db250ZXh0IH0gZnJvbSBcIkBsbXN0dWRpby9zZGtcIjtcblxuY29uc3QgR0FURVdBWV9VUkwgPVxuICBwcm9jZXNzLmVudi5BU1RFUl9HQVRFV0FZX1VSTD8udHJpbSgpIHx8IFwiaHR0cDovLzEyNy4wLjAuMTo4NTAxL3YxL2NoYXQvY29tcGxldGlvbnNcIjtcbmNvbnN0IE1PREVMID0gcHJvY2Vzcy5lbnYuQVNURVJfR0FURVdBWV9NT0RFTD8udHJpbSgpIHx8IFwiZGVtby9hc3RlclwiO1xuXG5mdW5jdGlvbiBsb2FkU3lzdGVtUHJvbXB0KCk6IHN0cmluZyB7XG4gIGNvbnN0IGZyb21FbnYgPSBwcm9jZXNzLmVudi5BU1RFUl9DSEFUX1NZU1RFTV9QUk9NUFQ/LnRyaW0oKTtcbiAgaWYgKGZyb21FbnYpIHtcbiAgICByZXR1cm4gZnJvbUVudjtcbiAgfVxuICBjb25zdCBjYW5kaWRhdGVzID0gW1xuICAgIGpvaW4oX19kaXJuYW1lLCBcIi4uXCIsIFwiLmFzdGVyX3N5c3RlbV9wcm9tcHRcIiksXG4gICAgam9pbihfX2Rpcm5hbWUsIFwiLmFzdGVyX3N5c3RlbV9wcm9tcHRcIiksXG4gIF07XG4gIGZvciAoY29uc3QgcGF0aCBvZiBjYW5kaWRhdGVzKSB7XG4gICAgdHJ5IHtcbiAgICAgIGNvbnN0IHRleHQgPSByZWFkRmlsZVN5bmMocGF0aCwgXCJ1dGY4XCIpLnRyaW0oKTtcbiAgICAgIGlmICh0ZXh0KSB7XG4gICAgICAgIHJldHVybiB0ZXh0O1xuICAgICAgfVxuICAgIH0gY2F0Y2gge1xuICAgICAgLyogdHJ5IG5leHQgKi9cbiAgICB9XG4gIH1cbiAgcmV0dXJuIFwiXCI7XG59XG5cbmNvbnN0IFNZU1RFTV9QUk9NUFQgPSBsb2FkU3lzdGVtUHJvbXB0KCk7XG5cbmZ1bmN0aW9uIHdpdGhTeXN0ZW1Qcm9tcHQobWVzc2FnZXM6IEFycmF5PHsgcm9sZTogc3RyaW5nOyBjb250ZW50OiBzdHJpbmcgfT4pIHtcbiAgaWYgKCFTWVNURU1fUFJPTVBUKSB7XG4gICAgcmV0dXJuIG1lc3NhZ2VzO1xuICB9XG4gIGlmIChtZXNzYWdlcy5zb21lKChtKSA9PiBtLnJvbGUgPT09IFwic3lzdGVtXCIgJiYgbS5jb250ZW50LnRyaW0oKSkpIHtcbiAgICByZXR1cm4gbWVzc2FnZXM7XG4gIH1cbiAgcmV0dXJuIFt7IHJvbGU6IFwic3lzdGVtXCIsIGNvbnRlbnQ6IFNZU1RFTV9QUk9NUFQgfSwgLi4ubWVzc2FnZXNdO1xufVxuXG5leHBvcnQgYXN5bmMgZnVuY3Rpb24gbWFpbihjdHg6IFBsdWdpbkNvbnRleHQpOiBQcm9taXNlPHZvaWQ+IHtcbiAgY3R4LndpdGhHZW5lcmF0b3IoYXN5bmMgKGN0bCwgaGlzdG9yeSkgPT4ge1xuICAgIGNvbnN0IG1lc3NhZ2VzOiBBcnJheTx7IHJvbGU6IHN0cmluZzsgY29udGVudDogc3RyaW5nIH0+ID0gW107XG4gICAgZm9yIChjb25zdCB0dXJuIG9mIGhpc3RvcnkpIHtcbiAgICAgIGNvbnN0IHJvbGUgPSB0dXJuLmdldFJvbGU/LigpID8/ICh0dXJuIGFzIHsgcm9sZT86IHN0cmluZyB9KS5yb2xlID8/IFwidXNlclwiO1xuICAgICAgY29uc3QgY29udGVudCA9IHR1cm4uZ2V0VGV4dD8uKCkgPz8gU3RyaW5nKCh0dXJuIGFzIHsgY29udGVudD86IHN0cmluZyB9KS5jb250ZW50ID8/IFwiXCIpO1xuICAgICAgaWYgKCFjb250ZW50LnRyaW0oKSkge1xuICAgICAgICBjb250aW51ZTtcbiAgICAgIH1cbiAgICAgIG1lc3NhZ2VzLnB1c2goeyByb2xlLCBjb250ZW50IH0pO1xuICAgIH1cbiAgICBpZiAobWVzc2FnZXMubGVuZ3RoID09PSAwKSB7XG4gICAgICBjdGwuZnJhZ21lbnRHZW5lcmF0ZWQoXCJbZ2F0ZXdheV0gZW1wdHkgaGlzdG9yeVwiKTtcbiAgICAgIHJldHVybjtcbiAgICB9XG5cbiAgICBjb25zdCBwYXlsb2FkID0gd2l0aFN5c3RlbVByb21wdChtZXNzYWdlcyk7XG4gICAgY29uc3QgcmVzcCA9IGF3YWl0IGZldGNoKEdBVEVXQVlfVVJMLCB7XG4gICAgICBtZXRob2Q6IFwiUE9TVFwiLFxuICAgICAgaGVhZGVyczogeyBcIkNvbnRlbnQtVHlwZVwiOiBcImFwcGxpY2F0aW9uL2pzb25cIiB9LFxuICAgICAgYm9keTogSlNPTi5zdHJpbmdpZnkoe1xuICAgICAgICBtb2RlbDogTU9ERUwsXG4gICAgICAgIG1lc3NhZ2VzOiBwYXlsb2FkLFxuICAgICAgICBtYXhfdG9rZW5zOiA0MDAsXG4gICAgICAgIHRlbXBlcmF0dXJlOiAwLjcsXG4gICAgICAgIHN0cmVhbTogZmFsc2UsXG4gICAgICB9KSxcbiAgICB9KTtcbiAgICBpZiAoIXJlc3Aub2spIHtcbiAgICAgIGNvbnN0IGVyclRleHQgPSBhd2FpdCByZXNwLnRleHQoKTtcbiAgICAgIHRocm93IG5ldyBFcnJvcihgZ2F0ZXdheSAke3Jlc3Auc3RhdHVzfTogJHtlcnJUZXh0LnNsaWNlKDAsIDI0MCl9YCk7XG4gICAgfVxuICAgIGNvbnN0IGRhdGEgPSAoYXdhaXQgcmVzcC5qc29uKCkpIGFzIHtcbiAgICAgIHNlcnZlZF9ieT86IHN0cmluZztcbiAgICAgIHJlc3BvbnNlPzogc3RyaW5nO1xuICAgICAgY2hvaWNlcz86IEFycmF5PHsgbWVzc2FnZT86IHsgY29udGVudD86IHN0cmluZyB9IH0+O1xuICAgIH07XG4gICAgY29uc3QgdGV4dCA9XG4gICAgICBkYXRhLmNob2ljZXM/LlswXT8ubWVzc2FnZT8uY29udGVudD8udHJpbSgpIHx8XG4gICAgICBTdHJpbmcoZGF0YS5yZXNwb25zZSB8fCBcIlwiKS50cmltKCkgfHxcbiAgICAgIFwiW2dhdGV3YXldIGVtcHR5IHJlc3BvbnNlXCI7XG4gICAgY3RsLmZyYWdtZW50R2VuZXJhdGVkKHRleHQpO1xuICB9KTtcbn1cbiIsICJpbXBvcnQgeyBMTVN0dWRpb0NsaWVudCwgdHlwZSBQbHVnaW5Db250ZXh0IH0gZnJvbSBcIkBsbXN0dWRpby9zZGtcIjtcblxuZGVjbGFyZSB2YXIgcHJvY2VzczogYW55O1xuXG4vLyBXZSByZWNlaXZlIHJ1bnRpbWUgaW5mb3JtYXRpb24gaW4gdGhlIGVudmlyb25tZW50IHZhcmlhYmxlcy5cbmNvbnN0IGNsaWVudElkZW50aWZpZXIgPSBwcm9jZXNzLmVudi5MTVNfUExVR0lOX0NMSUVOVF9JREVOVElGSUVSO1xuY29uc3QgY2xpZW50UGFzc2tleSA9IHByb2Nlc3MuZW52LkxNU19QTFVHSU5fQ0xJRU5UX1BBU1NLRVk7XG5jb25zdCBiYXNlVXJsID0gcHJvY2Vzcy5lbnYuTE1TX1BMVUdJTl9CQVNFX1VSTDtcblxuY29uc3QgY2xpZW50ID0gbmV3IExNU3R1ZGlvQ2xpZW50KHtcbiAgY2xpZW50SWRlbnRpZmllcixcbiAgY2xpZW50UGFzc2tleSxcbiAgYmFzZVVybCxcbn0pO1xuXG4oZ2xvYmFsVGhpcyBhcyBhbnkpLl9fTE1TX1BMVUdJTl9DT05URVhUID0gdHJ1ZTtcblxubGV0IHByZWRpY3Rpb25Mb29wSGFuZGxlclNldCA9IGZhbHNlO1xubGV0IHByb21wdFByZXByb2Nlc3NvclNldCA9IGZhbHNlO1xubGV0IGNvbmZpZ1NjaGVtYXRpY3NTZXQgPSBmYWxzZTtcbmxldCBnbG9iYWxDb25maWdTY2hlbWF0aWNzU2V0ID0gZmFsc2U7XG5sZXQgdG9vbHNQcm92aWRlclNldCA9IGZhbHNlO1xubGV0IGdlbmVyYXRvclNldCA9IGZhbHNlO1xuXG5jb25zdCBzZWxmUmVnaXN0cmF0aW9uSG9zdCA9IGNsaWVudC5wbHVnaW5zLmdldFNlbGZSZWdpc3RyYXRpb25Ib3N0KCk7XG5cbmNvbnN0IHBsdWdpbkNvbnRleHQ6IFBsdWdpbkNvbnRleHQgPSB7XG4gIHdpdGhQcmVkaWN0aW9uTG9vcEhhbmRsZXI6IChnZW5lcmF0ZSkgPT4ge1xuICAgIGlmIChwcmVkaWN0aW9uTG9vcEhhbmRsZXJTZXQpIHtcbiAgICAgIHRocm93IG5ldyBFcnJvcihcIlByZWRpY3Rpb25Mb29wSGFuZGxlciBhbHJlYWR5IHJlZ2lzdGVyZWRcIik7XG4gICAgfVxuICAgIGlmICh0b29sc1Byb3ZpZGVyU2V0KSB7XG4gICAgICB0aHJvdyBuZXcgRXJyb3IoXCJQcmVkaWN0aW9uTG9vcEhhbmRsZXIgY2Fubm90IGJlIHVzZWQgd2l0aCBhIHRvb2xzIHByb3ZpZGVyXCIpO1xuICAgIH1cblxuICAgIHByZWRpY3Rpb25Mb29wSGFuZGxlclNldCA9IHRydWU7XG4gICAgc2VsZlJlZ2lzdHJhdGlvbkhvc3Quc2V0UHJlZGljdGlvbkxvb3BIYW5kbGVyKGdlbmVyYXRlKTtcbiAgICByZXR1cm4gcGx1Z2luQ29udGV4dDtcbiAgfSxcbiAgd2l0aFByb21wdFByZXByb2Nlc3NvcjogKHByZXByb2Nlc3MpID0+IHtcbiAgICBpZiAocHJvbXB0UHJlcHJvY2Vzc29yU2V0KSB7XG4gICAgICB0aHJvdyBuZXcgRXJyb3IoXCJQcm9tcHRQcmVwcm9jZXNzb3IgYWxyZWFkeSByZWdpc3RlcmVkXCIpO1xuICAgIH1cbiAgICBwcm9tcHRQcmVwcm9jZXNzb3JTZXQgPSB0cnVlO1xuICAgIHNlbGZSZWdpc3RyYXRpb25Ib3N0LnNldFByb21wdFByZXByb2Nlc3NvcihwcmVwcm9jZXNzKTtcbiAgICByZXR1cm4gcGx1Z2luQ29udGV4dDtcbiAgfSxcbiAgd2l0aENvbmZpZ1NjaGVtYXRpY3M6IChjb25maWdTY2hlbWF0aWNzKSA9PiB7XG4gICAgaWYgKGNvbmZpZ1NjaGVtYXRpY3NTZXQpIHtcbiAgICAgIHRocm93IG5ldyBFcnJvcihcIkNvbmZpZyBzY2hlbWF0aWNzIGFscmVhZHkgcmVnaXN0ZXJlZFwiKTtcbiAgICB9XG4gICAgY29uZmlnU2NoZW1hdGljc1NldCA9IHRydWU7XG4gICAgc2VsZlJlZ2lzdHJhdGlvbkhvc3Quc2V0Q29uZmlnU2NoZW1hdGljcyhjb25maWdTY2hlbWF0aWNzKTtcbiAgICByZXR1cm4gcGx1Z2luQ29udGV4dDtcbiAgfSxcbiAgd2l0aEdsb2JhbENvbmZpZ1NjaGVtYXRpY3M6IChnbG9iYWxDb25maWdTY2hlbWF0aWNzKSA9PiB7XG4gICAgaWYgKGdsb2JhbENvbmZpZ1NjaGVtYXRpY3NTZXQpIHtcbiAgICAgIHRocm93IG5ldyBFcnJvcihcIkdsb2JhbCBjb25maWcgc2NoZW1hdGljcyBhbHJlYWR5IHJlZ2lzdGVyZWRcIik7XG4gICAgfVxuICAgIGdsb2JhbENvbmZpZ1NjaGVtYXRpY3NTZXQgPSB0cnVlO1xuICAgIHNlbGZSZWdpc3RyYXRpb25Ib3N0LnNldEdsb2JhbENvbmZpZ1NjaGVtYXRpY3MoZ2xvYmFsQ29uZmlnU2NoZW1hdGljcyk7XG4gICAgcmV0dXJuIHBsdWdpbkNvbnRleHQ7XG4gIH0sXG4gIHdpdGhUb29sc1Byb3ZpZGVyOiAodG9vbHNQcm92aWRlcikgPT4ge1xuICAgIGlmICh0b29sc1Byb3ZpZGVyU2V0KSB7XG4gICAgICB0aHJvdyBuZXcgRXJyb3IoXCJUb29scyBwcm92aWRlciBhbHJlYWR5IHJlZ2lzdGVyZWRcIik7XG4gICAgfVxuICAgIGlmIChwcmVkaWN0aW9uTG9vcEhhbmRsZXJTZXQpIHtcbiAgICAgIHRocm93IG5ldyBFcnJvcihcIlRvb2xzIHByb3ZpZGVyIGNhbm5vdCBiZSB1c2VkIHdpdGggYSBwcmVkaWN0aW9uTG9vcEhhbmRsZXJcIik7XG4gICAgfVxuXG4gICAgdG9vbHNQcm92aWRlclNldCA9IHRydWU7XG4gICAgc2VsZlJlZ2lzdHJhdGlvbkhvc3Quc2V0VG9vbHNQcm92aWRlcih0b29sc1Byb3ZpZGVyKTtcbiAgICByZXR1cm4gcGx1Z2luQ29udGV4dDtcbiAgfSxcbiAgd2l0aEdlbmVyYXRvcjogKGdlbmVyYXRvcikgPT4ge1xuICAgIGlmIChnZW5lcmF0b3JTZXQpIHtcbiAgICAgIHRocm93IG5ldyBFcnJvcihcIkdlbmVyYXRvciBhbHJlYWR5IHJlZ2lzdGVyZWRcIik7XG4gICAgfVxuXG4gICAgZ2VuZXJhdG9yU2V0ID0gdHJ1ZTtcbiAgICBzZWxmUmVnaXN0cmF0aW9uSG9zdC5zZXRHZW5lcmF0b3IoZ2VuZXJhdG9yKTtcbiAgICByZXR1cm4gcGx1Z2luQ29udGV4dDtcbiAgfSxcbn07XG5cbmltcG9ydChcIi4vLi4vc3JjL2luZGV4LnRzXCIpLnRoZW4oYXN5bmMgbW9kdWxlID0+IHtcbiAgcmV0dXJuIGF3YWl0IG1vZHVsZS5tYWluKHBsdWdpbkNvbnRleHQpO1xufSkudGhlbigoKSA9PiB7XG4gIHNlbGZSZWdpc3RyYXRpb25Ib3N0LmluaXRDb21wbGV0ZWQoKTtcbn0pLmNhdGNoKChlcnJvcikgPT4ge1xuICBjb25zb2xlLmVycm9yKFwiRmFpbGVkIHRvIGV4ZWN1dGUgdGhlIG1haW4gZnVuY3Rpb24gb2YgdGhlIHBsdWdpbi5cIik7XG4gIGNvbnNvbGUuZXJyb3IoZXJyb3IpO1xufSk7XG4iXSwKICAibWFwcGluZ3MiOiAiOzs7Ozs7Ozs7OztBQUFBO0FBQUE7QUFBQTtBQUFBO0FBUUEsU0FBUyxtQkFBMkI7QUFDbEMsUUFBTSxVQUFVLFFBQVEsSUFBSSwwQkFBMEIsS0FBSztBQUMzRCxNQUFJLFNBQVM7QUFDWCxXQUFPO0FBQUEsRUFDVDtBQUNBLFFBQU0sYUFBYTtBQUFBLFFBQ2pCLHVCQUFLLFdBQVcsTUFBTSxzQkFBc0I7QUFBQSxRQUM1Qyx1QkFBSyxXQUFXLHNCQUFzQjtBQUFBLEVBQ3hDO0FBQ0EsYUFBVyxRQUFRLFlBQVk7QUFDN0IsUUFBSTtBQUNGLFlBQU0sV0FBTyw2QkFBYSxNQUFNLE1BQU0sRUFBRSxLQUFLO0FBQzdDLFVBQUksTUFBTTtBQUNSLGVBQU87QUFBQSxN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LFlBQU0sSUFBSSxNQUFNLDREQUE0RDtBQUFBLElBQzlFO0FBRUEsK0JBQTJCO0FBQzNCLHlCQUFxQix5QkFBeUIsUUFBUTtBQUN0RCxXQUFPO0FBQUEsRUFDVDtBQUFBLEVBQ0Esd0JBQXdCLENBQUMsZUFBZTtBQUN0QyxRQUFJLHVCQUF1QjtBQUN6QixZQUFNLElBQUksTUFBTSx1Q0FBdUM7QUFBQSxJQUN6RDtBQUNBLDRCQUF3QjtBQUN4Qix5QkFBcUIsc0JBQXNCLFVBQVU7QUFDckQsV0FBTztBQUFBLEVBQ1Q7QUFBQSxFQUNBLHNCQUFzQixDQUFDLHFCQUFxQjtBQUMxQyxRQUFJLHFCQUFxQjtBQUN2QixZQUFNLElBQUksTUFBTSxzQ0FBc0M7QUFBQSxJQUN4RDtBQUNBLDBCQUFzQjtBQUN0Qix5QkFBcUIsb0JBQW9CLGdCQUFnQjtBQUN6RCxXQUFPO0FBQUEsRUFDVDtBQUFBLEVBQ0EsNEJBQTRCLENBQUMsMkJBQTJCO0FBQ3RELFFBQUksMkJBQTJCO0FBQzdCLFlBQU0sSUFBSSxNQUFNLDZDQUE2QztBQUFBLElBQy9EO0FBQ0EsZ0NBQTRCO0FBQzVCLHlCQUFxQiwwQkFBMEIsc0JBQXNCO0FBQ3JFLFdBQU87QUFBQSxFQUNUO0FBQUEsRUFDQSxtQkFBbUIsQ0FBQyxrQkFBa0I7QUFDcEMsUUFBSSxrQkFBa0I7QUFDcEIsWUFBTSxJQUFJLE1BQU0sbUNBQW1DO0FBQUEsSUFDckQ7QUFDQSxRQUFJLDBCQUEwQjtBQUM1QixZQUFNLElBQUksTUFBTSw0REFBNEQ7QUFBQSxJQUM5RTtBQUVBLHVCQUFtQjtBQUNuQix5QkFBcUIsaUJBQWlCLGFBQWE7QUFDbkQsV0FBTztBQUFBLEVBQ1Q7QUFBQSxFQUNBLGVBQWUsQ0FBQyxjQUFjO0FBQzVCLFFBQUksY0FBYztBQUNoQixZQUFNLElBQUksTUFBTSw4QkFBOEI7QUFBQSxJQUNoRDtBQUVBLG1CQUFlO0FBQ2YseUJBQXFCLGFBQWEsU0FBUztBQUMzQyxXQUFPO0FBQUEsRUFDVDtBQUNGO0FBRUEsd0RBQTRCLEtBQUssT0FBTUEsWUFBVTtBQUMvQyxTQUFPLE1BQU1BLFFBQU8sS0FBSyxhQUFhO0FBQ3hDLENBQUMsRUFBRSxLQUFLLE1BQU07QUFDWix1QkFBcUIsY0FBYztBQUNyQyxDQUFDLEVBQUUsTUFBTSxDQUFDLFVBQVU7QUFDbEIsVUFBUSxNQUFNLG9EQUFvRDtBQUNsRSxVQUFRLE1BQU0sS0FBSztBQUNyQixDQUFDOyIsCiAgIm5hbWVzIjogWyJtb2R1bGUiXQp9Cg==
