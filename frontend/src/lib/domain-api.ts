import { ApiError, applicationScopeHeaders } from "./api";
import { authenticatedFetch } from "./auth";

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
const isString = (value: unknown): value is string => typeof value === "string" && value.length > 0;
const isNullableString = (value: unknown): value is string | null => value === null || typeof value === "string";
const isDateTime = (value: unknown): value is string =>
  typeof value === "string" && value.length > 0 && Number.isFinite(Date.parse(value));
const isStringArray = (value: unknown): value is string[] =>
  Array.isArray(value) && value.every(item => typeof item === "string");

function validateResult(value: unknown, domain: DomainId): DomainComparisonResult {
  if (!isRecord(value) || value.schema_version !== "domain-comparison-v1" ||
      !isRecord(value.registration) || value.registration.domain_id !== domain ||
      !isString(value.registration.source_policy_version) ||
      !isString(value.registration.field_schema_version) ||
      !isString(value.registration.feature_policy_version) ||
      !Array.isArray(value.registration.fields) ||
      !isRecord(value.comparison) || value.comparison.domain_id !== domain ||
      !isString(value.comparison.id) || !isString(value.comparison.decision_id) ||
      !isDateTime(value.comparison.rendered_at) ||
      !states.has(value.comparison.state as ComparisonState) ||
      !Array.isArray(value.comparison.rows) || !Array.isArray(value.comparison.constraints) ||
      !isStringArray(value.comparison.available_filters) ||
      !isRecord(value.comparison.decision_policy_versions) ||
      !isString(value.comparison.decision_policy_versions.resolution) ||
      !isString(value.comparison.decision_policy_versions.constraints) ||
      !isString(value.comparison.decision_policy_versions.ranking) ||
      !Array.isArray(value.provider_observations)) {
    throw new ApiError("The comparison response was incomplete or invalid.");
  }
  for (const field of value.registration.fields) {
    if (!isRecord(field) || !isString(field.key) || !isString(field.label)) {
      throw new ApiError("The comparison response contained an invalid field registration.");
    }
  }
  for (const constraint of value.comparison.constraints) {
    if (!isRecord(constraint) || !isString(constraint.attribute) || !isString(constraint.operator) ||
        !["user", "system"].includes(String(constraint.source))) {
      throw new ApiError("The comparison response contained an invalid requirement.");
    }
  }
  for (const row of value.comparison.rows) {
    if (!isRecord(row) || !isString(row.candidate_id) || !isString(row.name) ||
        typeof row.eligible !== "boolean" || typeof row.selected !== "boolean" ||
        !(row.rank === null || (typeof row.rank === "number" && Number.isInteger(row.rank) && row.rank >= 1)) ||
        !(row.score === null || (typeof row.score === "number" && Number.isFinite(row.score) && row.score >= 0 && row.score <= 1)) ||
        !isStringArray(row.exclusion_reasons) || !Array.isArray(row.cells) || !Array.isArray(row.features)) {
      throw new ApiError("The comparison response contained an invalid candidate.");
    }
    for (const cell of row.cells) {
      if (!isRecord(cell) || !isString(cell.field) || !isString(cell.label) ||
          !(cell.value === null || typeof cell.value === "string") ||
          !statuses.has(cell.status as CellStatus) || !isNullableString(cell.note) ||
          !isStringArray(cell.claim_ids) || !Array.isArray(cell.sources)) {
        throw new ApiError("The comparison response contained an invalid evidence cell.");
      }
      for (const source of cell.sources) {
        if (!isRecord(source) || !isString(source.evidence_id) || !isString(source.source_observation_id) ||
            !isString(source.url) || !isSafeLink(source.url) ||
            !isNullableString(source.title) || !isNullableString(source.attribution) ||
            !(source.policy_url === null || (isString(source.policy_url) && isSafeLink(source.policy_url))) ||
            !isDateTime(source.observed_at) || !isDateTime(source.expires_at) ||
            Date.parse(source.expires_at) <= Date.parse(source.observed_at)) {
          throw new ApiError("The comparison response contained an unsafe source link.");
        }
      }
    }
    for (const feature of row.features) {
      if (!isRecord(feature) || !isString(feature.name) ||
          !(feature.value === null || (typeof feature.value === "number" && Number.isFinite(feature.value) && feature.value >= 0 && feature.value <= 1)) ||
          typeof feature.weight !== "number" || !Number.isFinite(feature.weight) || feature.weight < 0 || feature.weight > 1 ||
          !isStringArray(feature.evidence_ids) || !["zero", "omit"].includes(String(feature.missing_treatment))) {
        throw new ApiError("The comparison response contained an invalid feature score.");
      }
    }
  }
  for (const observation of value.provider_observations) {
    if (!isRecord(observation) || !isString(observation.provider) || !isString(observation.attribution) ||
        !(observation.policy_url === null || (isString(observation.policy_url) && isSafeLink(observation.policy_url))) ||
        !isDateTime(observation.observed_at) || !isDateTime(observation.expires_at) ||
        Date.parse(observation.expires_at) <= Date.parse(observation.observed_at)) {
      throw new ApiError("The comparison response contained invalid provider metadata.");
    }
  }
  return value as unknown as DomainComparisonResult;
}

function isSafeLink(value: string) {
  if (value.length > 2048 || [...value].some(character => {
    const code = character.charCodeAt(0);
    return code <= 0x20 || code === 0x7f || character === "\\";
  })) return false;
  try {
    const parsed = new URL(value);
    if (!new Set(["http:", "https:"]).has(parsed.protocol) || parsed.username || parsed.password ||
        (parsed.port !== "" && parsed.port !== "80" && parsed.port !== "443")) return false;
    const host = parsed.hostname.toLowerCase().replace(/^\[|\]$/g, "");
    if (!host || host.includes("%") || host.endsWith(".")) return false;
    if (host.includes(":")) {
      // Public IPv6 addresses use global unicast space; reject private, loopback,
      // link-local, documentation, and mapped addresses.
      const segments = host.split(":");
      const first = Number.parseInt(segments[0] || "0", 16);
      const second = Number.parseInt(segments[1] || "0", 16);
      if ((first & 0xe000) !== 0x2000 ||
          (first === 0x2001 && second <= 0x01ff) ||
          (first === 0x2001 && second === 0x0db8) ||
          first === 0x2002 ||
          (first === 0x3fff && second <= 0x0fff)) return false;
      return true;
    }
    const ipv4 = host.split(".");
    if (ipv4.length === 4 && ipv4.every(part => /^\d{1,3}$/.test(part) && Number(part) <= 255)) {
      const [a, b, c] = ipv4.map(Number);
      if (a === 0 || a === 10 || a === 127 || a >= 224 ||
          (a === 100 && b >= 64 && b <= 127) ||
          (a === 169 && b === 254) || (a === 172 && b >= 16 && b <= 31) ||
          (a === 192 && (b === 0 || b === 168)) ||
          (a === 192 && b === 88 && c === 99) ||
          (a === 198 && (b === 18 || b === 19 || b === 51)) ||
          (a === 203 && b === 0 && c === 113) || a >= 240) return false;
      return true;
    }
    if (!host.includes(".") || [".local", ".localhost", ".internal", ".invalid"].some(suffix => host.endsWith(suffix))) return false;
    const labels = host.split(".");
    return labels.every(label => label.length > 0 && !label.startsWith("-") && !label.endsWith("-") && /^[a-z0-9-]+$/.test(label));
  } catch { return false; }
}

async function response(domain: DomainId, path: string, init?: RequestInit) {
  const result = await authenticatedFetch(`/api/domains/${domain}${path}`, {
    ...init,
    cache: "no-store",
    headers: { "Content-Type": "application/json", ...applicationScopeHeaders(), ...init?.headers },
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
