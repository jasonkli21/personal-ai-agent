import { authenticatedFetch } from "./auth";
import { readSseFrames, SseError } from "./sse";

export type Conversation = {
  id: string;
  owner_id: string;
  application_id: string;
  workspace_id: string | null;
  title: string | null;
  created_at: string;
  updated_at: string;
};

export type Message = {
  id: string;
  conversation_id: string;
  owner_id: string;
  application_id: string;
  workspace_id: string | null;
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

export type ApplicationScopeRequest = {
  /** App IDs are extensible; the backend registry remains the authority. */
  applicationId?: string;
  workspaceId?: string | null;
  requestId?: string;
  capabilities?: string[];
  clientContext?: Record<string, string | number | boolean | null>;
};

export function applicationScopeHeaders(scope: ApplicationScopeRequest = {}): Record<string, string> {
  const headers: Record<string, string> = {
    "X-Application-ID": scope.applicationId ?? "personal_ai",
    "X-Request-ID": scope.requestId ?? crypto.randomUUID(),
  };
  if (scope.workspaceId) headers["X-Workspace-ID"] = scope.workspaceId;
  if (scope.capabilities?.length) headers["X-Client-Capabilities"] = scope.capabilities.join(",");
  if (scope.clientContext && Object.keys(scope.clientContext).length) {
    headers["X-Client-Context"] = JSON.stringify(scope.clientContext);
  }
  return headers;
}

export class ApiError extends Error {
  constructor(message: string, readonly status?: number) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(path: string, init?: RequestInit, scope?: ApplicationScopeRequest): Promise<T> {
  let response: Response;
  try {
    response = await authenticatedFetch(`/api${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...applicationScopeHeaders(scope), ...init?.headers },
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

async function streamRequest(path: string, init: RequestInit, handlers: StreamHandlers, scope?: ApplicationScopeRequest): Promise<void> {
  let response: Response;
  try {
    response = await authenticatedFetch(`/api${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...applicationScopeHeaders(scope), ...init.headers },
    });
  } catch {
    throw new ApiError("Unable to reach the Personal AI service. Please try again.");
  }
  if (!response.ok) {
    const body = (await response.json().catch(() => ({}))) as ErrorPayload;
    throw new ApiError(body.error?.message ?? "The request could not be completed. Please try again.", response.status);
  }
  if (!response.body) throw new ApiError("The response stream could not be read. Please try again.");

  let terminal = false;
  const consume = (event: string, data: string) => {
    if (!event || !data) return;
    try {
      switch (event) {
        case "message.created": {
          const payload = JSON.parse(data) as MessageCreatedEvent;
          if (!payload.message || typeof payload.message.id !== "string") throw new Error("Invalid message");
          handlers.onMessageCreated(payload.message);
          break;
        }
        case "response.delta": {
          const payload = JSON.parse(data) as ResponseDeltaEvent;
          if (typeof payload.message_id !== "string" || typeof payload.delta !== "string") throw new Error("Invalid delta");
          handlers.onDelta(payload.message_id, payload.delta);
          break;
        }
        case "response.completed": {
          const payload = JSON.parse(data) as ResponseCompletedEvent;
          if (!payload.message || typeof payload.message.id !== "string" || payload.message.role !== "assistant" || payload.message.status !== "completed" || typeof payload.message.content !== "string") throw new Error("Invalid completion");
          handlers.onCompleted(payload.message);
          terminal = true;
          break;
        }
        case "response.error": {
          const payload = JSON.parse(data) as ResponseErrorEvent;
          if (typeof payload.message_id !== "string" || typeof payload.code !== "string" || typeof payload.message !== "string") throw new Error("Invalid error");
          handlers.onError(payload);
          terminal = true;
          break;
        }
      }
    } catch {
      throw new ApiError("The response stream could not be read. Please try again.");
    }
  };

  try {
    for await (const frame of readSseFrames(response, { frameCharacters: 131072, totalBytes: 4 * 1024 * 1024 })) {
      consume(frame.event, frame.data);
      if (terminal) return;
    }
    throw new ApiError("The response was interrupted. Please retry.");
  } catch (error) {
    if (error instanceof SseError && error.kind === "incomplete") {
      throw new ApiError("The response was interrupted. Please retry.");
    }
    throw error instanceof ApiError ? error : new ApiError("The response stream could not be read. Please try again.");
  }
}

export const conversationsApi = {
  create(title?: string, signal?: AbortSignal, scope?: ApplicationScopeRequest) {
    return request<Conversation>("/conversations", { method: "POST", body: JSON.stringify(title ? { title } : {}), signal }, scope);
  },
  async list(signal?: AbortSignal, scope?: ApplicationScopeRequest) {
    return (await request<{ conversations: Conversation[] }>("/conversations", { signal }, scope)).conversations;
  },
  get(conversationId: string, signal?: AbortSignal, scope?: ApplicationScopeRequest) {
    return request<ConversationDetail>(`/conversations/${encodeURIComponent(conversationId)}`, { signal }, scope);
  },
  send(conversationId: string, content: string, handlers: StreamHandlers, signal?: AbortSignal, scope?: ApplicationScopeRequest) {
    return streamRequest(`/conversations/${encodeURIComponent(conversationId)}/messages`, { method: "POST", body: JSON.stringify({ content }), signal }, handlers, scope);
  },
  regenerate(conversationId: string, messageId: string, handlers: StreamHandlers, signal?: AbortSignal, scope?: ApplicationScopeRequest) {
    return streamRequest(`/conversations/${encodeURIComponent(conversationId)}/messages/${encodeURIComponent(messageId)}/regenerate`, { method: "POST", signal }, handlers, scope);
  },
  editAndRetry(conversationId: string, messageId: string, content: string, handlers: StreamHandlers, signal?: AbortSignal, scope?: ApplicationScopeRequest) {
    return streamRequest(`/conversations/${encodeURIComponent(conversationId)}/messages/${encodeURIComponent(messageId)}/edit-and-retry`, { method: "POST", body: JSON.stringify({ content }), signal }, handlers, scope);
  },
};
