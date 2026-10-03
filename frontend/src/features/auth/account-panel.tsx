"use client";

import { useEffect, useState } from "react";

import {
  cancelDeletion,
  confirmDeletion,
  createDeletion,
  exportAccount,
  getDeletion,
  type DeletionRequest,
} from "../../lib/account-api";

function errorMessage(error: unknown) {
  return error instanceof Error ? error.message : "The account request could not be completed.";
}

export function AccountPanel({
  exportEnabled,
  deletionEnabled,
}: {
  exportEnabled: boolean;
  deletionEnabled: boolean;
}) {
  const [request, setRequest] = useState<DeletionRequest | null>(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const requestId = new URLSearchParams(window.location.search).get("deletion");
    if (!requestId || !deletionEnabled) return;
    let cancelled = false;
    getDeletion(requestId)
      .then((current) => { if (!cancelled) setRequest(current); })
      .catch((reason: unknown) => { if (!cancelled) setError(errorMessage(reason)); });
    return () => { cancelled = true; };
  }, [deletionEnabled]);

  async function run(action: () => Promise<void>, success: string) {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      await action();
      setNotice(success);
    } catch (reason) {
      setError(errorMessage(reason));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section aria-label="Account data controls" style={{ display: "grid", gap: "1.5rem" }}>
      <section aria-labelledby="export-heading">
        <h2 id="export-heading">Export data</h2>
        <p>Download a bounded JSON archive of supported records owned by this account.</p>
        {exportEnabled ? (
          <button type="button" disabled={busy} onClick={() => void run(exportAccount, "Your export download has started.")}>
            Download account export
          </button>
        ) : <p>Export is disabled by the deployment operator.</p>}
      </section>

      <section aria-labelledby="deletion-heading">
        <h2 id="deletion-heading">Deletion request</h2>
        <p>
          Requests require recent sign-in. Confirmation records an operator action; this deployment
          does not automatically erase records or backups.
        </p>
        {deletionEnabled ? (
          <>
            {!request ? (
              <button
                type="button"
                disabled={busy}
                onClick={() => void run(async () => {
                  const created = await createDeletion();
                  setRequest(created);
                  const url = new URL(window.location.href);
                  url.searchParams.set("deletion", created.id);
                  window.history.replaceState(null, "", url);
                }, "Deletion request created. Review its status before confirming.")}
              >
                Start deletion request
              </button>
            ) : (
              <div>
                <p>Request status: <strong>{request.state}</strong></p>
                {request.state === "pending_confirmation" && (
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => void run(async () => setRequest(await confirmDeletion(request.id)), "Request confirmed for operator review.")}
                  >Confirm request</button>
                )}
                {!["cancelled", "completed"].includes(request.state) && request.irreversible_at == null && (
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => void run(async () => setRequest(await cancelDeletion(request.id)), "Request cancelled.")}
                  >Cancel request</button>
                )}
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => void run(async () => setRequest(await getDeletion(request.id)), "Request status refreshed.")}
                >Refresh status</button>
              </div>
            )}
          </>
        ) : <p>Deletion requests are disabled by the deployment operator.</p>}
      </section>
      {notice && <p role="status">{notice}</p>}
      {error && <p role="alert">{error}</p>}
    </section>
  );
}
