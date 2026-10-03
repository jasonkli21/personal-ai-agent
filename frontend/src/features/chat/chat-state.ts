import type { Conversation, ConversationDetail, Message } from "../../lib/api";

export type RequestState = "idle" | "loading-list" | "creating" | "opening";
export type ChatState = {
  conversations: Conversation[];
  selected: ConversationDetail | null;
  requestState: RequestState;
  chatPending: boolean;
  error: string | null;
  messageErrors: Record<string, string>;
};
export type ChatAction =
  | { type: "list-loaded"; conversations: Conversation[] }
  | { type: "opened"; detail: ConversationDetail }
  | { type: "request-started"; requestState: RequestState }
  | { type: "failed"; error: string }
  | { type: "chat-started" }
  | { type: "chat-finished" }
  | { type: "stream-message-created"; message: Message }
  | { type: "stream-delta"; messageId: string; delta: string }
  | { type: "stream-completed"; message: Message }
  | { type: "stream-error"; messageId: string; error: string };

export const initialChatState: ChatState = {
  conversations: [],
  selected: null,
  requestState: "loading-list",
  chatPending: false,
  error: null,
  messageErrors: {},
};

function updateMessage(state: ChatState, messageId: string, change: (message: Message) => Message): ChatState {
  if (!state.selected) return state;
  return {
    ...state,
    selected: {
      ...state.selected,
      messages: state.selected.messages.map(message => message.id === messageId ? change(message) : message),
    },
  };
}

function removeBranch(messages: Message[], rootId: string): Message[] {
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
  return messages.filter(message => !removed.has(message.id));
}

/** Reconcile the visible active branch without deleting persisted audit history. */
export function chatReducer(state: ChatState, action: ChatAction): ChatState {
  switch (action.type) {
    case "request-started":
      return { ...state, requestState: action.requestState, error: null };
    case "list-loaded":
      return { ...state, conversations: action.conversations, requestState: "idle" };
    case "opened":
      return { ...state, selected: action.detail, requestState: "idle", error: null, messageErrors: {} };
    case "failed":
      return { ...state, requestState: "idle", error: action.error };
    case "chat-started":
      return { ...state, chatPending: true, error: null };
    case "chat-finished":
      return { ...state, chatPending: false };
    case "stream-message-created": {
      if (!state.selected || action.message.conversation_id !== state.selected.conversation.id ||
          state.selected.messages.some(message => message.id === action.message.id)) return state;
      // Replace the visible root and all descendants immediately, even if the
      // replacement subsequently fails. Both branches remain in backend history.
      const messages = action.message.supersedes_message_id
        ? removeBranch(state.selected.messages, action.message.supersedes_message_id)
        : state.selected.messages;
      return { ...state, selected: { ...state.selected, messages: [...messages, action.message] } };
    }
    case "stream-delta":
      return updateMessage(state, action.messageId, message => message.role === "assistant" && message.status === "streaming"
        ? { ...message, content: message.content + action.delta }
        : message);
    case "stream-completed":
      return updateMessage(state, action.message.id, () => action.message);
    case "stream-error": {
      const next = updateMessage(state, action.messageId, message => ({ ...message, status: "failed" }));
      return { ...next, messageErrors: { ...next.messageErrors, [action.messageId]: action.error } };
    }
  }
}
