import { afterEach, describe, expect, it, vi } from "vitest";

import { buildApiUrl, normalizeApiBase } from "./api";

describe("normalizeApiBase", () => {
  it("defaults to a same-origin /api prefix", () => {
    expect(normalizeApiBase(undefined)).toBe("/api");
    expect(normalizeApiBase("")).toBe("/api");
    expect(normalizeApiBase("/")).toBe("/api");
    expect(normalizeApiBase("  ")).toBe("/api");
  });

  it("appends /api to an origin", () => {
    expect(normalizeApiBase("http://127.0.0.1:8000")).toBe("http://127.0.0.1:8000/api");
    expect(normalizeApiBase("http://127.0.0.1:8000/")).toBe("http://127.0.0.1:8000/api");
  });

  it("never doubles an existing /api suffix", () => {
    expect(normalizeApiBase("http://127.0.0.1:8000/api")).toBe("http://127.0.0.1:8000/api");
    expect(normalizeApiBase("http://127.0.0.1:8000/api/")).toBe("http://127.0.0.1:8000/api");
  });
});

describe("buildApiUrl", () => {
  const origin = "http://localhost:5173";

  it("keeps same-origin API calls relative for the proxy", () => {
    expect(buildApiUrl("/api", "/auth/login", undefined, origin)).toBe("/api/auth/login");
  });

  it("preserves the origin of an absolute API base", () => {
    expect(
      buildApiUrl("http://127.0.0.1:8000/api", "/auth/login", undefined, origin),
    ).toBe("http://127.0.0.1:8000/api/auth/login");
  });

  it("serialises query values and skips empty ones", () => {
    expect(
      buildApiUrl("http://127.0.0.1:8000/api", "/submissions", {
        limit: 20,
        status: "ready",
        search: "",
        offset: undefined,
        force: false,
      }),
    ).toBe("http://127.0.0.1:8000/api/submissions?limit=20&status=ready&force=false");
  });
});

describe("apiUrl wiring", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
    vi.resetModules();
    delete (globalThis as { window?: unknown }).window;
  });

  it("targets the configured backend origin instead of the page origin", async () => {
    vi.stubEnv("VITE_API_BASE_URL", "http://127.0.0.1:8000");
    vi.resetModules();
    (globalThis as { window?: unknown }).window = {
      location: { origin: "https://checkr.example.edu" },
    };

    const { apiUrl } = await import("./api");
    expect(apiUrl("/auth/login")).toBe("http://127.0.0.1:8000/api/auth/login");
  });
});
