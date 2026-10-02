"use client";

import { FormEvent, KeyboardEvent, useEffect, useReducer, useRef, useState } from "react";

import { ApiError, conversationsApi, type Conversation, type ConversationDetail, type Message, type StreamHandlers } from "../lib/api";
import styles from "./page.module.css";

type RequestState = "idle" | "loading-list" | "creating" | "opening";
type State = { conversations: Conversation[]; selected: ConversationDetail | null; requestState: RequestState; chatPending: boolean; error: string | null; messageErrors: Record<string, string> };
type Action =
  | { type: "list-loaded"; conversations: Conversation[] } | { type: "opened"; detail: ConversationDetail } | { type: "request-started"; requestState: RequestState } | { type: "failed"; error: string }
  | { type: "chat-started" } | { type: "chat-finished" } | { type: "stream-message-created"; message: Message } | { type: "stream-delta"; messageId: string; delta: string } | { type: "stream-completed"; message: Message } | { type: "stream-error"; messageId: string; error: string };

const initialState: State = { conversations: [], selected: null, requestState: "loading-list", chatPending: false, error: null, messageErrors: {} };
function withMessage(state: State, messageId: string, change: (message: Message) => Message): State {
  if (!state.selected) return state;
  return { ...state, selected: { ...state.selected, messages: state.selected.messages.map((message) => message.id === messageId ? change(message) : message) } };
}
function withoutBranch(messages: Message[], rootId: string): Message[] {
  const removed = new Set([rootId]);
  let changed = true;
  while (changed) {
    changed = false;
    for (const message of messages) {
      if (message.parent_message_id && removed.has(message.parent_message_id) && !removed.has(message.id)) {
        removed.add(message.id);
        changed = true;
      }
    }
  }
  return messages.filter((message) => !removed.has(message.id));
}
function reducer(state: State, action: Action): State {
  switch (action.type) {
    case "request-started": return { ...state, requestState: action.requestState, error: null };
    case "list-loaded": return { ...state, conversations: action.conversations, requestState: "idle" };
    case "opened": return { ...state, selected: action.detail, requestState: "idle", error: null, messageErrors: {} };
    case "failed": return { ...state, requestState: "idle", error: action.error };
    case "chat-started": return { ...state, chatPending: true, error: null };
    case "chat-finished": return { ...state, chatPending: false };
    case "stream-message-created": {
      if (!state.selected || state.selected.messages.some((message) => message.id === action.message.id)) return state;
      const messages = action.message.supersedes_message_id
        ? withoutBranch(state.selected.messages, action.message.supersedes_message_id)
        : state.selected.messages;
      return { ...state, selected: { ...state.selected, messages: [...messages, action.message] } };
    }
    case "stream-delta": return withMessage(state, action.messageId, (message) => ({ ...message, content: message.content + action.delta, status: "streaming" }));
    case "stream-completed": return withMessage(state, action.message.id, () => action.message);
    case "stream-error": { const next = withMessage(state, action.messageId, (message) => ({ ...message, status: "failed" })); return { ...next, messageErrors: { ...next.messageErrors, [action.messageId]: action.error } }; }
  }
}
function readableError(error: unknown) { return error instanceof ApiError ? error.message : "Something went wrong. Please try again."; }

export default function Home() {
  const [state, dispatch] = useReducer(reducer, initialState);
  const [draft, setDraft] = useState(""); const [editingMessage, setEditingMessage] = useState<Message | null>(null); const [editDraft, setEditDraft] = useState("");
  const mainHeading = useRef<HTMLHeadingElement>(null);
  const activeStream = useRef<AbortController | null>(null);
  async function loadConversations() { dispatch({ type: "request-started", requestState: "loading-list" }); try { dispatch({ type: "list-loaded", conversations: await conversationsApi.list() }); } catch (error) { dispatch({ type: "failed", error: readableError(error) }); } }
  useEffect(() => { void loadConversations(); return () => activeStream.current?.abort(); }, []);
  async function openConversation(id: string) { dispatch({ type: "request-started", requestState: "opening" }); try { dispatch({ type: "opened", detail: await conversationsApi.get(id) }); mainHeading.current?.focus(); } catch (error) { dispatch({ type: "failed", error: readableError(error) }); } }
  async function createConversation() { dispatch({ type: "request-started", requestState: "creating" }); try { const conversation = await conversationsApi.create(); dispatch({ type: "list-loaded", conversations: [conversation, ...state.conversations] }); await openConversation(conversation.id); } catch (error) { dispatch({ type: "failed", error: readableError(error) }); } }
  async function refreshConversation(conversationId: string) { try { const detail = await conversationsApi.get(conversationId); dispatch({ type: "opened", detail }); dispatch({ type: "list-loaded", conversations: state.conversations.map((item) => item.id === conversationId ? detail.conversation : item) }); } catch { /* Stream result remains visible and reload will reconcile it. */ } }
  async function runStream(start: (handlers: StreamHandlers, signal: AbortSignal) => Promise<void>) {
    if (!state.selected || state.chatPending || activeStream.current) return;
    const conversationId = state.selected.conversation.id; let assistantId: string | undefined; let completed = false;
    const controller = new AbortController();
    activeStream.current = controller;
    dispatch({ type: "chat-started" });
    const handlers: StreamHandlers = { onMessageCreated: (message) => { if (message.role === "assistant") assistantId = message.id; dispatch({ type: "stream-message-created", message }); }, onDelta: (messageId, delta) => dispatch({ type: "stream-delta", messageId, delta }), onCompleted: (message) => { completed = true; dispatch({ type: "stream-completed", message }); }, onError: (event) => { assistantId = event.message_id; dispatch({ type: "stream-error", messageId: event.message_id, error: event.message }); } };
    try { await start(handlers, controller.signal); if (completed) await refreshConversation(conversationId); } catch (error) { if (assistantId) dispatch({ type: "stream-error", messageId: assistantId, error: readableError(error) }); else { await refreshConversation(conversationId); dispatch({ type: "failed", error: readableError(error) }); } } finally { if (activeStream.current === controller) activeStream.current = null; dispatch({ type: "chat-finished" }); }
  }
  function submitMessage(event: FormEvent) { event.preventDefault(); const content = draft.trim(); if (!state.selected || !content || state.chatPending) return; setDraft(""); void runStream((handlers, signal) => conversationsApi.send(state.selected!.conversation.id, content, handlers, signal)); }
  function composerKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); event.currentTarget.form?.requestSubmit(); } }
  function beginEdit(message: Message) { setEditingMessage(message); setEditDraft(message.content); }
  function submitEdit(event: FormEvent) { event.preventDefault(); const content = editDraft.trim(); if (!editingMessage || !state.selected || !content || state.chatPending) return; const message = editingMessage; setEditingMessage(null); void runStream((handlers, signal) => conversationsApi.editAndRetry(state.selected!.conversation.id, message.id, content, handlers, signal)); }
  function retryFailedResponse(message: Message) {
    if (!state.selected || state.chatPending || !message.parent_message_id) return;
    const parent = state.selected.messages.find((candidate) => candidate.id === message.parent_message_id);
    if (!parent || parent.role !== "user") return;
    void runStream((handlers, signal) => conversationsApi.editAndRetry(state.selected!.conversation.id, parent.id, parent.content, handlers, signal));
  }
  const isBusy = state.requestState !== "idle"; const selectedId = state.selected?.conversation.id;
  return <div className={styles.shell}><aside className={styles.sidebar} aria-label="Conversations"><h1 className={styles.brand}>Personal AI</h1><button className={styles.newButton} onClick={() => void createConversation()} disabled={isBusy || state.chatPending}>New conversation</button><nav className={styles.conversationList} aria-label="Conversation list">{state.conversations.map((conversation) => <button key={conversation.id} className={`${styles.conversationButton} ${selectedId === conversation.id ? styles.selected : ""}`} aria-current={selectedId === conversation.id ? "page" : undefined} onClick={() => void openConversation(conversation.id)} disabled={isBusy || state.chatPending}>{conversation.title ?? "Untitled conversation"}</button>)}</nav></aside>
    <main className={styles.main}><section className={styles.content} aria-live="polite">{state.error && <div className={styles.error} role="alert"><p>{state.error}</p><button onClick={() => void loadConversations()}>Try again</button></div>}{!state.error && state.requestState === "loading-list" && <p className={styles.loading}>Loading conversations…</p>}{!state.error && !isBusy && !state.selected && state.conversations.length === 0 && <div className={styles.empty}><h2 ref={mainHeading} tabIndex={-1}>Start a conversation</h2><p>Create a conversation to begin.</p><button onClick={() => void createConversation()}>New conversation</button></div>}{!state.error && state.requestState === "opening" && <p className={styles.loading}>Opening conversation…</p>}
      {state.selected && <div><h2 ref={mainHeading} tabIndex={-1}>{state.selected.conversation.title ?? "Untitled conversation"}</h2>{state.selected.messages.length === 0 ? <p>This conversation is ready for your first message.</p> : <ol className={styles.messages}>{state.selected.messages.map((message) => <li className={styles.message} key={message.id} data-status={message.status}><span className={styles.messageRole}>{message.role}</span><p>{message.content || (message.status === "streaming" ? "Thinking…" : "")}</p>{message.status === "failed" && <p className={styles.messageError} role="alert">{state.messageErrors[message.id] ?? "This response could not be completed. Please try again."}</p>}<div className={styles.messageActions}>{message.role === "assistant" && message.status === "completed" && <button disabled={state.chatPending} onClick={() => void runStream((handlers, signal) => conversationsApi.regenerate(state.selected!.conversation.id, message.id, handlers, signal))}>Regenerate</button>}{message.role === "assistant" && message.status === "failed" && <button disabled={state.chatPending} onClick={() => retryFailedResponse(message)}>Retry response</button>}{message.role === "user" && <button disabled={state.chatPending} onClick={() => beginEdit(message)}>Edit and retry</button>}</div></li>)}</ol>}
        {editingMessage && <form className={styles.editForm} onSubmit={submitEdit}><label htmlFor="edit-message">Edit message</label><textarea id="edit-message" value={editDraft} onChange={(event) => setEditDraft(event.target.value)} disabled={state.chatPending} /><div><button type="submit" disabled={state.chatPending || !editDraft.trim()}>Retry edited message</button><button type="button" disabled={state.chatPending} onClick={() => setEditingMessage(null)}>Cancel</button></div></form>}
        <form className={styles.composer} onSubmit={submitMessage}><label htmlFor="composer">Message</label><textarea id="composer" value={draft} onChange={(event) => setDraft(event.target.value)} onKeyDown={composerKeyDown} disabled={state.chatPending} placeholder="Write a message" /><button type="submit" disabled={state.chatPending || !draft.trim()}>{state.chatPending ? "Sending…" : "Send"}</button></form></div>}</section></main></div>;
}
