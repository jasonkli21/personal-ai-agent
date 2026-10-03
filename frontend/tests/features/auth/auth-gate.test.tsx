import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AuthGate } from "../../../src/features/auth/auth-gate";
import { clearGoogleIdToken, configureAuth, setGoogleIdToken } from "../../../src/lib/auth";

vi.mock("next/script", () => ({
  default: ({ onReady }: { onReady: () => void }) => <button onClick={onReady}>Load sign-in script</button>,
}));

afterEach(() => {
  cleanup();
  clearGoogleIdToken();
  configureAuth("development");
  delete window.google;
});

describe("Google authentication gate", () => {
  it("renders a new sign-in button after signout and token invalidation", () => {
    const renderedContainers: HTMLElement[] = [];
    const initialize = vi.fn();
    window.google = { accounts: { id: {
      initialize,
      renderButton: (element) => { renderedContainers.push(element); },
      disableAutoSelect: vi.fn(),
    } } };
    render(<AuthGate authMode="google_oidc" clientId="synthetic-client"><p>Private app</p></AuthGate>);
    fireEvent.click(screen.getByRole("button", { name: "Load sign-in script" }));
    expect(renderedContainers).toHaveLength(1);

    const token = `${btoa("{}")}.${btoa(JSON.stringify({ exp: Date.now() / 1000 + 3600 }))}.signature`;
    act(() => { setGoogleIdToken(token); });
    expect(screen.getByText("Private app")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Sign out" }));
    expect(renderedContainers).toHaveLength(2);
    expect(renderedContainers[1]).not.toBe(renderedContainers[0]);
    expect(renderedContainers[1].isConnected).toBe(true);

    act(() => { setGoogleIdToken(token); });
    act(clearGoogleIdToken);
    expect(renderedContainers).toHaveLength(3);
    expect(initialize).toHaveBeenCalledOnce();
  });
});
