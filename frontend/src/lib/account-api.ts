import { authenticatedFetch } from "./auth";

export type DeletionRequest = {
  id: string;
  state: string;
  irreversible_at: string | null;
};

async function parseResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const result = await response.json().catch(() => null) as { error?: { message?: string } } | null;
    throw new Error(result?.error?.message ?? "The account request could not be completed.");
  }
  return response.json() as Promise<T>;
}

export async function exportAccount() {
  const response = await authenticatedFetch("/api/account/export", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ idempotency_key: crypto.randomUUID() }),
  });
  if (!response.ok) return parseResponse<never>(response);
  const blob = await response.blob();
  const objectUrl = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = objectUrl;
  anchor.download = response.headers.get("Content-Disposition")?.match(/filename="?([^";]+)"?/i)?.[1]
    ?? "personal-ai-export.json";
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
}

export async function createDeletion() {
  const response = await authenticatedFetch("/api/account/deletion", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ idempotency_key: crypto.randomUUID() }),
  });
  return parseResponse<DeletionRequest>(response);
}

export async function getDeletion(id: string) {
  const response = await authenticatedFetch(`/api/account/deletion/${encodeURIComponent(id)}`);
  return parseResponse<DeletionRequest>(response);
}

async function updateDeletion(id: string, action: "confirm" | "cancel") {
  const response = await authenticatedFetch(`/api/account/deletion/${encodeURIComponent(id)}/${action}`, {
    method: "POST",
  });
  return parseResponse<DeletionRequest>(response);
}

export function confirmDeletion(id: string) {
  return updateDeletion(id, "confirm");
}

export function cancelDeletion(id: string) {
  return updateDeletion(id, "cancel");
}
