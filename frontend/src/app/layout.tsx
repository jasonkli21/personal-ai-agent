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
      <body>{process.env.RESEARCH_ENABLED === "true" && <nav aria-label="Research navigation" style={{ padding: ".75rem 1rem" }}><Link href="/research">Research</Link></nav>}{children}</body>
    </html>
  );
}
