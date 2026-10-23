class DominoMcpClient {
  constructor(endpoint = "/mcp") {
    this.endpoint = endpoint;
    this.sessionId = null;
    this.protocolVersion = null;
    this.requestId = 0;
    this.ready = false;
    this.connection = null;
    this.listeners = new Set();
  }

  onStatusChange(listener) {
    this.listeners.add(listener);
    listener(this.ready);
    return () => this.listeners.delete(listener);
  }

  setReady(ready) {
    this.ready = ready;
    this.listeners.forEach((listener) => listener(ready));
  }

  async post(message) {
    const headers = new Headers({
      Accept: "application/json, text/event-stream",
      "Content-Type": "application/json",
    });
    if (this.sessionId) headers.set("MCP-Session-Id", this.sessionId);
    if (this.protocolVersion) headers.set("MCP-Protocol-Version", this.protocolVersion);

    const response = await fetch(this.endpoint, {
      method: "POST",
      headers,
      body: JSON.stringify(message),
    });
    const sessionId = response.headers.get("Mcp-Session-Id");
    if (sessionId) this.sessionId = sessionId;
    if (!response.ok) {
      const detail = (await response.text()).slice(0, 240);
      throw new Error(`MCP server returned HTTP ${response.status}${detail ? `: ${detail}` : ""}`);
    }
    if (response.status === 202 || message.method?.startsWith("notifications/")) return null;

    const body = await response.text();
    const result = this.parseResponse(body, response.headers.get("Content-Type"), message.id);
    if (result.error) throw new Error(result.error.message || "The MCP server rejected the request.");
    return result.result;
  }

  parseResponse(body, contentType, expectedId) {
    const candidates = [];
    if (contentType?.includes("text/event-stream")) {
      for (const event of body.split(/\r?\n\r?\n/)) {
        const data = event
          .split(/\r?\n/)
          .filter((line) => line.startsWith("data:"))
          .map((line) => line.slice(5).trim())
          .join("\n");
        if (data && data !== "[DONE]") candidates.push(data);
      }
    } else if (body.trim()) {
      candidates.push(body.trim());
    }

    for (const candidate of candidates) {
      let parsed;
      try {
        parsed = JSON.parse(candidate);
      } catch (error) {
        throw new Error("MCP server returned an invalid JSON-RPC response.");
      }
      if (parsed.id === expectedId) return parsed;
    }
    throw new Error("MCP server did not return a response for the request.");
  }

  async connect() {
    if (this.ready) return { protocolVersion: this.protocolVersion };
    if (this.connection) return this.connection;

    this.setReady(false);
    this.sessionId = null;
    this.protocolVersion = null;
    this.connection = (async () => {
      try {
        const response = await this.post({
          jsonrpc: "2.0",
          id: ++this.requestId,
          method: "initialize",
          params: {
            protocolVersion: "2025-11-25",
            capabilities: {},
            clientInfo: { name: "Ripple Web Demo", version: "1.0.0" },
          },
        });
        this.protocolVersion = response.protocolVersion;
        await this.post({ jsonrpc: "2.0", method: "notifications/initialized" });
        this.setReady(true);
        return response;
      } catch (error) {
        this.sessionId = null;
        this.protocolVersion = null;
        this.setReady(false);
        throw error;
      } finally {
        this.connection = null;
      }
    })();
    return this.connection;
  }

  async callTool(name, args) {
    if (!this.ready) await this.connect();
    try {
      const result = await this.post({
        jsonrpc: "2.0",
        id: ++this.requestId,
        method: "tools/call",
        params: { name, arguments: args },
      });
      if (result.isError) {
        throw new Error(result.content?.map((item) => item.text).filter(Boolean).join("\n") || "MCP tool call failed.");
      }
      const text = result.content?.map((item) => item.text).filter(Boolean).join("\n");
      if (!text) throw new Error("MCP tool returned no response text.");
      return text;
    } catch (error) {
      this.setReady(false);
      throw error;
    }
  }

  async listTools() {
    if (!this.ready) await this.connect();
    try {
      const result = await this.post({
        jsonrpc: "2.0",
        id: ++this.requestId,
        method: "tools/list",
        params: {},
      });
      return result.tools || [];
    } catch (error) {
      this.setReady(false);
      throw error;
    }
  }
}

window.dominoMcp = new DominoMcpClient();
