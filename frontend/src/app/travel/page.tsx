import { notFound } from "next/navigation";

import DomainWorkbench from "../../features/domains/domain-workbench";

export const dynamic = "force-dynamic";

export default function TravelPage() {
  if (process.env.DECISION_ENABLED !== "true" || process.env.TRAVEL_ENABLED !== "true") notFound();
  return <DomainWorkbench domain="travel" adapter={process.env.TRAVEL_PLACES_ADAPTER ?? "fake"} />;
}
