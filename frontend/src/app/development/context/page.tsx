import { notFound } from "next/navigation";
import ContextInspector from "./inspector";

export const dynamic = "force-dynamic";

export default function ContextInspectionPage() {
  if (process.env.CONTEXT_INSPECTION_ENABLED !== "true") notFound();
  return <ContextInspector enabled memoryEnabled={process.env.MEMORY_INSPECTION_ENABLED === "true"} />;
}
