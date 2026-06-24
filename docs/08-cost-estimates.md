# 08 — Cost Estimates

> What to budget for a small self-hosted deployment.

---

## The cost model

DescribeAT's backend costs are dominated by:

1. **Compute** for the fingerprinting engine (the always-on matcher is the biggest line item)
2. **Storage** for AD track audio, poster images, and the hash database
3. **Egress** for serving audio to listeners through the CDN
4. **Data layer** for the GraphQL API and database
5. **Notifications** for FCM/APNs (FCM is free up to a point; APNs is free)

The fingerprinting engine is the most variable cost. As your catalogue grows, the hash database grows, and the matcher's memory requirement grows with it. At some point (around 50,000 AD tracks), you need to scale the matcher horizontally.

---

## Small deployment: 100-1,000 listeners, 100-1,000 AD tracks

This is a single-region deployment, suitable for a small organisation, school, or research project.

| Resource | Spec | Monthly cost (USD) |
|----------|------|--------------------|
| Matcher (always-on, 0.5 vCPU, 1 GB) | Fargate task, 24/7 | $15 |
| Fingerprinter (on-demand, 4 vCPU, 8 GB) | Fargate task, ~1 hour/day | $10 |
| Data layer (managed GraphQL + DB) | AppSync + DynamoDB on-demand | $20 |
| Auth provider (Cognito) | 1,000 MAU free tier | $0 |
| Public bucket (S3) | 50 GB storage, 100 GB egress | $10 |
| Private bucket (S3) | 500 GB storage, no egress | $12 |
| CDN (CloudFront) | 500 GB egress | $40 |
| Notifications (FCM) | Free tier | $0 |
| Monitoring (CloudWatch) | Logs + metrics, 7-day retention | $5 |
| DNS + TLS | Route53 + ACM | $1 |
| **Total** | | **~$113/month** |

**Scaling to 10,000 listeners and 10,000 AD tracks:** roughly $300-500/month, dominated by CDN egress and matcher compute.

---

## Medium deployment: 1,000-10,000 listeners, 1,000-10,000 AD tracks

Add horizontal scaling, read replicas, and more storage.

| Resource | Change from small | New monthly cost (USD) |
|----------|-------------------|------------------------|
| Matcher (3 instances) | 3x compute | $45 |
| Fingerprinter | Same | $10 |
| Data layer (with read replicas) | Multi-AZ | $60 |
| Auth provider | Above free tier | $25 |
| Public bucket (S3) | 500 GB storage, 1 TB egress | $100 |
| Private bucket (S3) | 5 TB storage, no egress | $115 |
| CDN (CloudFront) | 5 TB egress | $400 |
| Notifications | Same | $0 |
| Monitoring | 30-day retention | $15 |
| DNS + TLS | Same | $1 |
| **Total** | | **~$771/month** |

---

## Large deployment: 10,000-100,000 listeners, 10,000+ AD tracks

Add multi-region, more aggressive scaling, and dedicated infrastructure.

This is beyond the scope of this guide. The cost model becomes:

- Matcher: 10+ instances, ~$500-1000/month
- Data layer: multi-region with read replicas, ~$500-2000/month
- Storage: tens of TB, ~$1000-3000/month
- CDN: tens of TB egress, ~$2000-5000/month
- Total: **$5,000-15,000/month**

At this scale, you should consider whether a managed service (or a commercial partner) would be cheaper than self-hosting.

---

## What dominates the cost

For most deployments, **CDN egress is the largest cost**. AD track audio is large (5-50 MB per track), and listeners stream it.

**Ways to reduce CDN cost:**
- Cache aggressively (the default is 30 days)
- Use a more efficient codec (Opus or HE-AAC instead of MP3)
- Allow listeners to download tracks for offline use (one egress, many plays)
- Use a cheaper CDN for non-critical content (posters can go on a cheaper CDN than audio)

**What you should NOT do to save money:**
- Skip the always-on matcher (you'll have cold-start latency on every sync request)
- Use a smaller fingerprinting library (match rate will drop)
- Cache audio at the edge for longer than 30 days (audio content can change, and the cache hit rate plateaus around 30 days)
- Skip backups (the cost of a backup is much less than the cost of a data loss)

---

## Cost optimisation opportunities

### 1. Pre-fingerprint in batch

If you have 1,000 AD tracks to ingest, batch them. Run the fingerprinter for 4 hours straight instead of starting it 1,000 times. The cold-start penalty is paid once, not 1,000 times.

**Savings:** ~$5-10 per 1,000 tracks.

### 2. Use spot instances for the fingerprinter

The fingerprinter is interruptible (if it gets killed mid-fingerprint, just restart it). Spot instances are 70-90% cheaper than on-demand.

**Caveat:** Spot instances can be reclaimed at any time. Make sure your fingerprinter can resume from a checkpoint.

**Savings:** ~$5-15/month for the small deployment.

### 3. Right-size the matcher

If your hash database is small (1,000 AD tracks = ~50 MB of hashes), you don't need 1 GB of RAM. You don't need 0.5 vCPU either. Right-size based on actual load.

**How to measure:** Use the matcher's p99 latency. If it's <500ms, you have headroom. If it's >2s, you need to scale up.

### 4. Compress audio

Opus at 64 kbps sounds equivalent to MP3 at 128 kbps for speech (which is what AD tracks are). Halving the bitrate halves the storage and egress costs.

**Trade-off:** Some browsers and devices may not support Opus. Provide MP3 as a fallback.

**Savings:** ~$20-50/month for the medium deployment.

### 5. Use a cheaper CDN for posters

Posters are static and small. Cloudflare's free tier covers most small deployments. Use it for posters, use CloudFront for audio (which needs range requests).

**Savings:** ~$5-10/month.

---

## Cost monitoring

Track these metrics weekly:

- **Cost per listener.** Total monthly cost / active listeners. Should decrease as you scale (up to a point).
- **Cost per AD track.** Total monthly cost / total AD tracks. Should be roughly constant.
- **Cost per sync request.** Total monthly cost / total sync requests. The matcher cost dominates this.
- **Egress per listener.** How much data each listener downloads. Should match expected usage.

**Set a budget alert.** Cloud providers have budget alerts that notify you when you're approaching a budget limit. Set one at 80% of expected spend.

---

## What to budget for ongoing operations

Beyond the compute and storage costs, budget for:

- **Engineering time** for bug fixes and feature additions. 0.5 FTE minimum.
- **Content operations** for adding new AD tracks. 1-2 FTE if you're producing AD content in-house.
- **User support** for listener issues. 0.5 FTE.
- **Security audits** annually. $5,000-20,000 for an external audit.
- **Legal review** for licensing and compliance. $2,000-10,000 annually.

These are the human costs. The infrastructure costs are the smaller line item.

---

## Next

- [`09-orphaned-resources.md`](09-orphaned-resources.md) — keeping your account tidy
- [`10-adrs.md`](10-adrs.md) — why we made the choices we did
