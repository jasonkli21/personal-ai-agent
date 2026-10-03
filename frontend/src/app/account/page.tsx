import { AccountPanel } from "../../features/auth/account-panel";

export const dynamic = "force-dynamic";

export default function AccountPage() {
  return (
    <main style={{ maxWidth: "48rem", margin: "2rem auto", padding: "0 1rem" }}>
      <h1>Account data</h1>
      <p>Export or manage deletion requests for data owned by this signed-in account.</p>
      <AccountPanel
        exportEnabled={process.env.EXPORT_ENABLED === "true"}
        deletionEnabled={process.env.DELETION_ENABLED === "true"}
      />
    </main>
  );
}
