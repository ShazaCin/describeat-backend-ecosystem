# Runbook: Adding a new title

> How to add a new title (movie, TV show, etc.) to a DescribeAT deployment, from "the content is finalised" to "listeners can find and match it."

---

## Overview

Adding a new title involves:

1. Preparing the assets (AD track audio, poster image)
2. Uploading to storage
3. Triggering the fingerprinting pipeline
4. Writing the title record to the data layer
5. Verifying the title is matchable

**Total time:** 5-15 minutes per title, depending on track length and fingerprinting pipeline speed.

---

## Prerequisites

Before you start, you need:

- The AD track audio file (MP3 or AAC, 128-192 kbps, mono or stereo)
- The poster image (JPEG or WebP, 800x1200 minimum)
- The title metadata (name, year, language, genre, etc.)
- Admin access to the admin portal
- A verified reference audio (the original movie/TV audio, used to generate fingerprints)

**You cannot skip the reference audio.** The fingerprinting pipeline needs it to generate hashes that will match what listeners record from their TVs.

---

## Step 1: Prepare the assets

### AD track audio

- **Format:** MP3 or AAC. 128-192 kbps is sufficient for speech.
- **Length:** Should match the reference audio length ±5%.
- **Channels:** Mono or stereo. Mono is smaller and works fine.
- **Sample rate:** 44.1 kHz is standard.
- **Normalization:** Normalize to -16 LUFS for consistent loudness.
- **File size:** Typically 5-50 MB for a feature-length track.

### Poster image

- **Format:** JPEG or WebP. JPEG is more compatible.
- **Resolution:** 800x1200 minimum, 1600x2400 ideal.
- **Aspect ratio:** 2:3 (typical movie poster).
- **File size:** 200-500 KB.
- **Color space:** sRGB.

### Reference audio

- **Format:** WAV or FLAC (lossless; lossy codecs degrade fingerprint quality).
- **Sample rate:** 44.1 kHz or 48 kHz. Must match the listener's microphone sample rate.
- **Length:** Should be the full movie/show, or at least the first 30-60 minutes.
- **Channels:** Stereo. Mono is acceptable.

---

## Step 2: Upload to storage

### Upload the AD track and poster to the public bucket

Use the admin portal's upload UI, or the AWS CLI:

```bash
# Upload AD track
aws s3 cp /path/to/track.mp3 s3://{public-bucket}/ad-tracks/pending/track-{trackId}.mp3

# Upload poster
aws s3 cp /path/to/poster.jpg s3://{public-bucket}/posters/pending/poster-{titleId}.jpg
```

The `pending/` prefix is important — it indicates the file is not yet ready for public access. Once the fingerprinting pipeline completes, the file is moved to `ad-tracks/` (no prefix) and made public.

### Upload the reference audio to the private bucket

```bash
aws s3 cp /path/to/reference.wav s3://{private-bucket}/reference-audio/pending/reference-{titleId}.wav
```

The private bucket is not public. Only the fingerprinting service has access via signed URLs.

---

## Step 3: Trigger the fingerprinting pipeline

### Via the admin portal

The admin portal has a "Process" button that triggers the fingerprinting pipeline. Click it after uploading the assets.

### Via the API

If you're scripting the upload:

```bash
# Trigger the fingerprinter
aws lambda invoke \
  --function-name describeat-fingerprinter-trigger \
  --payload '{"titleId":"...","referenceAudioKey":"reference-audio/pending/reference-{titleId}.wav","adTrackKey":"ad-tracks/pending/track-{trackId}.mp3"}' \
  response.json
```

### What happens

The trigger:

1. Starts a new fingerprinter task (or queues it if a task is already running)
2. The fingerprinter downloads the reference audio from the private bucket
3. The fingerprinter generates hashes from the reference audio
4. The fingerprinter writes the hashes to the hash database
5. The fingerprinter updates the title's `fingerprintingProgress` field in the data layer (0 → 25 → 50 → 75 → 100)
6. The fingerprinter scales itself to zero

**Duration:** 30 seconds to 5 minutes, depending on track length and fingerprinter spec.

---

## Step 4: Write the title record

Once the fingerprinting pipeline completes, write the title record to the data layer.

### Via the admin portal

Fill in the title form. The form fields:

- **Title:** The display name (e.g. "The Movie (2024)")
- **Year:** Release year
- **Language:** ISO 639-1 codes (e.g. "en", "es")
- **Genre:** Free-text tags
- **Runtime (minutes):** Used to validate the AD track length
- **Rated:** Local content rating
- **Actors, writers, narrators:** Optional
- **Where to watch:** Streaming service names
- **Categories:** Which categories this title belongs to
- **Public enabled:** Set to 1 to make it visible to listeners
- **Poster image:** Already uploaded; select from the gallery

Click "Save" to write the record.

### Via the API

```graphql
mutation CreateTitle {
  createTitle(input: {
    titleId: "..."
    title: "The Movie (2024)"
    year: 2024
    language: ["en"]
    genre: ["drama"]
    runtimeMinutes: 120
    rated: "PG-13"
    images: ["posters/poster-{titleId}.jpg"]
    publicEnabled: 1
    fingerprintingProgress: 100
  }) {
    titleId
  }
}

mutation CreateAdTrack {
  createAdTrack(input: {
    trackId: "..."
    titleId: "..."
    language: "en"
    narrator: "..."
    trackUrl: "https://media.example.com/ad-tracks/track-{trackId}.mp3"
    durationSeconds: 7200
  }) {
    trackId
  }
}
```

---

## Step 5: Verify

### In the admin portal

- The title should appear in the titles list
- `fingerprintingProgress` should be 100
- `publicEnabled` should be 1
- The poster image should render
- The AD track should be listed under the title

### In the PWA

- Open the PWA, sign in as a listener
- Browse to the category this title belongs to
- The title should appear in the list
- The poster should load
- Tapping the title should show the AD track(s)

### In the fingerprinting engine

- Use a test recording of the title (record 10 seconds from the reference audio)
- Submit to `/t2s/sync`
- Verify the response includes the titleId and offset
- Verify the confidence is > 0.85

### Final cleanup

- Move files from `pending/` to their final location in the public bucket
- Delete any temporary files
- Log the addition to the audit log (the data layer does this automatically)

---

## What to do if fingerprinting fails

### Symptom: fingerprintingProgress stays at 0

- Check the fingerprinter logs
- Verify the trigger was sent (check the S3 event notifications)
- Manually start the fingerprinter with the input parameters

### Symptom: fingerprintingProgress gets to 50 then fails

- The reference audio is probably corrupted or in an unsupported format
- Re-upload the reference audio as WAV at 44.1 kHz

### Symptom: fingerprinting completes but match returns wrong title

- The reference audio probably doesn't match the AD track
- Verify the reference audio is the correct version (no alternate cuts, no censored versions)

### Symptom: fingerprinting completes but match returns confidence < 0.85

- The reference audio is too short, or the audio is too clean (no real-world variation)
- Try re-recording the reference audio with a small amount of background noise

---

## After adding the title

- Notify your listeners (via the admin portal's notification feature)
- Add the title to relevant categories
- Update any external listings (e.g. "what's new this week")
- Monitor match rates for the first week to catch any issues

---

## Bulk operations

If you're adding many titles at once (e.g. migrating a content library):

1. **Upload all assets in parallel** — S3 supports high-throughput uploads
2. **Batch the fingerprinting triggers** — submit up to 10 in parallel
3. **Use bulk GraphQL mutations** — most GraphQL servers support `createMany` operations
4. **Verify a sample** — don't try to verify all 1,000 titles individually; verify 5-10 random samples

For a bulk import of 1,000 titles, expect:

- Upload: 30 minutes to 2 hours
- Fingerprinting: 1-3 hours (depending on parallelism)
- Database writes: 5-15 minutes
- Total: 2-5 hours
