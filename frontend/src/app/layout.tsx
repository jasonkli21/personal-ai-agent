import type { Metadata } from "next";
import Link from "next/link";
import type { ReactNode } from "react";

import "./globals.css";

// Evaluate server-side feature gates when a request arrives, including after deployment.
export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "Personal AI",
  description: "A personal AI system",
};

export default function RootLayout({ children }: Readonly<{ children: ReactNode }>) {
  return (
    <html lang="en">
      <body><nav aria-label="Feature navigation" style={{ padding: ".75rem 1rem", display: "flex", gap: "1rem" }}>
        {process.env.RESEARCH_ENABLED === "true" && <Link href="/research">Research</Link>}
        {process.env.DECISION_ENABLED === "true" && <Link href="/decisions">Decision support</Link>}
        {process.env.DECISION_ENABLED === "true" && process.env.DECISION_INSPECTION_ENABLED === "true" && <Link href="/development/decisions">Decision inspector</Link>}
      </nav>{children}</body>
    </html>
  );
}
