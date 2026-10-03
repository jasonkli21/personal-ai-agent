import { notFound } from "next/navigation";
import ResearchPanel from "./research-panel";

export const dynamic = "force-dynamic";
export default async function ResearchPage({ searchParams }: { searchParams: Promise<{ session?: string; run?: string }> }) {
  if (process.env.RESEARCH_ENABLED !== "true") notFound();
  const { session, run } = await searchParams;
  const iterativeEnabled = process.env.ITERATIVE_RESEARCH_ENABLED === "true" &&
    process.env.ITERATIVE_PROGRESS_ENABLED === "true" &&
    process.env.NEXT_PUBLIC_ITERATIVE_RESEARCH_ENABLED === "true";
  return <ResearchPanel initialSessionId={session} initialRunId={run} iterativeEnabled={iterativeEnabled} inspectionEnabled={process.env.RESEARCH_INSPECTION_ENABLED === "true"} />;
}
