# 01 — Architecture

> The reference architecture: what components exist, how they connect, and why the design is shaped the way it is.

---

## 1. Mental model

DescribeAT's backend is a **request/response system** with a **batch fingerprinting pipeline** attached to it. The first handles the listener's real-time sync requests; the second produces the fingerprints those requests are matched against.

```
                    ┌─────────────────────────────────────────┐
                    │  Listener device (PWA)                  │
                    │  Microphone → MP3 → POST to T2S         │
                    │  Receives: title ID + offset            │
                    │  Plays: AD track from offset            │
                    └────────────────┬────────────────────────┘
                                     │
                                     ▼
                    ┌─────────────────────────────────────────┐
                    │  Edge layer                             │
                    │  TLS termination, request routing,      │
                    │  static asset cache, binary upload      │
                    │  proxy                                   │
                    └────┬───────────────┬───────────────┬────┘
                         │               │               │
              ┌──────────┘               │               └──────────┐
              ▼                          ▼                          ▼
   ┌──────────────────────┐  ┌──────────────────────┐  ┌──────────────────────┐
   │  Fingerprinting      │  │  Data layer          │  │  Object storage      │
   │  engine (T2S)        │  │  (4 entities +       │  │  (S3-compatible)     │
   │  - Hash match        │  │   supporting tables) │  │  - AD track audio    │
   │  - Real-time API     │  │  - GraphQL API       │  │  - Poster images     │
   │  - Always-on service │  │  - Per-user auth     │  │  - Reference audio   │
   └──────────┬───────────┘  └──────────┬───────────┘  └──────────┬───────────┘
              │                         │                         │
              │                         │                         │
              ▼                         ▼                         ▼
   ┌──────────────────────┐  ┌──────────────────────┐  ┌──────────────────────┐
   │  Hash database       │  │  Auth provider       │  │  CDN                 │
   │  (Fingerprint store) │  │  (Cognito-compatible)│  │  (Public asset URLs) │
   │  - Title → hashes    │  │  - App users pool    │  │  - Edge cached       │
   │  - Updated by        │  │  - Admin users pool  │  │  - Geo-distributed   │
   │    pipeline          │  │  - OAuth for web     │  │                      │
   └──────────────────────┘  └──────────────────────┘  └──────────────────────┘
```

Visual: see [`diagrams/01-overview.svg`](../diagrams/01-overview.svg).

---

## 2. The components

### 2.1 Edge / CDN layer

**Purpose:** terminate TLS, route requests, cache static assets, proxy binary uploads to the fingerprinting engine.

**Why:** A single global endpoint is much easier to integrate with mobile clients than per-region endpoints. The CDN also absorbs traffic spikes (a popular show's AD being requested by thousands of listeners simultaneously).

**Responsibilities:**
- TLS termination (ACM or equivalent certificate)
- Route `/t2s/*` to the fingerprinting engine
- Route `/api/*` to the data layer
- Route `/*` to the static asset bucket (the PWA itself)
- Cache static assets aggressively (1 year for hashed bundles, 5 minutes for HTML)
- Compress text responses (gzip, brotli)
- Reject malformed requests at the edge (size limits, content-type checks)

**What it is NOT responsible for:**
- Authentication (handled at the data layer, not the edge)
- Business logic (the edge is a router, not a controller)
- Long-lived connections (the edge is HTTP/1.1 + HTTP/2 only; no WebSockets, no SSE)

**Common implementations:** AWS CloudFront + API Gateway, Cloudflare + Workers, Fastly + Compute@Edge. The choice matters less than the contract — keep the edge dumb, push logic inward.

---

### 2.2 Fingerprinting engine (T2S)

**Purpose:** match an incoming audio clip against the hash database and return the matched title + offset.

**Why a dedicated service:** Fingerprint matching is computationally heavy. A single matching request takes ~1–3 seconds of CPU time on modern hardware. Doing this in a stateless function on demand (Lambda-style) is technically possible but cost-prohibitive at any meaningful scale — you want a long-running service that keeps the hash database in memory.

**The "always-on vs. on-demand" split:**

The original production deployment used a two-service pattern that is worth preserving:

- **Real-time matcher:** always on, ~0.5 vCPU, holds the hash database in memory. Handles listener sync requests. ~$30/month.
- **Batch fingerprinter:** on-demand, scales to zero, ~4 vCPU. Runs only when a new AD track is uploaded, produces the hashes for that track, writes them to the database, then scales back to zero. Saves the cost of running 4 vCPU 24/7 (~$80/month at on-demand pricing).

**Why this matters for self-hosters:** Don't try to fingerprint on the same machine that does matching. The CPU profiles are different (steady small load vs. burst large load), the lifecycle is different (24/7 vs. triggered), and conflating them leads to a system that thrashes.

**The matching API contract:**

```http
POST /t2s/sync?filename={userId}_{timestamp}.mp3
Content-Type: audio/mpeg
Content-Length: <bytes>
Transfer-Encoding: chunked
Body: <MP3 audio bytes>

200 OK
Content-Type: application/json

{
  "status": "SUCCESS",
  "message": {
    "match": {
      "song_id": <integer, internal>,
      "song_name": "<title-uuid>",   ← this IS the titleId
      "input_total_hashes": <int>,
      "fingerprinted_hashes_in_db": <int>,
      "hashes_matched_in_input": <int>,
      "input_confidence": <float 0-1>,  ← threshold: 0.85
      "fingerprinted_confidence": <float 0-1>,
      "offset": <int, sample count>,
      "offset_seconds": <float>,
      "file_sha1": "<hex>"
    },
    "confidence_check_value": 0.85
  }
}
```

When confidence is below the threshold, the response includes `closest_matches[]` — the top N near-misses — for the client to optionally surface as "did you mean...?" suggestions.

**Hash database location:** The original deployment kept the hash database in-process (loaded into memory at startup). For multi-instance deployments, you'll want a shared store — DynamoDB, Redis, or an EFS volume mounted to all matcher instances. The choice depends on your scale.

**Closed-source note:** The original fingerprinting library is closed source. The architecture accommodates open-source substitutes (Dejavu is the canonical one) with the caveat that match accuracy will be lower on noisy real-world audio. See [`04-t2s-sync-engine.md`](04-t2s-sync-engine.md) for the full trade-off discussion.

---

### 2.3 Data layer (4 entities + 3 supporting tables)

**Purpose:** store all durable state — title metadata, AD track metadata, user feedback, notifications, and the supporting tables that make those work.

**Why a dedicated data layer:** The fingerprinting engine is read-mostly, write-rarely. The data layer is the opposite — heavy read, heavy write, with complex authorization (users see their own feedback, admins see all feedback, public titles are public, private titles are admin-only). Separating them lets each be scaled and evolved independently.

**The 4 core entities:**

| Entity | Description | Read pattern | Write pattern |
|--------|-------------|--------------|---------------|
| **Title** | A movie/TV show | All listeners, all the time | Rare, admin-only |
| **AD Track** | An audio description track for a title | All listeners, all the time | Rare, admin-only |
| **User Feedback** | Bug reports / content requests from listeners | Per-user (own), admin (all) | Per-user, on demand |
| **User Notification** | A message sent to a listener | Per-user (own), admin (all) | Admin-only |

**The 3 supporting tables:**

| Table | Purpose |
|-------|---------|
| **Categories** | Groupings of titles for browsing |
| **FCM Tokens** | Device push tokens, one or more per user |
| **Audit Log** | Every admin action, immutable, time-stamped |

**API style:** GraphQL is the natural fit — clients query exactly the fields they need, the schema is a single source of truth, and authorization is enforced at the resolver level. REST is workable but you'll end up building a poor GraphQL. AWS AppSync is the easiest managed option; Hasura + Postgres is the most portable self-hosted option.

**Schema vs data drift — important warning:** Schema evolves. Real data accumulates fields the schema doesn't know about. If you query for a field that exists in the data but not in the schema, you'll get an error. Audit your schema quarterly against the actual stored data. See [`03-data-model.md`](03-data-model.md) §"Schema drift" for a worked example.

---

### 2.4 Auth

**Purpose:** verify who is calling, enforce who can see/do what.

**The two-pool model:**

DescribeAT has two distinct user populations, and they have different authorization rules:

| Pool | Who | Can do |
|------|-----|--------|
| **App pool** | Listeners (blind/VI users of the app) | Read public titles, read own feedback/notifications, write own feedback, write own FCM tokens |
| **Admin pool** | Content managers, describer pipeline operators, support staff | Read all titles, write titles, send notifications, read all feedback, manage users |

**Why two pools, not one with roles:** The two pools use different OAuth client configurations, different allowed email domains, different session lifetimes, and different MFA requirements. A single pool with role-based access works for the first 100 users and then becomes a maintenance burden. Two pools is the right shape from day one.

**Critical warning — DO NOT MERGE THE POOLS:** A future contributor will be tempted to "simplify" by merging the two pools into one with role-based access. **Resist this.** The two pools are configured differently on purpose: the admin pool has a hard-coded allowlist of email domains, the app pool does not. A merged pool either loses the admin allowlist (insecure) or imposes it on all users (impossible — listeners need to be able to use any email). See [`02-auth.md`](02-auth.md) for the full configuration.

**OAuth for web, JWT for API:** Web clients use OAuth (Google sign-in via the hosted UI). Backend-to-backend calls (admin portal → AppSync, app → T2S) use JWTs from the user pool. The choice of auth flow per client is deliberate.

---

### 2.5 Storage / CDN

**Purpose:** store the actual audio and image files; serve them to listeners with low latency worldwide.

**Two buckets (or equivalent) by design:**

| Bucket | Contents | Access |
|--------|----------|--------|
| **Public** | AD track audio, poster images | World-readable, CDN-fronted |
| **Private** | Reference audio (used for fingerprinting), admin uploads in progress | Not public, signed URLs only |

**Why two:** Reference audio and AD track audio are different things. Reference audio is the original movie/TV audio (used to generate fingerprints). AD track audio is the narration (played to listeners). They have different access patterns and different licensing implications. Mixing them is a security and licensing risk.

**CDN caching rules:**
- Hashed bundles (e.g. `app.a3f8b2c.js`): 1 year, immutable
- HTML: 5 minutes, must-revalidate
- AD track audio: 30 days, range-request friendly
- Poster images: 30 days

**Anti-pattern — caching audio with status-0 (opaque) responses:** If your CDN caches responses that don't have a real HTTP status, you'll serve corrupted audio to listeners. Set `statuses: [200]` on cache rules, never `[0, 200]`. This bit the original deployment in 2026 and is a common silent-failure trap. See [`workflows/incident-response.md`](../workflows/incident-response.md) for the diagnosis recipe.

---

### 2.6 Notifications

**Purpose:** push messages from admins to listener devices.

**Two paths exist in the original design. Use only the live one.**

The original production deployment has two push paths, of which only one is live:

- **Live path:** admin portal → Lambda → Firebase Cloud Messaging (FCM) → device. Simple, direct, works.
- **Orphaned path:** notification record → DynamoDB stream → SQS → Lambda → FCM. This path's trigger is broken (the Lambda's event source mapping has an empty `FunctionName`). Do not try to fix this. If you want queue-based notification delivery, build it fresh.

**Token registration:** When a listener installs the PWA and grants notification permission, the app generates a device token via FCM (or APNs on iOS), and registers it with the backend by writing a row to the FCM tokens table. The registration requires a valid user JWT. Tokens are tied to a userId (the Cognito sub), not to a device — a user with two devices gets two rows in the table.

**iOS-specific requirement:** iOS push requires the PWA to be **added to the home screen** and the iOS version to be 16.4 or later. Browser-tab push is not supported on iOS. This is an Apple platform limitation, not a DescribeAT limitation.

**iOS VoiceOver trap:** The notification settings UI must use `role="alert"` for error states and `role="status" aria-live="polite"` for loading states. Without these, VoiceOver users see the notification toggle as a button that "does nothing" because the spinner appears and disappears silently. See [`06-notifications.md`](06-notifications.md) §"Accessibility" for the full pattern.

---

## 3. The request flows in detail

### 3.1 Listener sync request (the hot path)

```
1. User taps "Sync" in the app
2. App starts recording (MediaRecorder API)
3. App stops recording after ~10s, encodes to MP3 via WASM
4. App POSTs the MP3 to https://{edge}/t2s/sync?filename={userId}_{ts}.mp3
   - Content-Type: audio/mpeg
   - Content-Length: <exact>
   - Transfer-Encoding: chunked
5. Edge routes to the matching engine
6. Engine:
   a. Validates Content-Type and size
   b. Generates hashes from the MP3
   c. Looks up the hashes in the hash database
   d. Calculates the confidence score for each candidate
   e. Returns the best match (if above 0.85) or closest_matches[]
7. App receives the response
8. If matched:
   a. App queries the data layer: `query { getTitle(id: <song_name>) { ... } }`
   b. Verifies `publicEnabled == 1` (private titles are not exposed to listeners)
   c. App resolves the AD track's storage URL via the storage service
   d. App plays the AD track from `offset_seconds`
9. If not matched:
   a. App shows the user "We couldn't identify what you're watching"
   b. Optionally shows closest_matches[] as "Did you mean...?"
```

**Latency budget:** The user expects a result in under 3 seconds. The fingerprint match takes 1–3 seconds. Everything else must complete in <1 second combined. This puts a hard cap on cold-start time for the matching engine.

**What can go wrong (and the order to diagnose):**
1. Edge returns 5xx → check edge config, check origin health
2. Edge returns 200 with empty body → check audio Content-Type (must be `audio/mpeg`, not `audio/mp3`)
3. Engine returns SUCCESS but `input_confidence < 0.85` → check hash database population
4. Engine returns SUCCESS with wrong match → check noise threshold on the fingerprinting library
5. App receives match but no title in data layer → check the song_name → titleId mapping

---

### 3.2 Admin uploads a new title

```
1. Admin opens the admin portal
2. Admin enters title metadata + uploads AD track audio + uploads poster
3. Admin submits
4. Admin portal:
   a. Uploads the AD track audio to the public storage bucket (signed PUT)
   b. Uploads the poster image to the public storage bucket (signed PUT)
   c. Triggers a Lambda to start the fingerprinting pipeline
   d. Writes a Title record to the data layer with status=fingerprinting
5. Lambda starts a new on-demand fingerprinter task
6. Fingerprinter:
   a. Downloads the AD track audio from the public bucket
   b. Generates hashes
   c. Writes the hashes to the hash database
   d. Updates the Title record's `fingerprinting_progress` field
   e. Scales itself to zero
7. Admin portal refreshes; title now shows fingerprinting_progress=100
8. Title is available to listeners
```

**Cost note:** the on-demand fingerprinter scales to zero, so you only pay for fingerprinting when there's actual work to do. This saves ~$60–80/month vs. an always-on fingerprinter at the cost of ~30s of cold-start latency per new title.

---

### 3.3 Push notification flow

```
1. Admin composes a notification in the admin portal
2. Admin clicks "Send"
3. Admin portal writes a UserNotification record to the data layer
4. Admin portal invokes a Lambda with the notification ID
5. Lambda:
   a. Looks up the recipient's FCM tokens from the FCM Tokens table
   b. For each token, calls FCM (or APNs) with the notification payload
   c. Marks the notification record as delivered (with per-token success/failure)
6. Listener's device shows the notification
```

---

### 3.4 Feedback flow

```
1. Listener opens the in-app feedback form
2. Listener types message, optionally attaches a screenshot
3. Listener submits
4. App writes a UserFeedback record to the data layer
5. Admin sees the new feedback in the admin portal's feedback queue
6. Admin responds, marks as resolved
```

---

## 4. What the edge does NOT do

- **Authenticate the user.** Auth happens at the data layer, not the edge. The edge only checks that a request has a valid auth header if the route requires it.
- **Enforce authorization rules.** The data layer's resolvers enforce "user can only see their own feedback" rules, not the edge.
- **Cache API responses.** API responses are user-specific and should not be cached at the edge. Only static assets and binary uploads go through CDN caching.
- **Run business logic.** The edge is a router. If you find yourself putting business logic in edge functions, you're building a system that will be impossible to debug.

---

## 5. What to scale first

If you self-host and start hitting scale limits, scale in this order:

1. **CDN** — cheapest, most effective. Static assets and AD track audio should be edge-cached aggressively.
2. **Matching engine horizontal scaling** — run 2-4 instances behind a load balancer. Each holds the hash database in memory.
3. **Data layer read replicas** — if you have many listeners, read-heavy workloads scale horizontally via read replicas.
4. **On-demand fingerprinter** — already scales to zero by default; only scale if single-fingerprinter is too slow for your upload volume.

**Do not scale the data layer's write throughput** before exhausting read-side options. Writes are the expensive part.

---

## 6. The cross-cutting concerns

These cut across all four flows:

### 6.1 Logging

Every component emits structured JSON logs. The log line includes: timestamp, request ID, user ID (if authenticated), component, action, result, duration_ms. Logs are shipped to a central store (CloudWatch, Datadog, ELK, your choice). **Do not log the audio blob bytes. Do not log the hash database contents.**

### 6.2 Metrics

Each component emits standard metrics: request count, error rate, latency p50/p95/p99, queue depth. The matching engine additionally emits: match confidence distribution, match rate, fingerprinting pipeline duration. Metrics are scraped or pushed to a metrics store (Prometheus, CloudWatch Metrics, Datadog).

### 6.3 Tracing

A request ID is generated at the edge and propagated through all downstream calls. Every log line and metric includes the request ID. This is the only way to debug "why did this specific listener's request fail at 14:23 on Tuesday" — without distributed tracing, you have no way to follow a request through the system.

### 6.4 Error handling

Every component fails closed. If the matching engine can't reach the hash database, the request returns 503. If the data layer can't authenticate the user, the request returns 401, not 500. The system never returns partial data — if any sub-call fails, the whole request fails.

### 6.5 Secret management

API keys, OAuth client secrets, FCM private keys, and any other secret are stored in a managed secret store (AWS Secrets Manager, HashiCorp Vault, your choice). **Never in environment variables. Never in source code. Never in documentation.** This repository contains no real secrets.

---

## 7. What's intentionally NOT documented here

- **The fingerprinting algorithm internals.** Closed source, owned by the original Shazacin partners.
- **The exact Dejavu configuration parameters.** These are tuned per-deployment and depend on your audio characteristics.
- **The OAuth client IDs and secrets.** These are per-deployment; you generate your own.
- **Specific AWS account IDs, region choices, or instance types.** All of those are deployment decisions, not architecture decisions.

What IS documented: the shape of the system, the contracts between components, the patterns to follow. The specifics of your deployment are your responsibility.

---

## Next

- [`02-auth.md`](02-auth.md) — the two-pool auth model, in detail
- [`03-data-model.md`](03-data-model.md) — the 4 entities + 3 supporting tables
- [`04-t2s-sync-engine.md`](04-t2s-sync-engine.md) — the heart of the system
- [`07-deploy-your-own.md`](07-deploy-your-own.md) — step-by-step deployment
