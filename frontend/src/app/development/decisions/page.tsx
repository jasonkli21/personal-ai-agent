import { notFound } from "next/navigation";
import DecisionLookup from "../../decisions/decision-lookup";

export const dynamic = "force-dynamic";

export default async function DecisionInspectionPage({ searchParams }: { searchParams: Promise<{ id?: string }> }) {
  if (process.env.DECISION_ENABLED !== "true" || process.env.DECISION_INSPECTION_ENABLED !== "true") notFound();
  const { id } = await searchParams;
  return <DecisionLookup initialDecisionId={id} inspectionEnabled />;
}
