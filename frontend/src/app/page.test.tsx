import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import Home from "./page";

const fetchMock = vi.fn();
const conversation = { id: "conversation-1", owner_id: "local", title: "Project ideas", created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z" };
function jsonResponse(body: unknown, status = 200) { return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } }); }
function sseResponse(events: string[]) {
  return new Response(new ReadableStream({ start(controller) { controller.enqueue(new TextEncoder().encode(events.join(""))); controller.close(); } }), { headers: { "Content-Type": "text/event-stream" } });
}
const userMessage = { id: "user-1", conversation_id: conversation.id, owner_id: "local", role: "user" as const, content: "Hello", status: "completed" as const, created_at: "2026-01-01T00:00:00Z", parent_message_id: null, supersedes_message_id: null, model: null, error_code: null };
const assistantMessage = { ...userMessage, id: "assistant-1", role: "assistant" as const, content: "", status: "streaming" as const, parent_message_id: userMessage.id };

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
  it("accumulates deltas and replaces the streamed message with the completed response", async () => {
    const completed = { ...assistantMessage, content: "Hello there", status: "completed" as const };
    fetchMock.mockResolvedValueOnce(jsonResponse({ conversations: [conversation] }));
    fetchMock.mockResolvedValueOnce(jsonResponse({ conversation, messages: [] }));
    fetchMock.mockResolvedValueOnce(sseResponse([
      `event: message.created\ndata: ${JSON.stringify({ message: userMessage })}\n\n`,
      `event: message.created\ndata: ${JSON.stringify({ message: assistantMessage })}\n\n`,
      `event: response.delta\ndata: ${JSON.stringify({ message_id: assistantMessage.id, delta: "Hello " })}\n\n`,
      `event: response.delta\ndata: ${JSON.stringify({ message_id: assistantMessage.id, delta: "there" })}\n\n`,
      `event: response.completed\ndata: ${JSON.stringify({ message: completed })}\n\n`,
    ]));
    fetchMock.mockResolvedValueOnce(jsonResponse({ conversation, messages: [userMessage, completed] }));
    render(<Home />);
    fireEvent.click(await screen.findByRole("button", { name: "Project ideas" }));
    fireEvent.change(await screen.findByLabelText("Message"), { target: { value: "Hello" } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    expect(await screen.findByText("Hello there")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith("/api/conversations/conversation-1/messages", expect.objectContaining({ method: "POST" }));
  });
  it("renders stream errors and prevents duplicate submissions while pending", async () => {
    let finishStream: (() => void) | undefined;
    const pendingStream = new ReadableStream({ start(controller) { controller.enqueue(new TextEncoder().encode(`event: message.created\ndata: ${JSON.stringify({ message: assistantMessage })}\n\nevent: response.error\ndata: ${JSON.stringify({ message_id: assistantMessage.id, code: "provider_error", message: "The response failed safely." })}\n\n`)); finishStream = () => controller.close(); } });
    fetchMock.mockResolvedValueOnce(jsonResponse({ conversations: [conversation] }));
    fetchMock.mockResolvedValueOnce(jsonResponse({ conversation, messages: [] }));
    fetchMock.mockResolvedValueOnce(new Response(pendingStream, { headers: { "Content-Type": "text/event-stream" } }));
    render(<Home />);
    fireEvent.click(await screen.findByRole("button", { name: "Project ideas" }));
    fireEvent.change(await screen.findByLabelText("Message"), { target: { value: "Hello" } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    expect(await screen.findByRole("button", { name: "Sending…" })).toBeDisabled();
    await waitFor(() => expect(screen.getByRole("button", { name: "New conversation" })).toBeDisabled());
    expect(screen.getByRole("alert")).toHaveTextContent("The response failed safely.");
    finishStream?.();
  });
  it("regenerates completed assistant messages", async () => {
    const completed = { ...assistantMessage, content: "New answer", status: "completed" as const };
    fetchMock.mockResolvedValueOnce(jsonResponse({ conversations: [conversation] }));
    fetchMock.mockResolvedValueOnce(jsonResponse({ conversation, messages: [userMessage, { ...assistantMessage, content: "Old answer", status: "completed" }] }));
    fetchMock.mockResolvedValueOnce(sseResponse([`event: response.completed\ndata: ${JSON.stringify({ message: completed })}\n\n`]));
    fetchMock.mockResolvedValueOnce(jsonResponse({ conversation, messages: [userMessage, completed] }));
    render(<Home />);
    fireEvent.click(await screen.findByRole("button", { name: "Project ideas" }));
    fireEvent.click(await screen.findByRole("button", { name: "Regenerate" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith("/api/conversations/conversation-1/messages/assistant-1/regenerate", expect.objectContaining({ method: "POST" })));
  });
  it("retries a failed response through its parent user message", async () => {
    const failed = { ...assistantMessage, content: "Partial", status: "failed" as const, error_code: "llm_timeout" };
    fetchMock.mockResolvedValueOnce(jsonResponse({ conversations: [conversation] }));
    fetchMock.mockResolvedValueOnce(jsonResponse({ conversation, messages: [userMessage, failed] }));
    fetchMock.mockResolvedValueOnce(sseResponse([]));
    render(<Home />);
    fireEvent.click(await screen.findByRole("button", { name: "Project ideas" }));
    fireEvent.click(await screen.findByRole("button", { name: "Retry response" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      "/api/conversations/conversation-1/messages/user-1/edit-and-retry",
      expect.objectContaining({ method: "POST", body: JSON.stringify({ content: "Hello" }) }),
    ));
  });
  it("removes a superseded branch even when its replacement stream fails", async () => {
    const oldAnswer = { ...assistantMessage, content: "Old answer", status: "completed" as const };
    const descendant = { ...userMessage, id: "user-2", content: "Follow up", parent_message_id: oldAnswer.id };
    const replacement = { ...assistantMessage, id: "assistant-2", supersedes_message_id: oldAnswer.id };
    fetchMock.mockResolvedValueOnce(jsonResponse({ conversations: [conversation] }));
    fetchMock.mockResolvedValueOnce(jsonResponse({ conversation, messages: [userMessage, oldAnswer, descendant] }));
    fetchMock.mockResolvedValueOnce(sseResponse([
      `event: message.created\ndata: ${JSON.stringify({ message: replacement })}\n\n`,
      `event: response.delta\ndata: ${JSON.stringify({ message_id: replacement.id, delta: "Partial replacement" })}\n\n`,
      `event: response.error\ndata: ${JSON.stringify({ message_id: replacement.id, code: "llm_timeout", message: "Retry safely." })}\n\n`,
    ]));
    render(<Home />);
    fireEvent.click(await screen.findByRole("button", { name: "Project ideas" }));
    fireEvent.click(await screen.findByRole("button", { name: "Regenerate" }));
    expect(await screen.findByText("Partial replacement")).toBeInTheDocument();
    expect(screen.queryByText("Old answer")).not.toBeInTheDocument();
    expect(screen.queryByText("Follow up")).not.toBeInTheDocument();
  });
  it("edits a user message and retries it", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ conversations: [conversation] }));
    fetchMock.mockResolvedValueOnce(jsonResponse({ conversation, messages: [userMessage] }));
    fetchMock.mockResolvedValueOnce(sseResponse([]));
    render(<Home />);
    fireEvent.click(await screen.findByRole("button", { name: "Project ideas" }));
    fireEvent.click(await screen.findByRole("button", { name: "Edit and retry" }));
    fireEvent.change(screen.getByLabelText("Edit message"), { target: { value: "Updated question" } });
    fireEvent.click(screen.getByRole("button", { name: "Retry edited message" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith("/api/conversations/conversation-1/messages/user-1/edit-and-retry", expect.objectContaining({ method: "POST" })));
  });
});
