import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import Home from "./page";

const fetchMock = vi.fn();
const conversation = { id: "conversation-1", owner_id: "local", title: "Project ideas", created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z" };
function jsonResponse(body: unknown, status = 200) { return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } }); }

describe("Home", () => {
  afterEach(cleanup);
  beforeEach(() => { fetchMock.mockReset(); vi.stubGlobal("fetch", fetchMock); });
  it("renders an empty state with a new conversation action", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ conversations: [] }));
    render(<Home />);
    expect(await screen.findByRole("heading", { name: "Start a conversation" })).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "New conversation" })).not.toHaveLength(0);
  });
  it("renders a loaded conversation list and selects a conversation", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ conversations: [conversation] }));
    fetchMock.mockResolvedValueOnce(jsonResponse({ conversation, messages: [{ id: "message-1", conversation_id: conversation.id, owner_id: "local", role: "user", content: "Hello", status: "completed", created_at: "2026-01-01T00:00:00Z", parent_message_id: null, supersedes_message_id: null, model: null, error_code: null }] }));
    render(<Home />);
    fireEvent.click(await screen.findByRole("button", { name: "Project ideas" }));
    expect(await screen.findByText("Hello")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Project ideas" })).toHaveAttribute("aria-current", "page");
  });
  it("shows a recoverable API error", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ error: { message: "Service unavailable" } }, 503));
    render(<Home />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Service unavailable");
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
  });
  it("creates and opens a conversation", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ conversations: [] }));
    fetchMock.mockResolvedValueOnce(jsonResponse(conversation, 201));
    fetchMock.mockResolvedValueOnce(jsonResponse({ conversation, messages: [] }));
    render(<Home />);
    fireEvent.click(await screen.findByRole("button", { name: "New conversation" }));
    await waitFor(() => expect(screen.getByRole("heading", { name: "Project ideas" })).toBeInTheDocument());
  });
});
