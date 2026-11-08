/**
 * Official Streamable HTTP client. Token comes from the environment and is
 * not printed. Dummy mail credentials are not used here.
 */
import { Client, StreamableHTTPClientTransport } from "@modelcontextprotocol/client";

const token = process.env.MCP_HTTP_TOKEN;
const url = process.env.MCP_URL;
const era = process.env.MCP_ERA || "legacy";
if (!token || !url) {
  console.error("missing MCP_URL or MCP_HTTP_TOKEN");
  process.exit(2);
}
const options = era === "modern" ? { versionNegotiation: { mode: { pin: "2026-07-28" } } } : undefined;
const transport = new StreamableHTTPClientTransport(new URL(url), {
  authProvider: { token: async () => token },
});
const client = new Client({ name: "http-roundtrip", version: "0.0.0" }, options);
try {
  await client.connect(transport);
  const listed = await client.listTools();
  const names = listed.tools.map((tool) => tool.name).sort();
  process.stdout.write(
    JSON.stringify({
      era: client.getProtocolEra(),
      count: names.length,
      names,
    }) + "\n",
  );
} finally {
  await client.close();
}
