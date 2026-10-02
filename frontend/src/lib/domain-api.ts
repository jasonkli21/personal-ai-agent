import { ApiError } from "./api";

export type DomainId = "travel" | "shopping";
export type ComparisonState = "recommended" | "eligible_unranked" | "research_needed" | "no_verified_match";
export type CellStatus = "verified" | "conflicting" | "stale" | "missing" | "unverified" | "derived";

export type DomainFixture = {
  fixture_id: string;
  domain_id: DomainId;
  title: string;
  description: string;
};
export type ComparisonSource = {
  evidence_id: string;
  source_observation_id: string;
  url: string;
  title: string | null;
  attribution: string | null;
  policy_url: string | null;
  observed_at: string;
  expires_at: string;
};
export type ComparisonCell = {
  field: string;
  label: string;
  value: string | null;
  status: CellStatus;
  note: string | null;
  claim_ids: string[];
  sources: ComparisonSource[];
};
export type DomainFeature = {
  name: string;
  value: number | null;
  weight: number;
  evidence_ids: string[];
  missing_treatment: "zero" | "omit";
};
export type ComparisonRow = {
  candidate_id: string;
  name: string;
  eligible: boolean;
  selected: boolean;
  rank: number | null;
  score: number | null;
  exclusion_reasons: string[];
  cells: ComparisonCell[];
  features: DomainFeature[];
};
export type ConstraintSummary = {
  attribute: string;
  operator: string;
  value: unknown;
  upper_value?: unknown;
  source: "user" | "system";
};
export type DomainComparisonResult = {
  schema_version: "domain-comparison-v1";
  registration: {
    domain_id: DomainId;
    source_policy_version: string;
    field_schema_version: string;
    feature_policy_version: string;
    fields: { key: string; label: string }[];
  };
  comparison: {
    id: string;
    decision_id: string;
    domain_id: DomainId;
    state: ComparisonState;
    rendered_at: string;
    decision_policy_versions: { resolution: string; constraints: string; ranking: string };
    constraints: ConstraintSummary[];
    rows: ComparisonRow[];
    available_filters: string[];
  };
  provider_observations: {
    provider: string;
    attribution: string;
    policy_url: string | null;
    observed_at: string;
    expires_at: string;
  }[];
};

const states = new Set<ComparisonState>(["recommended", "eligible_unranked", "research_needed", "no_verified_match"]);
const statuses = new Set<CellStatus>(["verified", "conflicting", "stale", "missing", "unverified", "derived"]);
const isRecord = (value: unknown): value is Record<string, unknown> => typeof value === "object" && value !== null;

function validateResult(value: unknown, domain: DomainId): DomainComparisonResult {
  if (!isRecord(value) || value.schema_version !== "domain-comparison-v1" ||
      !isRecord(value.registration) || value.registration.domain_id !== domain ||
      !isRecord(value.comparison) || value.comparison.domain_id !== domain ||
      typeof value.comparison.id !== "string" || !states.has(value.comparison.state as ComparisonState) ||
      !Array.isArray(value.comparison.rows) || !Array.isArray(value.comparison.constraints) ||
      !Array.isArray(value.provider_observations)) {
    throw new ApiError("The comparison response was incomplete or invalid.");
  }
  for (const row of value.comparison.rows) {
    if (!isRecord(row) || typeof row.name !== "string" || typeof row.eligible !== "boolean" ||
        !Array.isArray(row.cells) || !Array.isArray(row.features)) {
      throw new ApiError("The comparison response contained an invalid candidate.");
    }
    for (const cell of row.cells) {
      if (!isRecord(cell) || typeof cell.field !== "string" || !statuses.has(cell.status as CellStatus) ||
          !Array.isArray(cell.sources)) {
        throw new ApiError("The comparison response contained an invalid evidence cell.");
      }
      for (const source of cell.sources) {
        if (!isRecord(source) || typeof source.url !== "string" || !isSafeLink(source.url)) {
          throw new ApiError("The comparison response contained an unsafe source link.");
        }
      }
    }
  }
  return value as unknown as DomainComparisonResult;
}

function isSafeLink(value: string) {
  try { return new URL(value).protocol === "https:"; } catch { return false; }
}

async function response(domain: DomainId, path: string, init?: RequestInit) {
  const result = await fetch(`/api/domains/${domain}${path}`, {
    ...init,
    cache: "no-store",
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!result.ok) {
    const error = await result.json().catch(() => ({}));
    throw new ApiError(error.error?.message ?? "The comparison is unavailable. Please retry.", result.status);
  }
  return result;
}

export const domainApi = {
  async fixtures(domain: DomainId): Promise<DomainFixture[]> {
    const value: unknown = await (await response(domain, "/fixtures")).json();
    if (!Array.isArray(value) || value.some(item => !isRecord(item) || item.domain_id !== domain || typeof item.fixture_id !== "string")) {
      throw new ApiError("The example comparison list was invalid.");
    }
    return value as DomainFixture[];
  },
  async runFixture(domain: DomainId, fixtureId: string): Promise<DomainComparisonResult> {
    return validateResult(await (await response(
      domain,
      `/fixtures/${encodeURIComponent(fixtureId)}/compare`,
      { method: "POST", body: "{}" },
    )).json(), domain);
  },
  async lookup(domain: DomainId, query: string): Promise<DomainComparisonResult> {
    return validateResult(await (await response(domain, "/lookup", {
      method: "POST",
      body: JSON.stringify({
        schema_version: "domain-lookup-v1",
        idempotency_key: crypto.randomUUID(),
        query,
        max_results: 8,
      }),
    })).json(), domain);
  },
  async get(domain: DomainId, comparisonId: string): Promise<DomainComparisonResult> {
    return validateResult(await (await response(
      domain,
      `/comparisons/${encodeURIComponent(comparisonId)}`,
    )).json(), domain);
  },
};
