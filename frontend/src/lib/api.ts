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
};
