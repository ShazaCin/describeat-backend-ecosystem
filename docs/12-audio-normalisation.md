# 12 — Audio normalisation service

> A reference service that converts uploaded audio into the format the backend expects, so operators can upload whatever they have and get the right result.

---

## Why this exists

DescribeAT ingests two very different kinds of audio, and the backend needs each one in a specific shape.

**Reference audio** — the original film or series soundtrack that the fingerprinting engine hashes — must be lossless and at a known sample rate. The fingerprint is made of spectral peaks, and lossy compression erodes exactly the detail the algorithm depends on. The guidance in [`workflows/adding-a-new-title.md`](../workflows/adding-a-new-title.md) is explicit: *"Format: WAV or FLAC (lossless; lossy codecs degrade fingerprint quality)"* and *"Sample rate: 44.1 kHz or 48 kHz."*

**AD track audio** — the narration listeners actually hear — is speech, which survives a far more aggressive encode. The documented floor is *"128–192 kbps is fine for narration"*, mono is preferred (*"Mono is smaller and works fine"*), and it should be *"Normalize to −16 LUFS for consistent loudness."*

Meeting those requirements is otherwise manual work: an operator has to know the target format, find an encoder, set the right parameters and check the result. The service does it automatically.

It lives in [`services/audio-normaliser`](../services/audio-normaliser) in this repository.

---

## The two profiles

| | `fingerprint` | `ad-track` |
|---|---|---|
| **Used for** | Reference audio the fingerprinting engine hashes | AD narration played to listeners |
| **Output** | Lossless PCM (WAV) | MP3 |
| **Sample rate** | 44.1 kHz | 44.1 kHz |
| **Channels** | Preserved from the source | Mono |
| **Bit rate** | Not applicable (lossless) | 128 kbps |
| **Loudness** | Not altered | Normalised to −16 LUFS, true peak ≤ −1.5 dBTP |
| **Duration** | Preserved exactly | Preserved exactly |

---

## Three decisions worth understanding

### Loudness is measured after the downmix, not before

This is the subtle one, and it is easy to get wrong.

A stereo source downmixed to mono loses several decibels. If you measure the stereo source and then encode mono, the gain is calculated for the wrong signal and the output lands well below target — several decibels low, which is plainly audible as quiet narration.

So the conversion runs in two stages:

1. **Prepare.** Resample to the target rate and set the target channel count into a lossless intermediate.
2. **Encode.** Measure *that intermediate file*, apply the loudness correction, and encode for delivery.

The intermediate on disk is exactly what gets encoded, so there is no filter chain to keep in step. This removes a whole class of bug rather than papering over it.

### The correction is a static gain, not a dynamic normaliser

`loudnorm` in single-pass mode is a dynamic process: it rides the gain to keep the output on target, which pumps audibly on speech and flattens the dynamics of narration.

The service measures the programme, then applies one fixed correction. The programme's dynamics are left exactly as they were, which is what a listener expects from narration.

The true-peak ceiling is enforced separately with a limiter, so the correction can never push a transient into clipping.

### The fingerprint profile leaves loudness alone

The fingerprinting engine normalises spectral peaks itself, so pre-normalised input is not needed, and re-shaping the programme's dynamics before hashing only degrades the source. Leaving the audio alone is the correct choice, and the service says so in its report so the absence reads as a decision rather than an oversight.

---

## The verification step

After converting, the service re-inspects the result and checks it against the profile: sample rate, channel count, codec, duration and — for the AD track — measured loudness. If the output does not conform, the conversion **fails loudly** rather than storing a bad file.

This matters more than it might seem. A reference audio file that is subtly wrong does not fail loudly at upload time; it fails *weeks later*, when listeners cannot match the title, and the stored fingerprints are quietly useless. Catching it at the point of upload is far cheaper than diagnosing it from a catalogue of unmatched titles.

Two safety properties follow from the same design:

- **A failed conversion never destroys existing audio.** The result is written to a temporary file alongside the destination and moved into place only after it has been verified. The source and the destination are never touched by the failure path.
- **Converting a file onto itself is safe.** Normalising an MP3 to the AD track profile writes to the same path, which is the common case. The original is read in full before the result replaces it.

---

## Using it

### From the command line

```bash
# What is in this file?
describeat-audio inspect reference.flac --loudness

# Calibrate reference audio for the fingerprinting engine
describeat-audio normalise reference.flac -p fingerprint

# Compress narration to the minimum size that meets the quality floor
describeat-audio normalise narration.wav -p ad-track -o narration.mp3
```

The output is plain text so it reads well through a screen reader and pipes cleanly into a log. Add `--json` for machine-readable output.

### From the upload path

The service runs as an AWS Lambda triggered by an S3 event, so normalisation happens automatically as audio lands in storage. See the [service README](../services/audio-normaliser/README.md) for the deployment walkthrough.

Routing is by key prefix:

```json
{
  "audio-tracks-to-process/": "fingerprint",
  "audio-description-tracks-to-process/": "ad-track"
}
```

Objects whose key matches no prefix are left untouched, so the same bucket can hold posters and other files without them being mangled.

---

## Requirements

- Python 3.10 or later
- `ffmpeg` and `ffprobe` on `PATH`

The core has no runtime dependencies beyond the standard library. It shells out to ffmpeg, the same binaries the rest of the media toolchain uses.

The SoX resampler is used when the local ffmpeg build includes it, because its resampling artefacts are quieter and more broadband-free — and broadband artefacts look like spurious spectral peaks, which matters for the fingerprint profile. The service falls back to ffmpeg's own resampler when SoX is unavailable, and works either way.

---

## Self-hosting notes

- **The fingerprint profile produces larger files than it consumes.** Lossless PCM is bigger than the compressed source it replaced. The docs already put reference audio at *"50–500 MB per title"*, so budget for that.
- **The service needs ffmpeg in the Lambda layer.** The deployment template expects it at `layer/`; the README explains how to supply it either way.
- **The AD track profile is the one to automate.** It is the profile an operator hits repeatedly, and the one where a wrong file is easiest to miss by ear.

---

## Next

- [`04-t2s-sync-engine.md`](04-t2s-sync-engine.md) — how the reference audio is used once it has been normalised
- [`05-storage-cdn.md`](05-storage-cdn.md) — where the normalised files live
- [`workflows/adding-a-new-title.md`](../workflows/adding-a-new-title.md) — the operational runbook this service supports
