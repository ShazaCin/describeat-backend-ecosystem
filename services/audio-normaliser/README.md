# DescribeAT audio normaliser

> Automatically formats uploaded audio into the format the DescribeAT backend expects, so operators can upload whatever they have and get the right result.

---

## The problem this solves

DescribeAT ingests two very different kinds of audio, and the backend needs each one in a specific shape.

**Reference audio** — the original film or series soundtrack that the fingerprinting engine hashes — must be lossless and at a known sample rate. The fingerprint is made of spectral peaks, and lossy compression erodes exactly the detail the algorithm depends on. The project documentation is explicit about this: *"Format: WAV or FLAC (lossless; lossy codecs degrade fingerprint quality)"* and *"Sample rate: 44.1 kHz or 48 kHz."*

**AD track audio** — the narration listeners actually hear — is speech, which survives a far more aggressive encode. The documented floor is *"128–192 kbps is fine for narration"*, mono is preferred (*"Mono is smaller and works fine"*), and it should be *"Normalize to −16 LUFS for consistent loudness."*

Today, meeting those requirements is manual work. The admin portal only accepts MP3 for the original audio upload, so the lossless requirement cannot be met at all through the UI, and there is no tooling to produce a correctly-sized AD track.

This service does that work automatically. You upload a WAV, an MP3, a FLAC, an OGG or whatever you have, and it comes out in the shape the backend needs.

---

## The two profiles

| | `fingerprint` | `ad-track` |
|---|---|---|
| **Used for** | Reference audio that the fingerprinting engine hashes | AD narration played to listeners |
| **Output** | Lossless PCM (WAV) | MP3 |
| **Sample rate** | 44.1 kHz | 44.1 kHz |
| **Channels** | Preserved from the source | Mono |
| **Bit rate** | Not applicable (lossless) | 128 kbps |
| **Loudness** | Not altered | Normalised to −16 LUFS, true peak ≤ −1.5 dBTP |
| **Duration** | Preserved exactly | Preserved exactly |

Two deliberate choices worth explaining:

**The fingerprint profile does not touch loudness.** The fingerprinting engine normalises spectral peaks itself, so re-shaping the programme's dynamics beforehand would only degrade the source. Leaving the audio alone is the correct choice.

**The AD track profile applies one static gain.** It measures the programme, then applies a single correction as a static gain. A dynamic normaliser rides the gain to keep the level on target, which pumps audibly on speech — and narration is speech.

**Loudness is measured after the downmix, not before.** This one is easy to get wrong. A stereo source downmixed to mono loses several decibels. If you measure the stereo source and then encode mono, the gain is calculated for the wrong signal and the output lands well below target. So the conversion runs in two stages: the first resamples and downmixes into a lossless intermediate, the second measures *that file* and encodes it. The file on disk is exactly what gets encoded, so there is no filter chain to keep in step.

---

## Using it from the command line

```bash
# What is in this file?
describeat-audio inspect reference.flac --loudness

# What profiles are available?
describeat-audio profiles

# Calibrate reference audio for the fingerprinting engine
describeat-audio normalise reference.flac -p fingerprint

# Compress narration to the minimum size that meets the quality floor
describeat-audio normalise narration.wav -p ad-track -o narration.mp3
```

The output is plain text, so it reads well through a screen reader and pipes cleanly into a log. This is real output from a 30-second 48 kHz stereo WAV:

```
Profile: ad-track
  Audio description narration for listeners: mono MP3 at 128 kbps, 44.1 kHz, normalised to -16 LUFS.

Source: narration.wav
  Format: wav (pcm_s16le)
  Sample rate: 48 kHz
  Channels: stereo
  Duration: 0m 30s
  Size: 5.5 MB

Output: narration.mp3
  Format: mp3 (mp3)
  Sample rate: 44.1 kHz
  Channels: mono
  Duration: 0m 30s
  Size: 469.8 KB
  Loudness before: -25.05 LUFS
  Loudness after: -16.45 LUFS
  Gain applied: +9.05 dB
  Saved: 5.0 MB (92 percent smaller)

Warnings:
  - The source was 48 kHz and was resampled to 44.1 kHz.
  - The source was stereo and was converted to mono.

Verified against the profile.
```

Add `--json` to any command for machine-readable output.

---

## Using it in the upload path

The service can run as an AWS Lambda triggered by an S3 event, so normalisation happens automatically as audio lands in storage.

```bash
sam build
sam deploy --guided
```

`sam build` and `sam deploy --guided` wire the S3 event notification themselves — nothing needs to be added on the bucket by hand.

**Routing** is by key prefix, configured with the `DESCRIBEAT_AUDIO_ROUTES` environment variable:

```json
{
  "audio-tracks-to-process/": "fingerprint",
  "audio-description-tracks-to-process/": "ad-track"
}
```

Objects whose key matches no prefix are left untouched, so the same bucket can hold posters and other files without them being mangled.

**The write-back guard.** The normalised result is written into the same key space the trigger watches, so the finished file arrives as a new event. The service recognises its own output — when an incoming object already meets its profile (codec, sample rate, channels, and measured loudness for the AD track) it is left untouched. A genuinely silent upload is refused with a plain message rather than normalised with an impossible gain.

Setting `DESCRIBEAT_AUDIO_DESTINATION_BUCKET` to a separate bucket is still the recommended setup: it keeps the upload bucket a pure drop-box and avoids the extra event round-trip entirely.

**Environment variables:**

| Variable | Purpose | Default |
|---|---|---|
| `DESCRIBEAT_AUDIO_ROUTES` | JSON mapping of key prefixes to profile names | The two routes above |
| `DESCRIBEAT_AUDIO_DESTINATION_BUCKET` | Where to write normalised files | The source bucket (a separate bucket is recommended) |
| `LOG_LEVEL` | Logging verbosity | `INFO` |

The function needs `s3:GetObject` on the source bucket and `s3:PutObject` on the destination bucket.

### The ffmpeg dependency

The function needs `ffmpeg` and `ffprobe`. The `template.yaml` expects them in a Lambda layer at `layer/`. Two ways to provide it:

1. **Use a published layer.** Replace the `FfmpegLayer` resource with an `AWS::Lambda::LayerVersion` pointing at a published ffmpeg layer, and delete the `layer/` directory.
2. **Build your own.** Put a static `ffmpeg` and `ffprobe` in `layer/bin/` and run `make build`. See the [static ffmpeg builds](https://johnvansickle.com/ffmpeg/) page. Check the binary before you deploy it.

---

## Using it as a library

```python
from describeat_audio import load_profile, normalise

profile = load_profile("ad-track")
report = normalise("narration.wav", "narration.mp3", profile)

print(report.output.integrated_lufs)   # -16.21
print(report.size_saved_ratio)          # 0.94
for warning in report.warnings:
    print(warning)
```

The core package has **no runtime dependencies** — it shells out to ffmpeg, the same binaries the rest of the media toolchain uses. `boto3` is only needed for the S3 path, and it is imported lazily.

---

## Why it verifies the output

After converting, the service re-inspects the result and checks it against the profile: sample rate, channel count, codec, duration, and — for the AD track — measured loudness. If the output does not conform, the conversion **fails loudly** rather than storing a bad file.

This matters more than it might seem. A reference audio file that is subtly wrong does not fail loudly at upload time; it fails *weeks later*, when listeners cannot match the title, and the stored fingerprints are quietly useless. Catching it at the point of upload is far cheaper than diagnosing it from a catalogue of unmatched titles.

Two safety properties follow from the same design:

- **A failed conversion never destroys existing audio.** The result is written to a temporary file alongside the destination and moved into place only after it has been verified. The source and the destination are never touched by the failure path.
- **Converting a file onto itself is safe.** Normalising an MP3 to the AD track profile writes to the same path, which is the common case. The original is read in full before the result replaces it.

---

## Requirements

- Python 3.10 or later
- `ffmpeg` and `ffprobe` on `PATH`

The SoX resampler is used when the local ffmpeg build includes it, because its resampling artefacts are quieter and more broadband-free — and broadband artefacts look like spurious spectral peaks, which matters for the fingerprint profile. The service falls back to ffmpeg's own resampler when SoX is unavailable, and works either way.

---

## Running the tests

```bash
pip install -e ".[dev]"
pytest tests/ -v
```

The tests synthesise their own audio with ffmpeg rather than checking binaries into the repository, and they cover the conversion profiles, the command construction, the object-storage integration and the failure paths. Tests that need ffmpeg skip themselves when it is not installed.

---

## Licence

AGPLv3, the same licence as the rest of the [DescribeAT backend and ecosystem documentation](https://github.com/ShazaCin/describeat-backend-ecosystem). See [`LICENSE`](../../LICENSE).
