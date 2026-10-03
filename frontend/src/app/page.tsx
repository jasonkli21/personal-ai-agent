"use client";

import { FormEvent, KeyboardEvent, useEffect, useReducer, useRef, useState } from "react";

import { chatReducer, initialChatState } from "../features/chat/chat-state";
import { ApiError, conversationsApi, type Message, type StreamHandlers } from "../lib/api";
import styles from "./page.module.css";

function readableError(error: unknown) {
  return error instanceof ApiError ? error.message : "Something went wrong. Please try again.";
}

export default function Home() {
  const [state, dispatch] = useReducer(chatReducer, initialChatState);
  const [draft, setDraft] = useState("");
  const [editingMessage, setEditingMessage] = useState<Message | null>(null);
  const [editDraft, setEditDraft] = useState("");
  const mainHeading = useRef<HTMLHeadingElement>(null);
  const activeStream = useRef<AbortController | null>(null);
  const activeNavigation = useRef<AbortController | null>(null);
  const isBusy = state.requestState !== "idle";
  const controlsDisabled = isBusy || state.chatPending;
  const selectedId = state.selected?.conversation.id;

  async function loadConversations() {
    if (activeNavigation.current || activeStream.current) return;
    const controller = new AbortController();
    activeNavigation.current = controller;
    dispatch({ type: "request-started", requestState: "loading-list" });
    try {
      const conversations = await conversationsApi.list(controller.signal);
      if (!controller.signal.aborted) dispatch({ type: "list-loaded", conversations });
    } catch (error) {
      if (!controller.signal.aborted) dispatch({ type: "failed", error: readableError(error) });
    } finally {
      if (activeNavigation.current === controller) activeNavigation.current = null;
    }
  }

  useEffect(() => {
    void loadConversations();
    return () => {
      activeStream.current?.abort();
      activeNavigation.current?.abort();
      activeNavigation.current = null;
    };
  }, []);

  async function openConversation(id: string) {
    if (activeNavigation.current || activeStream.current) return;
    const controller = new AbortController();
    activeNavigation.current = controller;
    dispatch({ type: "request-started", requestState: "opening" });
    try {
      const detail = await conversationsApi.get(id, controller.signal);
      if (controller.signal.aborted) return;
      setEditingMessage(null);
      dispatch({ type: "opened", detail });
      mainHeading.current?.focus();
    } catch (error) {
      if (!controller.signal.aborted) dispatch({ type: "failed", error: readableError(error) });
    } finally {
      if (activeNavigation.current === controller) activeNavigation.current = null;
    }
  }

  async function createConversation() {
    if (activeNavigation.current || activeStream.current) return;
    const controller = new AbortController();
    activeNavigation.current = controller;
    dispatch({ type: "request-started", requestState: "creating" });
    try {
      const conversation = await conversationsApi.create(undefined, controller.signal);
      if (controller.signal.aborted) return;
      dispatch({ type: "list-loaded", conversations: [conversation, ...state.conversations] });
      dispatch({ type: "request-started", requestState: "opening" });
      const detail = await conversationsApi.get(conversation.id, controller.signal);
      if (controller.signal.aborted) return;
      setEditingMessage(null);
      dispatch({ type: "opened", detail });
      mainHeading.current?.focus();
    } catch (error) {
      if (!controller.signal.aborted) dispatch({ type: "failed", error: readableError(error) });
    } finally {
      if (activeNavigation.current === controller) activeNavigation.current = null;
    }
  }

  async function refreshConversation(conversationId: string, signal: AbortSignal) {
    try {
      const detail = await conversationsApi.get(conversationId, signal);
      if (signal.aborted) return;
      dispatch({ type: "opened", detail });
      dispatch({
        type: "list-loaded",
        conversations: state.conversations.map(item => item.id === conversationId ? detail.conversation : item),
      });
    } catch {
      // A failed reconciliation must not discard the response already shown.
      // Reopening the conversation can recover its durable terminal state.
    }
  }

  async function runStream(start: (handlers: StreamHandlers, signal: AbortSignal) => Promise<void>) {
    if (!state.selected || controlsDisabled || activeNavigation.current || activeStream.current) return;
    const conversationId = state.selected.conversation.id;
    let assistantId: string | undefined;
    let completed = false;
    const controller = new AbortController();
    activeStream.current = controller;
    dispatch({ type: "chat-started" });
    const handlers: StreamHandlers = {
      onMessageCreated: message => {
        if (message.role === "assistant") assistantId = message.id;
        dispatch({ type: "stream-message-created", message });
      },
      onDelta: (messageId, delta) => dispatch({ type: "stream-delta", messageId, delta }),
      onCompleted: message => {
        completed = true;
        dispatch({ type: "stream-completed", message });
      },
      onError: event => {
        assistantId = event.message_id;
        dispatch({ type: "stream-error", messageId: event.message_id, error: event.message });
      },
    };
    try {
      await start(handlers, controller.signal);
      if (completed && !controller.signal.aborted) await refreshConversation(conversationId, controller.signal);
    } catch (error) {
      if (controller.signal.aborted) return;
      if (assistantId) {
        dispatch({ type: "stream-error", messageId: assistantId, error: readableError(error) });
      } else {
        // Preparation may persist the user message before returning an error.
        // Reload it so edit-and-retry remains available after budget overflow.
        await refreshConversation(conversationId, controller.signal);
        dispatch({ type: "failed", error: readableError(error) });
      }
    } finally {
      if (activeStream.current === controller) activeStream.current = null;
      dispatch({ type: "chat-finished" });
    }
  }

  function submitMessage(event: FormEvent) {
    event.preventDefault();
    const content = draft.trim();
    if (!state.selected || !content || controlsDisabled || activeNavigation.current || activeStream.current) return;
    const conversationId = state.selected.conversation.id;
    setDraft("");
    void runStream((handlers, signal) => conversationsApi.send(conversationId, content, handlers, signal));
  }

  function composerKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      event.currentTarget.form?.requestSubmit();
    }
  }

  function beginEdit(message: Message) {
    if (controlsDisabled) return;
    setEditingMessage(message);
    setEditDraft(message.content);
  }

  function submitEdit(event: FormEvent) {
    event.preventDefault();
    const content = editDraft.trim();
    if (!editingMessage || !state.selected || !content || controlsDisabled || activeNavigation.current || activeStream.current) return;
    const messageId = editingMessage.id;
    const conversationId = state.selected.conversation.id;
    setEditingMessage(null);
    void runStream((handlers, signal) => conversationsApi.editAndRetry(conversationId, messageId, content, handlers, signal));
  }

  function retryFailedResponse(message: Message) {
    if (!state.selected || controlsDisabled || !message.parent_message_id) return;
    const conversationId = state.selected.conversation.id;
    const parent = state.selected.messages.find(candidate => candidate.id === message.parent_message_id);
    if (!parent || parent.role !== "user") return;
    void runStream((handlers, signal) => conversationsApi.editAndRetry(conversationId, parent.id, parent.content, handlers, signal));
  }

  return (
    <div className={styles.shell}>
      <aside className={styles.sidebar} aria-label="Conversations">
        <h1 className={styles.brand}>Personal AI</h1>
        <button className={styles.newButton} onClick={() => void createConversation()} disabled={controlsDisabled}>New conversation</button>
        <nav className={styles.conversationList} aria-label="Conversation list">
          {state.conversations.map(conversation => (
            <button
              key={conversation.id}
              className={`${styles.conversationButton} ${selectedId === conversation.id ? styles.selected : ""}`}
              aria-current={selectedId === conversation.id ? "page" : undefined}
              onClick={() => void openConversation(conversation.id)}
              disabled={controlsDisabled}
            >{conversation.title ?? "Untitled conversation"}</button>
          ))}
        </nav>
      </aside>
      <main className={styles.main}>
        <section className={styles.content} aria-live="polite">
          {state.error && <div className={styles.error} role="alert">
            <p>{state.error}</p>
            <button disabled={controlsDisabled} onClick={() => void loadConversations()}>Try again</button>
          </div>}
          {!state.error && state.requestState === "loading-list" && <p className={styles.loading}>Loading conversations…</p>}
          {!state.error && !isBusy && !state.selected && state.conversations.length === 0 && <div className={styles.empty}>
            <h2 ref={mainHeading} tabIndex={-1}>Start a conversation</h2>
            <p>Create a conversation to begin.</p>
            <button onClick={() => void createConversation()}>New conversation</button>
          </div>}
          {!state.error && state.requestState === "opening" && <p className={styles.loading}>Opening conversation…</p>}
          {state.selected && <div>
            <h2 ref={mainHeading} tabIndex={-1}>{state.selected.conversation.title ?? "Untitled conversation"}</h2>
            {state.selected.messages.length === 0
              ? <p>This conversation is ready for your first message.</p>
              : <ol className={styles.messages}>
                {state.selected.messages.map(message => <li className={styles.message} key={message.id} data-status={message.status}>
                  <span className={styles.messageRole}>{message.role}</span>
                  <p>{message.content || (message.status === "streaming" ? "Thinking…" : "")}</p>
                  {message.status === "failed" && <p className={styles.messageError} role="alert">
                    {state.messageErrors[message.id] ?? "This response could not be completed. Please try again."}
                  </p>}
                  <div className={styles.messageActions}>
                    {message.role === "assistant" && message.status === "completed" && <button
                      disabled={controlsDisabled}
                      onClick={() => void runStream((handlers, signal) => conversationsApi.regenerate(selectedId!, message.id, handlers, signal))}
                    >Regenerate</button>}
                    {message.role === "assistant" && message.status === "failed" && <button disabled={controlsDisabled} onClick={() => retryFailedResponse(message)}>Retry response</button>}
                    {message.role === "user" && <button disabled={controlsDisabled} onClick={() => beginEdit(message)}>Edit and retry</button>}
                  </div>
                </li>)}
              </ol>}
            {editingMessage && <form className={styles.editForm} onSubmit={submitEdit}>
              <label htmlFor="edit-message">Edit message</label>
              <textarea id="edit-message" value={editDraft} maxLength={20000} onChange={event => setEditDraft(event.target.value)} disabled={controlsDisabled} />
              <div>
                <button type="submit" disabled={controlsDisabled || !editDraft.trim()}>Retry edited message</button>
                <button type="button" disabled={controlsDisabled} onClick={() => setEditingMessage(null)}>Cancel</button>
              </div>
            </form>}
            <form className={styles.composer} onSubmit={submitMessage}>
              <label htmlFor="composer">Message</label>
              <textarea id="composer" value={draft} maxLength={20000} onChange={event => setDraft(event.target.value)} onKeyDown={composerKeyDown} disabled={controlsDisabled} placeholder="Write a message" />
              <button type="submit" disabled={controlsDisabled || !draft.trim()}>{state.chatPending ? "Sending…" : "Send"}</button>
            </form>
          </div>}
        </section>
      </main>
    </div>
  );
}
