# ADR 0015: Keep Phase 7 domain modules thin

Date: 2026-10-02

Status: Accepted

## Decision

Travel and shopping are internal `DomainModule` implementations, not an
external plugin system. Each module registers a versioned field schema,
supported entity types, constraints, explainable feature policy, source policy,
privacy notice, and retention policy. It maps provider records to the shared
Phase 5 evidence contracts and Phase 6 candidates and claims. The shared
decision service remains responsible for identity resolution, evidence
verification, freshness, hard constraints, and final ranking.

Domain claims are immutable extensions keyed to shared claim IDs. Provider
observations are separately attributable and expiring. Comparison snapshots
retain candidate order, source links, visible constraints, field and feature
versions, shared decision-policy versions, and result rows. The repository
uses bounded point reads and transactions; it adds no composite index.

## Source rights and safety

Phase 5 research citations may be reused by a domain only through their stored
source references. Brave-origin results remain blocked unless the operator has
explicit storage and AI-use rights. The current
[Brave Search API terms](https://api-dashboard.search.brave.com/documentation/resources/terms-of-service)
do not grant persistent storage or AI model evaluation rights by default.

Provider credentials and SDK details stay inside provider adapters. Each
adapter has an independent disabled-by-default gate, bounded request and
response sizes, attribution, TTL, and fallback. No module writes an
authoritative trip, booking, purchase, or price-history record. Reviews remain
sourced opinions and evidence-quality signals, never proof of product facts.

## User-facing boundary

The comparison view is rendered from validated decision results. It shows
constraints, eligibility, freshness, conflict and missing states, rationale,
and original source links. Filters only change local presentation. There are
no transactional actions and no hidden model reasoning or owner-private memory
in comparison responses. The fixed `local` owner is not an authentication
boundary.

## Consequences

The platform can load either domain independently or both together without a
second storage, search, entity, ranking, or authentication stack. Domain
features run only after shared hard-constraint evaluation. Future application
repositories can own editable trip or shopping records and consume the shared
comparison APIs without treating these proposals as authoritative records.
