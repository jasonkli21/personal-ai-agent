"use client";

type AuthListener = () => void;

let googleIdToken: string | null = null;
let expiresAtMs = 0;
let expiryTimer: ReturnType<typeof setTimeout> | null = null;
let authMode: "development" | "google_oidc" = "development";
const listeners = new Set<AuthListener>();

function notify() {
  listeners.forEach((listener) => listener());
}

export function isGoogleOidcEnabled() {
  return authMode === "google_oidc";
}

export function configureAuth(mode: string) {
  authMode = mode === "google_oidc" ? "google_oidc" : "development";
}

export function subscribeAuth(listener: AuthListener) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function getAuthTokenSnapshot() {
  return googleIdToken;
}

export function getAuthTokenServerSnapshot() {
  return null;
}

export function setGoogleIdToken(token: string) {
  if (token.length > 8192) return false;
  const parts = token.split(".");
  if (parts.length !== 3) return false;
  try {
    const payload = JSON.parse(atob(parts[1].replace(/-/g, "+").replace(/_/g, "/"))) as { exp?: unknown };
    if (typeof payload.exp !== "number" || !Number.isFinite(payload.exp) || payload.exp * 1000 <= Date.now() + 60_000) return false;
    googleIdToken = token;
    expiresAtMs = payload.exp * 1000;
    if (expiryTimer) clearTimeout(expiryTimer);
    expiryTimer = setTimeout(clearGoogleIdToken, Math.min(expiresAtMs - Date.now(), 2_147_000_000));
    notify();
    return true;
  } catch {
    return false;
  }
}

export function clearGoogleIdToken() {
  googleIdToken = null;
  expiresAtMs = 0;
  if (expiryTimer) clearTimeout(expiryTimer);
  expiryTimer = null;
  notify();
}

export function authorizationHeaders(headers?: HeadersInit) {
  const merged = new Headers(headers);
  if (isGoogleOidcEnabled() && googleIdToken && expiresAtMs > Date.now()) {
    merged.set("Authorization", `Bearer ${googleIdToken}`);
  }
  return merged;
}

export async function authenticatedFetch(input: RequestInfo | URL, init?: RequestInit) {
  // Tokens belong only to our same-origin proxies, including when callers use
  // an absolute URL or Request object. Never forward them to a source/provider.
  const target = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
  if (isGoogleOidcEnabled() && new URL(target, window.location.origin).origin !== window.location.origin) {
    throw new Error("Authenticated requests must use the application origin.");
  }
  const requestInit: RequestInit = { ...init };
  let sentToken: string | null = null;
  if (isGoogleOidcEnabled() && googleIdToken && expiresAtMs > Date.now()) {
    requestInit.headers = authorizationHeaders(init?.headers);
    sentToken = googleIdToken;
  }
  const response = await fetch(input, requestInit);
  // A delayed failure for the previous credential must not sign out a newly
  // authenticated session.
  if (response.status === 401 && sentToken && sentToken === googleIdToken) clearGoogleIdToken();
  return response;
}
