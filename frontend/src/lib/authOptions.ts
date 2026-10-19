// What the sign-in screen is allowed to offer.
//
// The server is the authority: it decides whether account creation is open and
// whether the seeded demo account may be advertised. This module only turns that
// payload into rendering decisions, and it fails closed — until the environment
// has loaded (or if the request fails) nothing extra is shown.

import type { AuthEnvironment } from "./types";

export type AuthMode = "signin" | "register";

export interface LoginExperience {
  /** The form actually rendered; registration falls back to sign-in. */
  mode: AuthMode;
  registrationEnabled: boolean;
  demoCredentials: { email: string; password: string } | null;
}

const CLOSED: LoginExperience = {
  mode: "signin",
  registrationEnabled: false,
  demoCredentials: null,
};

export function resolveLoginExperience(
  environment: AuthEnvironment | undefined | null,
  requestedMode: AuthMode,
): LoginExperience {
  if (!environment) return CLOSED;

  // Defence in depth: even if a deployment shipped a demo hint, only display it
  // when the payload is complete and the environment is not production.
  const demo = environment.demo_credentials;
  const demoCredentials =
    environment.environment !== "production" && demo?.email && demo?.password
      ? { email: demo.email, password: demo.password }
      : null;

  const registrationEnabled = environment.self_registration_enabled === true;

  return {
    mode: registrationEnabled ? requestedMode : "signin",
    registrationEnabled,
    demoCredentials,
  };
}
