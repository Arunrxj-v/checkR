import { describe, expect, it } from "vitest";

import { resolveLoginExperience } from "./authOptions";
import type { AuthEnvironment } from "./types";

const DEV: AuthEnvironment = {
  environment: "development",
  self_registration_enabled: false,
  demo_credentials: { email: "examiner@example.edu", password: "DevDemo-Passw0rd" },
};

const PROD: AuthEnvironment = {
  environment: "production",
  self_registration_enabled: false,
  demo_credentials: null,
};

describe("resolveLoginExperience", () => {
  it("fails closed until the environment has loaded", () => {
    const exp = resolveLoginExperience(undefined, "signin");
    expect(exp.registrationEnabled).toBe(false);
    expect(exp.demoCredentials).toBeNull();
    expect(exp.mode).toBe("signin");
  });

  it("fails closed after a failed environment request", () => {
    expect(resolveLoginExperience(null, "signin").demoCredentials).toBeNull();
  });

  it("shows the seeded demo account in development", () => {
    const exp = resolveLoginExperience(DEV, "signin");
    expect(exp.demoCredentials).toEqual({
      email: "examiner@example.edu",
      password: "DevDemo-Passw0rd",
    });
    expect(exp.registrationEnabled).toBe(false);
  });

  it("offers only sign-in when account creation is closed", () => {
    const exp = resolveLoginExperience(DEV, "register");
    expect(exp.mode).toBe("signin");
    expect(exp.registrationEnabled).toBe(false);
  });

  it("keeps the registration flow when it is deliberately enabled", () => {
    const exp = resolveLoginExperience({ ...DEV, self_registration_enabled: true }, "register");
    expect(exp.mode).toBe("register");
    expect(exp.registrationEnabled).toBe(true);
  });

  it("never surfaces demo credentials in production", () => {
    const exp = resolveLoginExperience(PROD, "signin");
    expect(exp.demoCredentials).toBeNull();
    expect(exp.registrationEnabled).toBe(false);
    expect(exp.mode).toBe("signin");
  });

  it("ignores demo credentials a production server should not have sent", () => {
    const leaky: AuthEnvironment = {
      ...PROD,
      demo_credentials: { email: "examiner@example.edu", password: "DevDemo-Passw0rd" },
    };
    expect(resolveLoginExperience(leaky, "signin").demoCredentials).toBeNull();
  });

  it("ignores an incomplete demo credential payload", () => {
    const partial: AuthEnvironment = {
      ...DEV,
      demo_credentials: { email: "", password: "" },
    };
    expect(resolveLoginExperience(partial, "signin").demoCredentials).toBeNull();
  });
});
