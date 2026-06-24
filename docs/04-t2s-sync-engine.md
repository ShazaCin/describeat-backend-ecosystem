# 04 — T2S Sync Engine

> The audio fingerprinting engine — the heart of DescribeAT.

---

## What T2S does in one sentence

Given a 10-second MP3 clip of someone watching a TV show, T2S returns: "the show is *X*, the user is at offset *Y* in the AD track, with confidence *Z*."

That single sentence is what makes DescribeAT different from "an app where you manually search for a show and play its AD track." Everything else is plumbing.

---

## The two-service pattern

The original production deployment uses two services, not one. The reason is economic: matching is steady-state and light; fingerprinting is bursty and heavy. Conflating them either wastes money (always-on heavyweight) or ruins latency (cold-starting the heavyweight on every match request).

```
┌─────────────────────────────────────────┐
│  Matcher (always on)                    │
│  - 0.5 vCPU, 1 GB RAM                   │
│  - Holds hash DB in memory              │
│  - Handles /t2s/sync POST requests      │
│  - Latency: 1–3s per request            │
│  - Cost: ~$30/month                     │
└─────────────────────────────────────────┘
                    ▲
                    │ (reads from)
                    │
┌─────────────────────────────────────────┐
│  Hash Database                          │
│  - Title ID → set of fingerprint hashes │
│  - Loaded into matcher memory at boot   │
│  - Updated by fingerprinter             │
└─────────────────────────────────────────┘
                    ▲
                    │ (writes to)
                    │
┌─────────────────────────────────────────┐
│  Fingerprinter (on-demand)              │
│  - 4 vCPU, 8 GB RAM                     │
│  - Scales to zero when idle             │
│  - Triggered by AD track upload         │
│  - Cold start: ~30s                     │
│  - Cost: ~$0 when idle, ~$0.50 per      │
│    fingerprint when running             │
└─────────────────────────────────────────┘
```

**The matcher is never blocked by the fingerprinter.** They share the hash database, but they don't share a process. Adding a new title to the hash database does not require restarting the matcher; it does require the matcher to refresh its in-memory cache (handled by periodic reload or SIGHUP, depending on your setup).

---

## How matching works

### Step 1: Receive the audio

```
POST /t2s/sync?filename={userId}_{timestamp}.mp3
Content-Type: audio/mpeg
Content-Length: <exact>
Transfer-Encoding: chunked
Body: <MP3 audio bytes>
```

**The Content-Type matters.** The original engine accepts `audio/mpeg` and rejects everything else. A common bug: clients send `audio/mp3` (non-standard) and get a 415 Unsupported Media Type. The HTTP spec MIME type for MP3 is `audio/mpeg`. Always `audio/mpeg`.

**Why include the filename in the query string:** Logging. When 1,000 requests come in and you need to debug a specific one, the filename gives you the userId and timestamp directly. It's a free correlation ID.

### Step 2: Decode and window the audio

The MP3 is decoded to raw PCM samples. The samples are split into overlapping windows (~10ms each, with 50% overlap). Each window is then processed independently.

**Why overlapping windows:** Without overlap, the boundary between windows can miss transient features. With 50% overlap, every part of the audio is in the center of at least one window.

### Step 3: Extract spectral peaks

For each window, take the FFT (Fast Fourier Transform), convert to a spectrogram (frequency vs. time, magnitude as color), and find the loudest peaks.

**The peaks, not the spectrum, are the signal.** A spectral peak is a point in time-frequency space where the audio is significantly louder than its neighbors. Speech, music, and ambient noise all have peaks, but the *positions* of the peaks are stable across re-recordings of the same source.

```
            Spectrogram of a window
            (darker = louder)
        ┌──────────────────────┐
    8kHz│  ░  █  ░  ░  █  ░  ░  │
        │  █  ░  ░  █  ░  ░  █  │
    4kHz│  ░  ░  █  ░  ░  █  ░  │
        │  ░  █  ░  ░  █  ░  ░  │
    2kHz│  █  ░  ░  █  ░  ░  █  │
        │  ░  ░  █  ░  ░  █  ░  │
    1kHz│  ░  █  ░  ░  █  ░  ░  │
        └──────────────────────┘
          0   1   2   3   4  ms
```

**Each `█` is a peak. The pattern of peaks is the fingerprint.**

### Step 4: Hash the peaks into pairs

For each peak, find a later peak (within a configurable time delta and frequency delta). Generate a hash from the pair: `(time1, freq1, time2, freq2) → hash`.

**The pair structure is what makes the fingerprint robust to noise.** A single peak can be created by background noise, but the *relationship* between two peaks (one early, one later, at specific frequencies) is much harder to fake or destroy.

**The result:** a clip of 10 seconds produces ~500–1000 hashes. Each hash is a 32-bit or 64-bit integer.

### Step 5: Look up the hashes in the database

Each hash is looked up in the hash database. The database maps `hash → (titleId, time-offset-in-the-reference-audio)`. For each lookup, you get a list of candidate matches.

**This is the bottleneck step.** With ~5000 hashes in the database and ~500 hashes in the clip, the lookup is ~500 queries. Each query returns ~0–10 candidates. So you end up with ~500–5000 candidate `(titleId, offset)` pairs.

**Most of these are noise.** The signal is the candidate that appears most often with the same offset.

### Step 6: Vote and score

For each unique `(titleId, offset)` pair, count how many of the clip's hashes support it. This is the "votes" count.

The confidence score is then calculated:

```
input_confidence = hashes_matched / input_total_hashes
```

If `input_confidence > 0.85`, it's a match. Return the candidate with the most votes.

If `input_confidence < 0.85`, return the top N candidates as `closest_matches[]` for the client to surface as suggestions.

### The response

```json
{
  "status": "SUCCESS",
  "message": {
    "match": {
      "song_id": 42,
      "song_name": "2b237778-288a-4b05-b075-798804d26537",
      "input_total_hashes": 512,
      "fingerprinted_hashes_in_db": 827308,
      "hashes_matched_in_input": 442,
      "input_confidence": 0.86,
      "fingerprinted_confidence": 0.97,
      "offset": 75650,
      "offset_seconds": 3227.73,
      "file_sha1": "70a3da430fadc9a1162a2105f6b3887da680f892"
    },
    "confidence_check_value": 0.85
  }
}
```

**`song_name` IS the titleId.** The fingerprinting library uses "song" in its vocabulary because it was originally designed for music recognition. In DescribeAT, a "song" is a movie or TV show, and `song_name` is the titleId (UUID) that the data layer expects.

**`offset_seconds` is the seek position in the AD track.** The app plays the AD track starting from this offset. So if the user is watching a movie and is 53 minutes into it, and the AD track is 54 minutes long, the response says "start playing at offset 53:00."

---

## Choosing your fingerprinting engine

You have three options. The original production deployment used a closed-source commercial library. Open-source alternatives are good enough for many use cases, with trade-offs.

### Option 1: Closed-source commercial library (the original)

- **Accuracy:** Highest. Trained on a wide variety of content, including noisy real-world audio.
- **Cost:** Per-match licensing fees, typically negotiated by annual volume.
- **License:** Proprietary. You cannot redistribute, modify, or audit the code.
- **Setup:** Vendor provides a container image or library; you deploy it as the matcher.
- **Best for:** Production deployments with strict accuracy requirements and budget for licensing.

### Option 2: [Dejavu](https://github.com/worldveil/dejavu) (open-source)

- **Accuracy:** High on clean audio, moderate on noisy real-world audio. Expect a 10-20% reduction in match rate compared to commercial options.
- **Cost:** Free, no licensing fees.
- **License:** MIT. You can read, modify, and redistribute the code.
- **Setup:** Python library, well-documented, can be wrapped in a Flask/FastAPI service in a few hours.
- **Best for:** Self-hosted deployments, cost-sensitive projects, contributors who want to learn how fingerprinting works.

**Tuning Dejavu for real-world audio:** The default configuration is tuned for clean studio recordings. For DescribeAT's use case (user recording in a living room with TV audio), you'll want to:

- Lower the peak detection threshold (more peaks = more candidates = more chance of a match)
- Use a longer time delta between paired peaks (allows for more variation in tempo)
- Allow for frequency shifts (TV speakers and laptop speakers have different frequency responses)

These tunings are deployment-specific. Run a calibration session with real recordings of your content before going live.

### Option 3: Build your own

- **Accuracy:** Depends on your investment.
- **Cost:** Engineering time (weeks to months for a basic implementation).
- **License:** Yours.
- **Best for:** Research projects, very specific tuning needs, or if you have a strong opinion about the algorithm.

**Recommendation for most self-hosters:** Start with Dejavu. It works, it's well-understood, and you can replace it later if you need higher accuracy.

---

## How fingerprinting works (the pipeline)

The fingerprinter service runs when a new AD track is uploaded. The pipeline is:

```
[AD track audio uploaded to public storage]
        |
        |  (1) Upload triggers an event
        v
[Event handler starts a new fingerprinter task]
        |
        |  (2) Fingerprinter downloads the audio
        v
[Fingerprinter decodes + windows + extracts peaks + hashes]
        |
        |  (3) Hashes are written to the hash database
        v
[Fingerprinter updates the Title record's fingerprintingProgress field]
        |
        |  (4) Fingerprinter scales itself to zero
        v
[Title is now matchable]
```

**Cost of fingerprinting one track:** ~30 seconds of compute time on 4 vCPU, ~$0.50 in cloud costs. Cheap enough that you can re-fingerprint a track if you tune the algorithm.

**Cold start penalty:** ~30s. This is the time it takes the fingerprinter service to boot, load its dependencies, and start processing. If you upload 100 tracks at once, they queue and process serially. If you have high upload volume, run 2-4 fingerprinter tasks in parallel.

---

## The hash database

The hash database maps `(hash, time_offset) → titleId`. The schema is roughly:

```
hash        | titleId    | time_offset_seconds
----------- | ---------- | -------------------
0xABCD1234  | 2b237778.. | 0
0xABCD1234  | 2b237778.. | 0.1
0xABCD1234  | 2b237778.. | 0.2
...
0xEF567890  | 90b0de82.. | 1234.5
```

**Indexing:** The primary index is on `hash`. Lookups are `WHERE hash = ?`, which is O(log N) with a B-tree index.

**Size:** Each AD track produces ~50,000 hashes (10 minutes of audio, ~85 hashes per second). 1000 AD tracks = 50M hashes = ~5 GB of indexed data. 10,000 AD tracks = 50 GB.

**Storage options:**
- **In-memory (Redis or similar):** Fast, but expensive at scale. Good for the matcher.
- **On-disk (SQLite, Postgres, DynamoDB):** Slower per-lookup but cheap to store. The matcher can load a snapshot of the most popular hashes into memory and fall back to disk for cold hashes.
- **Hybrid:** In-memory cache + on-disk store, with a periodic sync. Most production deployments do this.

**The original production deployment** loaded the entire hash database into matcher memory at boot, then periodically (every 5 minutes) refreshed from the on-disk store. For 10,000 AD tracks, this was ~5 GB of RAM, which is fine for a 16 GB matcher instance.

---

## Known accuracy limitations

Fingerprinting audio is not magic. The following are known to degrade match accuracy:

| Scenario | Impact | Mitigation |
|----------|--------|------------|
| Heavy background noise (other people talking, kitchen sounds) | Match rate drops 20-40% | Tune the peak detection threshold; require longer clips |
| TV speakers vs. phone microphone frequency response mismatch | Match rate drops 10-20% | Allow for frequency shifts in the peak pairing |
| Music-only content (no dialogue) | Match rate stable | This is actually a strength of the algorithm |
| Speech-only content (radio, podcast) | Match rate drops 5-10% | Less spectral variation means fewer distinct peaks |
| Multi-speaker dialogue | Match rate drops 5-15% | Overlapping speech creates dense spectrograms; the algorithm still works but with more candidates |
| Re-encoded audio (different codec) | Match rate stable | This is the algorithm's main strength |
| Volume changes | Match rate stable | Spectral peaks are normalized |
| Speed changes (1.05x playback) | Match rate drops 5-10% | Frequency peaks shift; some implementations handle this explicitly |

**For blind/VI users specifically:** They may be listening in quiet environments (the user wears headphones), so the recording quality is often better than the average. This works in the system's favor.

---

## What to monitor

- **Match rate per request:** how many sync requests return a confident match (>0.85). Should be >70% for a healthy deployment.
- **Match confidence distribution:** are most matches close to the threshold (bad) or well above it (good)?
- **Closest-matches rate:** how often the user gets "did you mean...?" suggestions. High rate = false negatives, investigate.
- **Fingerprinting pipeline duration:** how long it takes to fingerprint a new track. Should be <1 minute for typical AD tracks.
- **Hash database size:** how many hashes are in the database. Track this as your catalogue grows.

---

## Common mistakes when deploying

| Mistake | Symptom | Fix |
|---------|---------|-----|
| Matcher and fingerprinter on the same instance | Matcher latency spikes when a new track is being fingerprinted | Run them on separate instances |
| Hash database not in memory | Matcher latency is 5-10s instead of 1-3s | Load hash DB into memory at boot |
| Confidence threshold too low (e.g. 0.5) | Many false matches, users complain about wrong content | Raise to 0.85 |
| Confidence threshold too high (e.g. 0.95) | Many false negatives, users complain about "doesn't work" | Lower to 0.85 |
| Fingerprinter trigger not wired up | New AD tracks never get fingerprinted, matches fail | Wire up the S3 event trigger or scheduler |
| Using `audio/mp3` Content-Type | Matcher returns 415 | Use `audio/mpeg` |
| Recording quality too low (8kHz) | Match rate drops 30% | Use at least 16kHz, ideally 44.1kHz |
| Hash DB in SQLite on a network filesystem | Slow lookups, network latency | Local disk or in-memory |

---

## Self-hosting checklist

When you deploy your own T2S engine, before going live:

- [ ] Matcher service is running with the hash database loaded in memory
- [ ] Fingerprinter service is wired up to the upload trigger (S3 event, scheduled task, etc.)
- [ ] Hash database is being written to when new AD tracks are uploaded
- [ ] Hash database is being read from by the matcher
- [ ] Confidence threshold is set to 0.85 (or your tuned value)
- [ ] Content-Type validation accepts `audio/mpeg`, rejects other types
- [ ] You have test recordings of 5+ different shows with known titleIds
- [ ] All 5 test recordings return matches with confidence > 0.85
- [ ] You have a monitoring alert for match rate dropping below 50%
- [ ] You have a runbook for re-fingerprinting a track if the algorithm is updated

---

## Next

- [`05-storage-cdn.md`](05-storage-cdn.md) — where the AD track audio files actually live
- [`07-deploy-your-own.md`](07-deploy-your-own.md) — step-by-step deployment
- [`workflows/adding-a-new-title.md`](../workflows/adding-a-new-title.md) — the operational runbook
