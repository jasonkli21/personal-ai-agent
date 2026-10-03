// @vitest-environment node
import { NextRequest } from "next/server";
import { afterEach, expect, it, vi } from "vitest";
import { middleware } from "../src/middleware";

afterEach(() => vi.unstubAllEnvs());

it("permits the installed Next.js development source maps without loosening production CSP", () => {
  const request = new NextRequest("http://localhost/");
  vi.stubEnv("NODE_ENV", "development");
  expect(middleware(request).headers.get("Content-Security-Policy")).toContain("'unsafe-eval'");
  vi.stubEnv("NODE_ENV", "production");
  const response = middleware(request);
  expect(response.headers.get("Content-Security-Policy")).not.toContain("'unsafe-eval'");
  expect(response.headers.get("Content-Security-Policy")).toContain("'nonce-");
  expect(response.headers.get("Strict-Transport-Security")).toContain("max-age=31536000");
});
