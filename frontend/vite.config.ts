import path from "node:path";

import react from "@vitejs/plugin-react";
import { defineConfig, loadEnv, type ProxyOptions } from "vite";

const FRONTEND_DIR = __dirname;
const REPO_DIR = path.resolve(__dirname, "..");

/**
 * Where the dev server sends `/api`.
 *
 * One source of truth: the repository `.env` publishes the backend on
 * `BACKEND_HOST_PORT` (docker compose uses the same value), so a frontend run
 * from the host reaches the same backend as the containerised one. An explicit
 * `VITE_PROXY_TARGET` always wins — docker compose sets it to the service name
 * (`http://backend:8000`) because container ports are not host ports.
 *
 * Getting this wrong is invisible in the UI and shows up as a confusing 404 or
 * 500 from whatever else happens to own the port, so the target is announced at
 * startup and probed (see below).
 */
function resolveProxyTarget(mode: string): string {
  const explicit = process.env.VITE_PROXY_TARGET;
  if (explicit) return explicit;

  // The repo `.env` is authoritative for host ports. Read it with an empty
  // prefix so a non-`VITE_` name like BACKEND_HOST_PORT is visible here; only
  // `VITE_`-prefixed values are ever exposed to the client.
  const repoEnv = loadEnv(mode, REPO_DIR, "");
  const fromRepo = repoEnv.VITE_PROXY_TARGET;
  if (fromRepo) return fromRepo;

  const port = repoEnv.BACKEND_HOST_PORT || "8000";
  // 127.0.0.1 (not "localhost") so the proxy never resolves to an IPv6 host that
  // another service may be bound to.
  return `http://127.0.0.1:${port}`;
}

/**
 * Fail loudly when `/api` is pointed at something that is not the CheckR API.
 * A foreign service on the same port answers with its own 404/500 shape, which
 * looks like "the login endpoint is missing" rather than "wrong port".
 */
function backendProbe(target: string): { name: string; configureServer: (s: any) => void } {
  return {
    name: "checkr:backend-probe",
    configureServer(server) {
      const probe = async () => {
        server.config.logger.info(`  ➜  /api        proxied to ${target}`);
        const health = `${target.replace(/\/$/, "")}/api/health`;
        try {
          const res = await fetch(health, { signal: AbortSignal.timeout(4000) });
          const body = (await res.json().catch(() => null)) as { app?: string } | null;
          if (!res.ok || body?.app !== "CheckR") {
            server.config.logger.warn(
              `\n  [checkr] ${health} did not answer as the CheckR API` +
                `${body?.app ? ` (found "${body.app}")` : ` (HTTP ${res.status})`}.\n` +
                `  [checkr] Something else is listening on that port. Start the CheckR ` +
                `backend or point the proxy elsewhere:\n` +
                `  [checkr]   VITE_PROXY_TARGET=http://127.0.0.1:<port> npm run dev\n`,
            );
          }
        } catch {
          server.config.logger.warn(
            `\n  [checkr] No CheckR API reachable at ${health}.\n` +
              `  [checkr] Start it (docker compose up -d backend, or uvicorn on the ` +
              `port named by BACKEND_HOST_PORT) or override VITE_PROXY_TARGET.\n`,
          );
        }
      };

      if (server.httpServer?.listening) void probe();
      else if (server.httpServer) server.httpServer.once("listening", () => void probe());
      else void probe();
    },
  };
}

export default defineConfig(({ mode }) => {
  const target = resolveProxyTarget(mode);

  const proxy: Record<string, ProxyOptions> = {
    "/api": {
      target,
      changeOrigin: true,
      configure(proxy) {
        proxy.on("error", (err: Error, _req, res: any) => {
          // The default Vite handler prints a bare stack trace; say what to do.
          console.error(
            `\n  [checkr] /api proxy error talking to ${target}: ${err.message}\n` +
              `  [checkr] Is the CheckR backend running on that port? Override with ` +
              `VITE_PROXY_TARGET if not.\n`,
          );
          if (res && typeof res.writeHead === "function" && !res.headersSent) {
            res.writeHead(503, { "Content-Type": "application/json" });
            res.end(
              JSON.stringify({
                detail: `Cannot reach backend API at ${target}. Please ensure the CheckR backend container or server is running. (${err.message})`,
              }),
            );
          }
        });
      },
    },
  };

  return {
    plugins: [react(), backendProbe(target)],
    resolve: {
      alias: { "@": path.resolve(FRONTEND_DIR, "src") },
    },
    server: {
      host: true,
      port: 5173,
      proxy,
    },
    // `vite preview` serves the production bundle; keep `/api` wired to the same
    // backend so a build can be verified without a separate reverse proxy.
    preview: {
      host: true,
      port: 4173,
      proxy,
    },
  };
});
