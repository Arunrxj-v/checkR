import { describe, expect, it } from "vitest";

import { aiConnected, aiHealthy, aiStatusMeta } from "./aiStatus";

describe("aiStatusMeta", () => {
  it("maps verified states to healthy", () => {
    expect(aiStatusMeta("ready")).toEqual({
      label: "Ready",
      tone: "healthy",
      usable: true,
    });
    expect(aiStatusMeta("connected")).toEqual({
      label: "Connected",
      tone: "healthy",
      usable: true,
    });
  });

  it("maps transient and failure states", () => {
    expect(aiStatusMeta("model_loading").tone).toBe("pending");
    expect(aiStatusMeta("inference_error")).toEqual({
      label: "Inference failed",
      tone: "critical",
      usable: false,
    });
    expect(aiStatusMeta("model_not_installed").label).toBe("Model not installed");
    expect(aiStatusMeta("unavailable").label).toBe("Unavailable");
    expect(aiStatusMeta("error").tone).toBe("critical");
  });

  it("maps the busy single-inference state to a pending, unusable badge", () => {
    expect(aiStatusMeta("processing")).toEqual({
      label: "Processing",
      tone: "pending",
      usable: false,
    });
  });

  it("treats unknown/missing statuses as critical, never healthy", () => {
    expect(aiStatusMeta("something_new").tone).toBe("critical");
    expect(aiStatusMeta("").tone).toBe("critical");
    expect(aiStatusMeta(null).tone).toBe("critical");
  });
});

describe("aiHealthy / aiConnected", () => {
  it("only ready and connected are healthy", () => {
    expect(aiHealthy("ready")).toBe(true);
    expect(aiHealthy("connected")).toBe(true);
    expect(aiHealthy("model_loading")).toBe(false);
    expect(aiHealthy("inference_error")).toBe(false);
    expect(aiHealthy("unavailable")).toBe(false);
  });

  it("model loading is still connected", () => {
    expect(aiConnected("model_loading")).toBe(true);
    expect(aiConnected("unavailable")).toBe(false);
    expect(aiConnected("model_not_installed")).toBe(false);
  });

  it("processing means reachable but busy — never healthy", () => {
    expect(aiConnected("processing")).toBe(true);
    expect(aiHealthy("processing")).toBe(false);
  });
});
