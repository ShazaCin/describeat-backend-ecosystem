# 10 — Architecture Decision Records

> The "why we did it this way" decisions, captured so future contributors don't re-litigate them.

Each ADR is a short document (1-2 pages) capturing a significant architectural decision: the context, the options considered, the decision, and the consequences.

---

## ADR-001: Two Cognito pools, not one with roles

**Status:** Accepted (2026-06, originally)

**Context:** DescribeAT has two distinct user populations — listeners (the blind/VI users of the app) and admins (content managers, support staff). They have different authorization rules, different session lifetimes, and different MFA requirements.

**Options considered:**

1. **One pool with role-based access control.** Simpler to manage. Roles assigned via a custom attribute. Authorization rules implemented as runtime checks on every API call.

2. **Two pools (app + admin).** More infrastructure. Each pool has its own configuration, OAuth clients, and authorization model.

**Decision:** Two pools.

**Reasoning:**

- The admin pool needs a hard allowlist of email domains. The app pool does not. A merged pool either loses the admin allowlist (insecure) or imposes it on everyone (impossible).
- Admin sessions should be short (15 min access / 24h refresh). Listener sessions should be long (1h access / 30d refresh). A merged pool uses one policy.
- Admin MFA should be required. Listener MFA should be optional. A merged pool uses one policy.
- If the admin pool is compromised, deleting it doesn't affect listeners. If the merged pool is compromised, every user is potentially an admin.

**Consequences:**

- More infrastructure to manage (two pools, two OAuth clients, two sets of secrets).
- A future contributor will be tempted to "simplify" by merging the pools. Resist this. The "complexity" of two pools is dwarfed by the operational pain of a single pool with roles.

---

## ADR-002: Two-service fingerprinting (matcher + fingerprinter), not one

**Status:** Accepted (2026-06, originally)

**Context:** Audio fingerprinting has two distinct workload patterns:
- **Matching:** steady-state, light CPU, latency-sensitive. Runs on every listener sync request.
- **Fingerprinting:** bursty, heavy CPU, latency-tolerant. Runs only when a new AD track is uploaded.

**Options considered:**

1. **One service, always-on, sized for fingerprinting.** Simple. The matcher is always ready because the fingerprinter is always ready.

2. **Two services: matcher always-on, fingerprinter on-demand.** More complex. The matcher is sized for matching; the fingerprinter is sized for fingerprinting and scales to zero when idle.

**Decision:** Two services.

**Reasoning:**

- The matcher's latency budget is 1-3 seconds per request. A service sized for fingerprinting (4 vCPU) wastes money to meet a workload it rarely sees.
- The fingerprinter's cold-start latency (~30s) is acceptable for the upload flow but unacceptable for the sync flow.
- Conflating them means a fingerprinting job can starve matching requests, leading to user-visible latency spikes.
- Separating them lets each be optimized independently.

**Consequences:**

- Two deployment units to manage.
- The hash database is shared. The matcher reads from it; the fingerprinter writes to it. The matcher's in-memory cache must be invalidated when the fingerprinter writes (or the matcher can periodically reload).
- A new contributor will be tempted to "simplify" by running them on the same instance. Resist this. The cost and latency trade-offs are real.

---

## ADR-003: GraphQL, not REST

**Status:** Accepted (2026-06, originally)

**Context:** The data layer needs to serve multiple clients (PWA, admin portal) with different field requirements. The same Title entity is queried differently by each.

**Options considered:**

1. **REST with multiple endpoints.** `/titles/:id`, `/titles/:id/tracks`, etc. Each client fetches what it needs from multiple endpoints.

2. **GraphQL.** Single endpoint, client specifies the fields it needs.

**Decision:** GraphQL.

**Reasoning:**

- Clients query exactly the fields they need. Less data over the wire.
- The schema is a single source of truth for the data model.
- Authorization is enforced at the resolver level, which is more reliable than per-endpoint checks.
- Subscriptions (for real-time updates) are native to GraphQL.

**Consequences:**

- GraphQL is harder to cache than REST. The CDN cannot cache GraphQL responses (per-user). API responses are not cached at the edge.
- GraphQL introspection can leak schema information. Disable introspection in production if this is a concern.
- N+1 query problems are easier to introduce in GraphQL. Use dataloader or equivalent batching.

---

## ADR-004: CloudFront for CDN (originally) — now portable

**Status:** Superseded (2026-06)

**Context:** The original production deployment used CloudFront because it was the AWS-native option and the deployment was AWS-only.

**Options considered for the open-source release:**

1. **Stay AWS-only.** Document CloudFront as the recommended CDN.

2. **Document the architecture abstractly, support multiple CDNs.** Let self-hosters choose.

**Decision:** Document the architecture abstractly. The CDN is interchangeable. Cloudflare, Fastly, and CloudFront all work; the choice is deployment-specific.

**Reasoning:**

- Self-hosters may not be on AWS. Requiring CloudFront would block them.
- The CDN's responsibilities (TLS termination, routing, caching) are common to all CDNs.
- Documenting the contract (what the CDN must do) is more valuable than documenting one specific implementation.

**Consequences:**

- The deployment guide is more abstract. Self-hosters must translate the abstract guide to their specific CDN.
- We do not provide CloudFront-specific Terraform/CDK code. The examples in the docs are conceptual.

---

## ADR-005: AGPLv3 + DCO, not Apache 2.0 + CLA

**Status:** Accepted (2026-06, originally)

**Context:** DescribeAT is being open-sourced. The license choice affects who can use the code and under what conditions.

**Options considered:**

1. **AGPLv3 + DCO.** Network copyleft. Anyone who deploys DescribeAT as a service must share their improvements. DCO is a lightweight contribution agreement.

2. **Apache 2.0 + CLA.** Permissive. Anyone can use the code for any purpose, including commercial. CLA provides IP protection for the project.

3. **MIT.** Maximum permissive. Anyone can use the code with minimal restrictions.

**Decision:** AGPLv3 + DCO.

**Reasoning:**

- The project's mission is to make audio description accessible to everyone. AGPLv3's network copyleft clause ensures that improvements to the system benefit the community, not just one company.
- DCO is low-friction for contributors. No CLA paperwork; just `git commit -s`.
- The closed-source components (fingerprinting library, AD content) are licensed separately and not affected by this decision.

**Consequences:**

- Some companies will not use AGPLv3 code in their products. This is acceptable; the mission prioritizes community benefit over corporate adoption.
- Contributors must sign off on the DCO. This is enforced at PR-merge time.

---

## ADR-006: Service worker caching for static assets, not API responses

**Status:** Accepted (2026-06, originally)

**Context:** The PWA uses a service worker for offline support. The SW must decide what to cache.

**Options considered:**

1. **Cache everything.** Maximum offline support. Minimum data freshness.

2. **Cache only static assets.** Limited offline support. Maximum data freshness.

3. **Cache static assets + safe-to-cache API responses.** Best of both, but more complex to reason about.

**Decision:** Cache only static assets.

**Reasoning:**

- API responses are user-specific and security-sensitive. Caching them at the edge is a security hole.
- Static assets (hashed bundles, images) are immutable. Caching them is safe and fast.
- The PWA's "offline support" is limited to "I can see the last screen I was on." This is the right trade-off for an app that needs real-time data.

**Consequences:**

- Listeners without network cannot use the app (other than seeing the last loaded screen).
- The SW is simpler and easier to reason about.
- A future contributor will be tempted to "improve offline support" by caching more. Resist this. The security trade-off is not worth it.

---

## ADR-007: Audio fingerprinting closed-source, code open-source

**Status:** Accepted (2026-06, originally)

**Context:** The audio fingerprinting engine is a critical component. The choice is between using an open-source library (Dejavu) and a closed-source commercial library.

**Options considered:**

1. **Open-source only (Dejavu).** Lower accuracy on noisy real-world audio. No licensing fees. Modifiable.

2. **Closed-source commercial.** Higher accuracy. Licensing fees. Not modifiable.

3. **Open-source for the public release, commercial for the original deployer's production use.**

**Decision:** Open-source for the public release. The commercial library is used by the original production deployment but is not redistributed.

**Reasoning:**

- Open-source releases must not depend on closed-source libraries. Otherwise the "open source" label is misleading.
- The accuracy trade-off is acceptable for the public release. Self-hosters who need higher accuracy can license the commercial library separately.
- The architecture is designed to allow swapping the fingerprinting engine. The matcher service has a clean contract (`POST /t2s/sync`, returns JSON); the implementation is pluggable.

**Consequences:**

- The default deployment uses Dejavu, with lower accuracy on noisy audio.
- Self-hosters who need higher accuracy must license the commercial library and implement a service that conforms to the matcher's contract.
- The public release cannot include any closed-source code, even as a build dependency.

---

## ADR-008: Domain allowlist on admin pool, not app pool

**Status:** Accepted (2026-06, originally)

**Context:** The admin pool should be restricted to specific email domains. The app pool should accept any email.

**Decision:** Domain allowlist on admin pool only.

**Reasoning:**

- Admins are staff. They have corporate email addresses. Hard-locking admin access to specific domains is the right security control.
- Listeners are users. They may use personal email addresses, school email addresses, or any other address. Domain allowlist on the app pool would block legitimate users.

**Consequences:**

- Self-hosters MUST set the admin domain allowlist correctly. Forgetting this is a critical security vulnerability.
- The allowlist is enforced via a Lambda trigger (Cognito) or equivalent mechanism in other auth providers.
- The app pool has no allowlist. This is correct for a public deployment. For a corporate deployment, the operator may add an allowlist post-creation.

---

## ADR-009: Schema-first GraphQL, not code-first

**Status:** Accepted (2026-06, originally)

**Context:** The data layer uses GraphQL. The choice is between schema-first (write the `.graphql` schema, generate code) and code-first (write code that defines the schema).

**Decision:** Schema-first.

**Reasoning:**

- The schema is the contract. Schema-first makes the contract explicit and reviewable.
- Schema-first generates TypeScript types automatically, which the client apps use.
- Schema-first tools (GraphQL Code Generator) produce consistent, well-typed code.
- Code-first is faster for prototyping but produces implicit contracts that are hard to review.

**Consequences:**

- The schema is a checked-in artifact (`schema.graphql`). Changes require a PR.
- Resolvers are implemented separately. The schema and resolvers must stay in sync; the build enforces this.
- New contributors can read the schema to understand the data model without reading resolver code.

---

## ADR-010: Pre-signed URLs for private content, not proxy through the data layer

**Status:** Accepted (2026-06, originally)

**Context:** When the fingerprinter needs to download a reference audio file, or when an admin needs to upload a new AD track, the data layer needs to grant temporary access to the private bucket.

**Options considered:**

1. **Proxy through the data layer.** The data layer fetches the file from the bucket and serves it to the client. Simple, but adds load to the data layer.

2. **Pre-signed URLs.** The data layer generates a pre-signed URL with a short TTL. The client uses the URL directly with the bucket.

**Decision:** Pre-signed URLs.

**Reasoning:**

- The data layer is for metadata, not for binary content. Proxying audio through it adds load and latency.
- Pre-signed URLs are a native S3 feature. The SDK generates them.
- The 5-15 minute TTL is short enough to be safe, long enough to allow normal usage.

**Consequences:**

- Pre-signed URL generation is centralized in the data layer. Audit it before deploying.
- The TTL is a security control. Don't set it too long.
- A common bug: signing for the wrong bucket. Centralized generation prevents this.

---

## How to add a new ADR

When you make a significant architectural decision, document it as an ADR. The format:

```markdown
# ADR-NNN: <Title>

**Status:** Proposed | Accepted | Superseded | Deprecated

**Context:** What is the situation that requires a decision?

**Options considered:** What were the alternatives?

**Decision:** What was decided?

**Reasoning:** Why was this option chosen?

**Consequences:** What are the trade-offs? What does this commit us to?
```

Add the file to `docs/adr/` and link it from this index. Future contributors will read the ADRs before making related decisions.

---

## Next

You've read the full architecture documentation. Next steps:
- Try to [deploy your own instance](07-deploy-your-own.md) following the step-by-step guide
- Read the [workflows](../workflows/) for day-2 operations
- If you find something the docs got wrong, [open an issue](../../CONTRIBUTING.md)
