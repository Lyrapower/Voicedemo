#!/usr/bin/env node
/* TCP 127.0.0.1:11434 -> /bridge/model.sock. Lives in cc netns only. */
const net = require("net");
const SOCK = process.env.MODEL_SOCK || "/bridge/model.sock";
const PORT = Number(process.env.MODEL_RELAY_PORT || 11434);
const server = net.createServer((client) => {
  const up = net.connect(SOCK);
  const die = () => {
    try { client.destroy(); } catch (e) {}
    try { up.destroy(); } catch (e) {}
  };
  client.pipe(up);
  up.pipe(client);
  client.on("error", die);
  up.on("error", die);
  client.on("close", die);
  up.on("close", die);
});
server.on("error", (err) => {
  process.stderr.write(String(err) + "\n");
  process.exit(1);
});
server.listen(PORT, "127.0.0.1");
