# 00 — Overview

> **Start here.** This is the 15-minute orientation for the DescribeAT backend.

---

## What problem does DescribeAT solve?

Audio description (AD) tracks for movies and TV shows are typically locked inside proprietary platforms (Netflix AD, YouTube AD, MovieReading) that require the user to manually find the title they're watching, install a specific app, or hold a subscription.

DescribeAT removes that friction. The listener points the app at whatever's playing on their TV, taps "sync," and the system handles identification and synchronisation automatically. To the user, it's a single button.

For a blind or visually impaired user, this is the difference between "I can watch any movie I want" and "I can only watch what's on Netflix's AD catalogue this month."

---

## The four flows

The backend supports four distinct flows. Understanding them up front makes the rest of the architecture make sense.

### 1. The listener sync flow (the core experience)

```
[Listener's phone, app open]
        |
        |  (1) user taps "Sync"
        v
[App records ~10s of ambient audio from the TV via the device microphone]
        |
        |  (2) POST /t2s/sync (Content-Type: audio/mpeg, body = MP3 blob)
        v
[Edge CDN forwards the binary upload to the fingerprinting engine]
        |
        |  (3) engine generates audio fingerprint hashes from the clip
        |      and looks up matches in the hash database
        v
[Engine responds with: matched title ID + offset (where in the AD track to start)]
        |
        |  (4) app queries the data layer for the title's metadata
        |      (poster, description, available AD tracks, etc.)
        v
[App queries the storage layer for the AD track audio file]
        |
        |  (5) app plays the AD track from the matched offset
        v
[User hears audio description in sync with the show]
```

**This is the flow DescribeAT exists for.** Everything else exists to support it.

### 2. The content upload flow (admin side)

```
[Admin user, logged into the admin portal]
        |
        |  (1) admin uploads a new title + AD track audio + poster image
        v
[Admin portal writes metadata to the data layer (AppSync mutation)]
        |
        |  (2) admin portal uploads the AD track audio to object storage
        v
[S3 upload triggers the fingerprinting pipeline]
        |
        |  (3) the audio track is fingerprinted and the hashes are added
        |      to the hash database
        v
[Title is now available to listeners via flow #1]
```

### 3. The notification flow

```
[Admin user sends a push notification to a user or user group]
        |
        |  (1) admin writes a notification record to the data layer
        v
[Notification service picks up the record and looks up the recipient's
 device tokens from the token table]
        |
        |  (2) service sends a push to the device via the platform's
        |      push service (Firebase Cloud Messaging, Apple Push, etc.)
        v
[Listener's device shows the notification]
```

### 4. The feedback flow

```
[Listener submits in-app feedback (bug report, content request)]
        |
        |  (1) app writes a feedback record to the data layer
        v
[Admin sees new feedback in the admin portal]
        |
        |  (2) admin triages, responds, marks as resolved
```

---

## The high-level component map

The backend has six logical components. Each is detailed in its own doc.

| # | Component | What it does | Document |
|---|-----------|--------------|----------|
| 1 | **Edge / CDN** | Static asset delivery, binary upload handling, edge caching | [`01-architecture.md` §Edge layer](01-architecture.md#edge--cdn) |
| 2 | **Auth** | User authentication, account model, OAuth for web, JWT for API | [`02-auth.md`](02-auth.md) |
| 3 | **Data layer** | The 4 core entities (titles, AD tracks, user feedback, notifications) | [`03-data-model.md`](03-data-model.md) |
| 4 | **T2S sync engine** | Audio fingerprinting — the heart of the system | [`04-t2s-sync-engine.md`](04-t2s-sync-engine.md) |
| 5 | **Storage / CDN** | Audio files, poster images, content distribution | [`05-storage-cdn.md`](05-storage-cdn.md) |
| 6 | **Notifications** | Push to listener devices (FCM, APNs) | [`06-notifications.md`](06-notifications.md) |

Visual: see [`diagrams/01-overview.svg`](../diagrams/01-overview.svg).

---

## What's an "AD track"?

For newcomers to audio description: an AD track is a separate audio file containing spoken narration of the visual elements of a movie/TV show — the character who just entered the room, the text on the screen, the expression on someone's face. The narration is recorded to fit in the natural gaps between dialogue.

DescribeAT does not produce AD tracks. It **synchronises** them. A describer (a trained professional) produces the AD track, uploads it to DescribeAT via the admin portal, and from that point on any listener can have that narration play in time with the show they're watching.

---

## What's an "audio fingerprint"?

When the user records 10 seconds of audio from their TV, the system needs to figure out *what* they recorded. It cannot compare the raw audio (different speakers, different room acoustics, different TV volume settings) — instead it extracts a **fingerprint**: a compact representation of the audio's distinctive features that is stable across re-recordings of the same source.

The fingerprinting process is: take the audio → break it into short windows → for each window, identify the loudest frequency peaks → create a hash from pairs of peaks (one early, one later) → store those hashes in a database.

When a clip comes in to be matched, the same process produces hashes for it, and the system asks: which fingerprints in the database overlap with these hashes? The answer is the match.

The accuracy of this approach is high for clean studio recordings and degrades for noisy real-world audio (the user recording in a living room with background noise). Tuning the fingerprinting engine for real-world conditions is one of the harder problems in the system. See [`04-t2s-sync-engine.md`](04-t2s-sync-engine.md) for the engineering details.

---

## What's the data model?

Four core entities. Just four. The system's apparent complexity comes from how they relate, not from how many there are.

- **Title** — a movie or show. Has metadata (title, year, language, genre, posters, runtime).
- **AD Track** — a single audio description track for a Title, in one language, by one narrator. Belongs to a Title.
- **User Feedback** — a bug report or content request from a listener.
- **User Notification** — a message sent to a listener (or a group of listeners).

Plus three supporting tables:
- **Categories** — groupings of titles (e.g. "Movies", "TV Series", "Documentaries").
- **FCM Tokens** — the device push tokens that link a user to their phone's notification service.
- **Audit Log** — every admin action, time-stamped, user-attributed.

Full schema and sample data: [`03-data-model.md`](03-data-model.md).

---

## How big is this?

Realistic numbers for a small-to-medium self-hosted deployment:

| Resource | Approximate size | Notes |
|----------|------------------|-------|
| Code (this + the app repo) | ~50k lines | Mostly TypeScript, some Python for the engine |
| Documentation (this repo) | ~30k words | The reading time for the full pack |
| AD tracks in catalogue | 100–10,000 | Depends entirely on your describer pipeline |
| Audio fingerprints in DB | ~10× the AD track count | Hashes, not raw audio |
| Listeners | 100–100,000 | The cost scales with listener count, not catalogue |
| Monthly AWS cost (small) | $50–150 | See [`08-cost-estimates.md`](08-cost-estimates.md) for the breakdown |

---

## What's next?

- **For architects:** read [`01-architecture.md`](01-architecture.md).
- **For self-hosters:** skip to [`07-deploy-your-own.md`](07-deploy-your-own.md).
- **For the curious:** read the four flows above once more, then look at the overview diagram. Everything else is detail.

---

*This is a living document. If you find something the docs got wrong, open an issue — see [`CONTRIBUTING.md`](../CONTRIBUTING.md).*
