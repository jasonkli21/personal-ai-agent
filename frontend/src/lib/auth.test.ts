import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  authenticatedFetch,
  authorizationHeaders,
  clearGoogleIdToken,
  configureAuth,
  getAuthTokenSnapshot,
  setGoogleIdToken,
} from "./auth";

function tokenWithExpiry(exp: number) {
  const encode = (value: object) =>
    btoa(JSON.stringify(value)).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
  return `${encode({ alg: "none" })}.${encode({ exp })}.synthetic-signature`;
}

describe("memory-only Google authentication", () => {
  beforeEach(() => {
    localStorage.clear();
    sessionStorage.clear();
    configureAuth("google_oidc");
    clearGoogleIdToken();
  });

  afterEach(() => {
    configureAuth("development");
    vi.unstubAllGlobals();
  });

  it("keeps a well-formed unexpired token in memory and adds its bearer header", () => {
    const token = tokenWithExpiry(Date.now() / 1000 + 3600);
    expect(setGoogleIdToken(token)).toBe(true);
    expect(getAuthTokenSnapshot()).toBe(token);

    const headers = authorizationHeaders({ "Content-Type": "application/json" });
    expect(headers.get("Authorization")).toBe(`Bearer ${token}`);
    expect(headers.get("Content-Type")).toBe("application/json");
    expect(localStorage.length).toBe(0);
    expect(sessionStorage.length).toBe(0);
  });

  it("rejects malformed and nearly expired tokens", () => {
    expect(setGoogleIdToken("not-a-jwt")).toBe(false);
    expect(setGoogleIdToken(tokenWithExpiry(Date.now() / 1000 + 10))).toBe(false);
    expect(getAuthTokenSnapshot()).toBeNull();
  });

  it("clears the in-memory token when the API says the identity is invalid", async () => {
    const token = tokenWithExpiry(Date.now() / 1000 + 3600);
    setGoogleIdToken(token);
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      expect(input).toBe("/api/account/export");
      expect(new Headers(init?.headers).get("Authorization")).toBe(`Bearer ${token}`);
      return new Response(null, { status: 401 });
    });
    vi.stubGlobal("fetch", fetchMock);

    const response = await authenticatedFetch("/api/account/export", { method: "POST" });

    expect(response.status).toBe(401);
    expect(getAuthTokenSnapshot()).toBeNull();
    expect(localStorage.length).toBe(0);
    expect(sessionStorage.length).toBe(0);
  });
});
