"use client";

import { useEffect, useReducer, useRef } from "react";

import { ApiError, conversationsApi, type Conversation, type ConversationDetail } from "../lib/api";
import styles from "./page.module.css";

type RequestState = "idle" | "loading-list" | "creating" | "opening";
type State = { conversations: Conversation[]; selected: ConversationDetail | null; requestState: RequestState; error: string | null };
type Action =
  | { type: "list-loaded"; conversations: Conversation[] }
  | { type: "opened"; detail: ConversationDetail }
  | { type: "request-started"; requestState: RequestState }
  | { type: "failed"; error: string };

const initialState: State = { conversations: [], selected: null, requestState: "loading-list", error: null };

function reducer(state: State, action: Action): State {
  switch (action.type) {
    case "request-started": return { ...state, requestState: action.requestState, error: null };
    case "list-loaded": return { ...state, conversations: action.conversations, requestState: "idle" };
    case "opened": return { ...state, selected: action.detail, requestState: "idle", error: null };
    case "failed": return { ...state, requestState: "idle", error: action.error };
  }
}

function readableError(error: unknown) {
  return error instanceof ApiError ? error.message : "Something went wrong. Please try again.";
}

export default function Home() {
  const [state, dispatch] = useReducer(reducer, initialState);
  const mainHeading = useRef<HTMLHeadingElement>(null);

  async function loadConversations() {
    dispatch({ type: "request-started", requestState: "loading-list" });
    try { dispatch({ type: "list-loaded", conversations: await conversationsApi.list() }); }
    catch (error) { dispatch({ type: "failed", error: readableError(error) }); }
  }
  useEffect(() => { void loadConversations(); }, []);

  async function openConversation(id: string) {
    dispatch({ type: "request-started", requestState: "opening" });
    try {
      dispatch({ type: "opened", detail: await conversationsApi.get(id) });
      mainHeading.current?.focus();
    } catch (error) { dispatch({ type: "failed", error: readableError(error) }); }
  }

  async function createConversation() {
    dispatch({ type: "request-started", requestState: "creating" });
    try {
      const conversation = await conversationsApi.create();
      dispatch({ type: "list-loaded", conversations: [conversation, ...state.conversations] });
      await openConversation(conversation.id);
    } catch (error) { dispatch({ type: "failed", error: readableError(error) }); }
  }

  const isBusy = state.requestState !== "idle";
  const selectedId = state.selected?.conversation.id;
  return <div className={styles.shell}>
    <aside className={styles.sidebar} aria-label="Conversations">
      <h1 className={styles.brand}>Personal AI</h1>
      <button className={styles.newButton} onClick={() => void createConversation()} disabled={isBusy}>New conversation</button>
      <nav className={styles.conversationList} aria-label="Conversation list">
        {state.conversations.map((conversation) => <button key={conversation.id} className={`${styles.conversationButton} ${selectedId === conversation.id ? styles.selected : ""}`} aria-current={selectedId === conversation.id ? "page" : undefined} onClick={() => void openConversation(conversation.id)} disabled={isBusy}>{conversation.title ?? "Untitled conversation"}</button>)}
      </nav>
    </aside>
    <main className={styles.main}><section className={styles.content} aria-live="polite">
      {state.error && <div className={styles.error} role="alert"><p>{state.error}</p><button onClick={() => void loadConversations()}>Try again</button></div>}
      {!state.error && state.requestState === "loading-list" && <p className={styles.loading}>Loading conversations…</p>}
      {!state.error && !isBusy && !state.selected && state.conversations.length === 0 && <div className={styles.empty}><h2 ref={mainHeading} tabIndex={-1}>Start a conversation</h2><p>Create a conversation to begin.</p><button onClick={() => void createConversation()}>New conversation</button></div>}
      {!state.error && state.requestState === "opening" && <p className={styles.loading}>Opening conversation…</p>}
      {state.selected && <div><h2 ref={mainHeading} tabIndex={-1}>{state.selected.conversation.title ?? "Untitled conversation"}</h2>{state.selected.messages.length === 0 ? <p>This conversation is ready for your first message.</p> : <ol className={styles.messages}>{state.selected.messages.map((message) => <li className={styles.message} key={message.id}><span className={styles.messageRole}>{message.role}</span>{message.content}</li>)}</ol>}</div>}
    </section></main>
  </div>;
}
