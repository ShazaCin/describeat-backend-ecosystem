# 03 — Data Model

> Four core entities, three supporting tables. That's the whole model.

---

## The shape

DescribeAT's data model is intentionally small. The system's apparent complexity comes from how the entities relate, not from how many there are.

```
┌──────────┐       ┌────────────┐
│  Title   │ 1────∞│  AD Track  │
│          │       │            │
└──────────┘       └────────────┘
     │                    │
     │                    │
     │ 1               ∞  │
     │                    │
     ∞                    │
┌──────────────────┐      │
│   Categories     │      │
│  (many-to-many   │      │
│   with titles)   │      │
└──────────────────┘      │
                          │
┌──────────────────┐      │
│  User Feedback   │      │ (referenced by)
│  (per user)      │      │
└──────────────────┘      │
                          │
┌──────────────────┐      │
│ User Notification│──────┘ (notifications may reference titles)
│  (per user)      │
└──────────────────┘

Supporting tables (not in the diagram):
  - FCM Tokens (per user, per device)
  - Audit Log (per admin action)
```

---

## The 4 core entities

### Title

A movie or TV show. The unit a user browses, the unit a T2S match returns, the unit an AD track attaches to.

**Fields:**

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `titleId` | UUID | yes | Primary key. The ID returned by the T2S match. |
| `title` | String | yes | Display name. May contain the year in parentheses. |
| `year` | Int | no | Release year. |
| `language` | [String] | yes | ISO 639-1 codes (`en`, `es`, `fr`, etc.). One or more. |
| `genre` | [String] | no | Free-text tags. Used for filtering. |
| `runtimeMinutes` | Int | no | Used to validate the AD track length is plausible. |
| `releaseDate` | Epoch ms | no | When the title was first available. |
| `rated` | String | no | Local content rating (`"9"`, `"12"`, `"TV-14"`, etc.). |
| `score` | Float | no | Aggregated user rating. 0–10. |
| `actors` | [String] | no | Top-billed actors. |
| `writers` | [String] | no | Screenwriters / showrunners. |
| `narrators` | [String] | no | Who narrated the AD track(s). |
| `images` | [String] | no | S3 keys for poster images. Resolved to CDN URLs at read time. |
| `wheretowatch` | [String] | no | Streaming service names. |
| `publicEnabled` | Int (0/1) | yes | **Critical field.** 0 = not visible to listeners; 1 = visible. Default 0. |
| `fingerprintingProgress` | Int (0–100) | yes | How much of the title's audio has been fingerprinted. 100 = ready to match. |
| `createdAt` | Epoch ms | yes | Audit field. |
| `updatedAt` | Epoch ms | yes | Audit field. |

**The two fields that matter most:**

- `publicEnabled` — Without this, private content leaks to listeners. Always check this in the data layer's resolver before returning a title to a listener.
- `fingerprintingProgress` — A title with `fingerprintingProgress < 100` cannot be matched by T2S. Listeners will get a "no match" result even if they're watching the right thing.

**Example (anonymised):** See [`../data-examples/titles.sample.json`](../data-examples/titles.sample.json).

---

### AD Track

A single audio description track for a Title. One title can have many AD tracks (different languages, different narrators, different describer productions).

**Fields:**

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `trackId` | UUID | yes | Primary key. |
| `titleId` | UUID | yes | Foreign key to Title. |
| `language` | String | yes | ISO 639-1. The language of the narration. |
| `narrator` | String | yes | Who narrated this track. |
| `description` | String | no | Track-specific metadata (e.g. "Director's cut with extended descriptions"). |
| `trackUrl` | String | yes | The CDN URL where the audio file is served from. Public-readable. |
| `durationSeconds` | Int | yes | Length of the AD track. |
| `fileSizeBytes` | Int | no | For client-side capacity planning. |
| `createdAt` | Epoch ms | yes | Audit field. |

**The pairing:** When T2S returns a match for a Title, the app queries for the AD Track(s) associated with that Title, picks the one matching the user's language preference, and plays it from the returned offset.

**One Title → Many AD Tracks pattern:** This is how multilingual support works. A Title might have an English track, a Spanish track, and a French track. The user picks their language in settings; the app filters AD tracks by that language.

**Example:** See [`../data-examples/ad-tracks.sample.json`](../data-examples/ad-tracks.sample.json).

---

### User Feedback

A bug report, content request, or general feedback submitted by a listener.

**Fields:**

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `feedbackId` | UUID | yes | Primary key. |
| `userId` | String | yes | The submitter's user ID (Cognito sub). |
| `userEmail` | String | no | For admin reply. May be null if the user signed in with a privacy-focused email. |
| `feedbackType` | Enum | yes | `bug`, `content_request`, `general`. |
| `subject` | String | yes | One-line summary. |
| `message` | String | yes | The body. May be long. |
| `attachments` | [String] | no | S3 keys for any uploaded screenshots or audio. |
| `status` | Enum | yes | `new`, `in_progress`, `resolved`, `wontfix`. Defaults to `new`. |
| `adminNotes` | String | no | Internal notes, not visible to the user. |
| `respondedBy` | String | no | Admin user ID who responded. |
| `respondedAt` | Epoch ms | no | When the admin responded. |
| `createdAt` | Epoch ms | yes | Audit field. |

**Authorization rules:**
- Listeners can create feedback for themselves (`userId == sub`)
- Listeners can read their own feedback only
- Admins can read all feedback
- Only admins can update `status`, `adminNotes`, `respondedBy`, `respondedAt`

**Example:** See [`../data-examples/user-feedback.sample.json`](../data-examples/user-feedback.sample.json).

---

### User Notification

A message sent to a listener (or a group of listeners) by an admin.

**Fields:**

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `notificationId` | UUID | yes | Primary key. |
| `title` | String | yes | Headline. |
| `body` | String | yes | The message. |
| `recipientUserIds` | [String] | no | Direct recipients. Mutually exclusive with `recipientGroup`. |
| `recipientGroup` | String | no | Group name (e.g. `all_users`, `beta_testers`). Mutually exclusive with `recipientUserIds`. |
| `deepLink` | String | no | Where the app should navigate when the user taps the notification. |
| `imageUrl` | String | no | Optional notification image. |
| `createdBy` | String | yes | Admin user ID. |
| `createdAt` | Epoch ms | yes | Audit field. |
| `scheduledFor` | Epoch ms | no | If set, send at this time, not immediately. |
| `sentAt` | Epoch ms | no | When the send actually happened. |
| `deliveryStatus` | Enum | yes | `pending`, `sending`, `delivered`, `partial_failure`, `failed`. |

**Authorization rules:**
- Listeners can read notifications addressed to them only
- Only admins can create notifications
- Only admins can update `deliveryStatus`

**Example:** See [`../data-examples/user-notifications.sample.json`](../data-examples/user-notifications.sample.json).

---

## The 3 supporting tables

### Categories

Groupings of titles for browsing. Many-to-many with titles.

**Fields:**

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `categoryId` | UUID | yes | Primary key. |
| `name` | String | yes | Display name. |
| `description` | String | no | One-line description for the home page. |
| `imageUrl` | String | no | Category icon. |
| `orderIndex` | Int | yes | Display order on the home page. |
| `enabled` | Boolean | yes | Show or hide. |
| `createdAt` | Epoch ms | yes | Audit field. |

**The `titleCategories` join table:**

| Field | Type | Notes |
|-------|------|-------|
| `titleId` | UUID | Foreign key. |
| `categoryId` | UUID | Foreign key. |
| `orderIndex` | Int | Per-title ordering within the category. |

**Example:** See [`../data-examples/categories.sample.json`](../data-examples/categories.sample.json).

---

### FCM Tokens

The device push tokens that link a user to their phone's notification service.

**Fields:**

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `tokenId` | UUID | yes | Primary key. |
| `userId` | String | yes | Cognito sub. |
| `deviceToken` | String | yes | The actual FCM/APNs token. |
| `platform` | Enum | yes | `web`, `ios`, `android`. |
| `userAgent` | String | no | For debugging. |
| `lastSeenAt` | Epoch ms | yes | Updated on every successful push. |
| `createdAt` | Epoch ms | yes | Audit field. |

**Lifecycle:** When a user grants notification permission, the app generates a device token and writes a row. When a user revokes permission, the row is deleted. When a push fails (e.g. the user uninstalled the app), the token is marked as invalid and pruned.

---

### Audit Log

Every admin action, time-stamped, user-attributed. Immutable.

**Fields:**

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `logId` | UUID | yes | Primary key. |
| `timestamp` | Epoch ms | yes | When the action happened. |
| `actorUserId` | String | yes | Who did it. |
| `actorEmail` | String | yes | For human readability. |
| `action` | String | yes | What they did. Use a verb-noun format: `title.create`, `title.update`, `notification.send`, `user.delete`. |
| `entityType` | String | yes | What they did it to: `title`, `ad_track`, `notification`, `user`. |
| `entityId` | String | no | The ID of the affected entity. |
| `before` | Object | no | State before (for updates). |
| `after` | Object | no | State after (for creates/updates). |
| `ipAddress` | String | no | For security audits. |
| `userAgent` | String | no | For security audits. |

**Why immutable:** Once written, an audit log row is never updated. If you need to "correct" an audit row, write a new row that references the old one. This is how legal compliance audits work — the log is evidence that cannot be retroactively changed.

**What to log:**
- Every admin creates/updates/deletes of any entity
- Every notification sent
- Every admin sign-in (success and failure)
- Every user permission change

**What NOT to log:**
- Listener activity (too high volume, not security-relevant)
- Audio bytes or hash data (sensitive, large)
- User passwords or tokens (security rule, never log these)

---

## Schema drift — the silent bug

A common problem: the schema gets updated, but the actual stored data still has fields from the old schema (or fields that were never in the schema but got written anyway). When a client queries a field that's in the data but not in the schema, the query fails with a GraphQL "field not found" error.

**How this happens:**
1. An admin writes a title with a new field `score` (not in the schema yet)
2. The schema gets updated to include `score`
3. The schema gets updated again to remove `score` (refactor)
4. The data still has `score` rows from step 1
5. A client queries for `score` and gets an error

**How to detect it:**
- Periodically (e.g. monthly) export a sample of data from each table
- Diff the sample fields against the current schema
- Flag any field that's in the data but not the schema (or vice versa)

**How to handle it:**
- For fields in data but not schema: either add them to the schema (if they're useful) or migrate the data to remove them
- For fields in schema but not data: either populate them (if they're required) or make them optional
- Never delete a schema field without first checking that no data uses it

---

## Relationships — the ER diagram in text

```
Title (1) ──────── (∞) AD Track         [via titleId]
Title (∞) ──────── (∞) Categories       [via titleCategories]
User Feedback (∞) ── (1) User            [via userId]
User Notification (∞) ── (1) User       [via recipientUserIds or recipientGroup]
FCM Tokens (∞) ──── (1) User            [via userId]
Audit Log (∞) ───── (1) Admin User      [via actorUserId]
User Notification (∞) ── (0..1) Title   [via deepLink if it's a title deep link]
```

There is no direct relationship between AD Track and User. The only way a user "gets" an AD track is by triggering T2S to identify a title, and then the data layer returns the AD track(s) for that title.

---

## Sample data

All four entities plus categories have anonymised sample data in [`../data-examples/`](../data-examples/). Use these to:

- Seed your local development environment
- Validate your data layer's resolvers handle the field types correctly
- Test your admin portal UI against real-world variations
- Onboard new contributors — they can see what real data looks like

The samples are CC-BY-4.0. Use them freely, attribute this repo.

---

## Next

- [`04-t2s-sync-engine.md`](04-t2s-sync-engine.md) — the engine that matches against Title records
- [`05-storage-cdn.md`](05-storage-cdn.md) — where the audio files for AD Track records live
- [`06-notifications.md`](06-notifications.md) — the engine that delivers User Notification records
