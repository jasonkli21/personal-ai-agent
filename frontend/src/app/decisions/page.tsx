import { notFound } from "next/navigation";
import DecisionLookup from "./decision-lookup";

export const dynamic = "force-dynamic";

export default async function DecisionsPage({ searchParams }: { searchParams: Promise<{ id?: string }> }) {
  if (process.env.DECISION_ENABLED !== "true") notFound();
  const { id } = await searchParams;
  return <DecisionLookup initialDecisionId={id} />;
}
