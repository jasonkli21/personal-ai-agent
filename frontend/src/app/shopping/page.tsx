import { notFound } from "next/navigation";

import DomainWorkbench from "../../features/domains/domain-workbench";

export const dynamic = "force-dynamic";

export default function ShoppingPage() {
  if (process.env.DECISION_ENABLED !== "true" || process.env.SHOPPING_ENABLED !== "true") notFound();
  return <DomainWorkbench domain="shopping" adapter={process.env.SHOPPING_PRODUCTS_ADAPTER ?? "fake"} />;
}
