export type Conversation = {
  id: string;
  owner_id: string;
  title: string | null;
  created_at: string;
  updated_at: string;
};

export type Message = {
  id: string;
  conversation_id: string;
  owner_id: string;
  role: "user" | "assistant";
  content: string;
  status: "streaming" | "completed" | "failed" | "superseded";
  created_at: string;
  parent_message_id: string | null;
  supersedes_message_id: string | null;
  model: string | null;
  error_code: string | null;
};

export type ConversationDetail = { conversation: Conversation; messages: Message[] };
type ErrorPayload = { error?: { message?: string } };
type MessageCreatedEvent = { message: Message };
type ResponseDeltaEvent = { message_id: string; delta: string };
type ResponseCompletedEvent = { message: Message };
type ResponseErrorEvent = { message_id: string; code: string; message: string };

export type StreamHandlers = {
  onMessageCreated: (message: Message) => void;
  onDelta: (messageId: string, delta: string) => void;
  onCompleted: (message: Message) => void;
  onError: (event: ResponseErrorEvent) => void;
};

export class ApiError extends Error {
  constructor(message: string, readonly status?: number) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`/api${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...init?.headers },
    });
  } catch {
    throw new ApiError("Unable to reach the Personal AI service. Please try again.");
  }
  if (!response.ok) {
    const body = (await response.json().catch(() => ({}))) as ErrorPayload;
    throw new ApiError(body.error?.message ?? "The request could not be completed. Please try again.", response.status);
  }
  return response.json() as Promise<T>;
}

async function streamRequest(path: string, init: RequestInit, handlers: StreamHandlers): Promise<void> {
  let response: Response;
  try {
    response = await fetch(`/api${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...init.headers },
    });
  } catch {
    throw new ApiError("Unable to reach the Personal AI service. Please try again.");
  }
  if (!response.ok) {
    const body = (await response.json().catch(() => ({}))) as ErrorPayload;
    throw new ApiError(body.error?.message ?? "The request could not be completed. Please try again.", response.status);
  }
  if (!response.body) throw new ApiError("The response stream could not be read. Please try again.");

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  const consume = (frame: string) => {
    const lines = frame.split(/\r?\n/);
    const event = lines.find((line) => line.startsWith("event:"))?.slice(6).trim();
    const data = lines.filter((line) => line.startsWith("data:")).map((line) => line.slice(5).trim()).join("\n");
    if (!event || !data) return;
    try {
      switch (event) {
        case "message.created": handlers.onMessageCreated((JSON.parse(data) as MessageCreatedEvent).message); break;
        case "response.delta": {
          const payload = JSON.parse(data) as ResponseDeltaEvent;
          handlers.onDelta(payload.message_id, payload.delta);
          break;
        }
        case "response.completed": handlers.onCompleted((JSON.parse(data) as ResponseCompletedEvent).message); break;
        case "response.error": handlers.onError(JSON.parse(data) as ResponseErrorEvent); break;
      }
    } catch {
      throw new ApiError("The response stream could not be read. Please try again.");
    }
  };

  while (true) {
    const { done, value } = await reader.read();
    buffer += decoder.decode(value, { stream: !done });
    let boundary = buffer.search(/\r?\n\r?\n/);
    while (boundary >= 0) {
      consume(buffer.slice(0, boundary));
      buffer = buffer.slice(boundary + (buffer[boundary] === "\r" ? 4 : 2));
      boundary = buffer.search(/\r?\n\r?\n/);
    }
    if (done) break;
  }
  if (buffer.trim()) consume(buffer);
}

export const conversationsApi = {
  create(title?: string) {
    return request<Conversation>("/conversations", { method: "POST", body: JSON.stringify(title ? { title } : {}) });
  },
  async list() {
    return (await request<{ conversations: Conversation[] }>("/conversations")).conversations;
  },
  get(conversationId: string) {
    return request<ConversationDetail>(`/conversations/${encodeURIComponent(conversationId)}`);
  },
  send(conversationId: string, content: string, handlers: StreamHandlers) {
    return streamRequest(`/conversations/${encodeURIComponent(conversationId)}/messages`, { method: "POST", body: JSON.stringify({ content }) }, handlers);
  },
  regenerate(conversationId: string, messageId: string, handlers: StreamHandlers) {
    return streamRequest(`/conversations/${encodeURIComponent(conversationId)}/messages/${encodeURIComponent(messageId)}/regenerate`, { method: "POST" }, handlers);
  },
  editAndRetry(conversationId: string, messageId: string, content: string, handlers: StreamHandlers) {
    return streamRequest(`/conversations/${encodeURIComponent(conversationId)}/messages/${encodeURIComponent(messageId)}/edit-and-retry`, { method: "POST", body: JSON.stringify({ content }) }, handlers);
  },
};
