const assert = require("node:assert/strict");
const http = require("node:http");
const test = require("node:test");

const hubClient = require("../lib/hub-client");

function withServer(handler, fn) {
  return new Promise((resolve, reject) => {
    const server = http.createServer(handler);
    server.listen(0, "127.0.0.1", async () => {
      const { port } = server.address();
      try {
        await fn(`http://127.0.0.1:${port}`);
        resolve();
      } catch (err) {
        reject(err);
      } finally {
        server.close();
      }
    });
  });
}

test("request() sends no Authorization header when no token is configured", async () => {
  let seen;
  await withServer(
    (req, res) => {
      seen = req.headers.authorization;
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end("{}");
    },
    async (baseUrl) => {
      await hubClient.request("/api/services", { baseUrl });
    }
  );
  assert.equal(seen, undefined);
});

test("request() sends the token as a Bearer Authorization header when one is given", async () => {
  let seen;
  await withServer(
    (req, res) => {
      seen = req.headers.authorization;
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end("{}");
    },
    async (baseUrl) => {
      await hubClient.request("/api/services", { baseUrl, token: "secret-token" });
    }
  );
  assert.equal(seen, "Bearer secret-token");
});

test("request() surfaces the server's hint on a 401", async () => {
  await withServer(
    (req, res) => {
      res.writeHead(401, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ error: "authentication required", hint: "mint a token first" }));
    },
    async (baseUrl) => {
      await assert.rejects(hubClient.request("/api/services", { baseUrl }), (err) => {
        assert.equal(err.status, 401);
        assert.equal(err.body.hint, "mint a token first");
        return true;
      });
    }
  );
});

test("requestStream() sends the token as a Bearer Authorization header too", async () => {
  let seen;
  await withServer(
    (req, res) => {
      seen = req.headers.authorization;
      res.writeHead(200, { "Content-Type": "text/event-stream" });
      res.end('data: {"type":"done","result":{"answer":"ok"}}\n\n');
    },
    async (baseUrl) => {
      const events = [];
      await hubClient.requestStream("/api/services/coding/run/stream", { baseUrl, token: "secret-token", body: {} }, (e) =>
        events.push(e)
      );
      assert.equal(events[0].result.answer, "ok");
    }
  );
  assert.equal(seen, "Bearer secret-token");
});

test("requestStream() rejects with the parsed error body on a non-2xx status", async () => {
  await withServer(
    (req, res) => {
      res.writeHead(403, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ error: "forbidden" }));
    },
    async (baseUrl) => {
      await assert.rejects(
        hubClient.requestStream("/api/services/coding/run/stream", { baseUrl, body: {} }, () => {}),
        /forbidden/
      );
    }
  );
});
