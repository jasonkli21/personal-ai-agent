import type { Metadata } from "next";
import Link from "next/link";
import type { ReactNode } from "react";
import { headers } from "next/headers";

import "./globals.css";
import { AuthGate } from "../features/auth/auth-gate";

// Evaluate server-side feature gates when a request arrives, including after deployment.
export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "Personal AI",
  description: "A personal AI system",
};

export default async function RootLayout({ children }: Readonly<{ children: ReactNode }>) {
  const requestHeaders = await headers();
  const nonce = requestHeaders.get("x-nonce");
  const authMode = process.env.AUTH_MODE ?? "development";
  const clientId = process.env.GOOGLE_OAUTH_CLIENT_ID ?? "";
  return (
    <html lang="en">
      <body><AuthGate nonce={nonce} authMode={authMode} clientId={clientId}><nav aria-label="Feature navigation" style={{ padding: ".75rem 1rem", display: "flex", gap: "1rem" }}>
        {process.env.RESEARCH_ENABLED === "true" && <Link href="/research">Research</Link>}
        {process.env.DECISION_ENABLED === "true" && <Link href="/decisions">Decision support</Link>}
        {process.env.DECISION_ENABLED === "true" && process.env.TRAVEL_ENABLED === "true" && <Link href="/travel">Travel</Link>}
        {process.env.DECISION_ENABLED === "true" && process.env.SHOPPING_ENABLED === "true" && <Link href="/shopping">Shopping</Link>}
        {process.env.DECISION_ENABLED === "true" && process.env.DECISION_INSPECTION_ENABLED === "true" && <Link href="/development/decisions">Decision inspector</Link>}
        <Link href="/account">Account</Link>
      </nav>{children}</AuthGate></body>
    </html>
  );
}
