import { notFound } from "next/navigation";
import ResearchPanel from "./research-panel";

export const dynamic = "force-dynamic";
export default async function ResearchPage({ searchParams }: { searchParams: Promise<{ session?: string }> }) {
  if (process.env.RESEARCH_ENABLED !== "true") notFound();
  const { session } = await searchParams;
  return <ResearchPanel initialSessionId={session} inspectionEnabled={process.env.RESEARCH_INSPECTION_ENABLED === "true"} />;
}
