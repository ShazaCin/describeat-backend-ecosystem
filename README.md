# DescribeAT Backend & Ecosystem

> **Companion documentation to [DescribeAT App](https://github.com/ShazaCin/describeat-app-public) — the listener-facing PWA.**
> This repository documents the **backend infrastructure, data model, deployment patterns, and operational knowledge** that the DescribeAT app depends on.

---

## What is DescribeAT?

DescribeAT is an audio description (AD) sync app for blind and visually impaired users. When a user is watching a movie or TV show on a separate device (TV, laptop, cinema), they tap "sync" in the DescribeAT app, it records a few seconds of ambient audio, and the backend figures out **what they're watching** and **at what offset** to start the AD audio track at.

The app itself is in the [`describeat-app`](https://github.com/ShazaCin/describeat-app-public) repository. **This** repository is the documentation of everything that runs behind it: the audio fingerprinting engine, the data model, the storage, the auth, the deployment.

---

## What's in this repository?

```
describeat-backend-ecosystem/
├── README.md                       ← you are here — start here
├── LICENSE                         ← AGPLv3 (code-adjacent docs)
├── LICENSE.media                   ← separate terms for AD content
├── CONTRIBUTING.md                 ← how to contribute to these docs
├── CODE_OF_CONDUCT.md
├── GOVERNANCE.md                   ← project governance (tiers, veto, conflict resolution)
├── SECURITY.md                     ← how to report vulnerabilities
├── TRADEMARK.md                    ← DescribeAT and Shazacin trademark usage policy
├── .gitlab-ci.yml                  ← CI pipeline (markdown lint, link check, secret scan, JSON/SVG validation)
├── .gitlab/                        ← GitLab-specific templates
│   ├── issue_templates/            ← bug report, feature request, documentation, question
│   └── merge_request_templates/    ← MR template with DCO checklist
├── .github/                        ← GitHub-compatible templates (for cross-platform use)
│   └── ISSUE_TEMPLATE/             ← bug report, feature request, documentation, question
│
├── docs/                           ← the canonical reference
│   ├── 00-overview.md              ← mental model, request paths, "is this for me?"
│   ├── 01-architecture.md          ← component map, request flows, diagrams
│   ├── 02-auth.md                  ← authentication, OAuth, account model
│   ├── 03-data-model.md            ← the 4 core entities, sample data
│   ├── 04-t2s-sync-engine.md       ← the audio fingerprinting engine
│   ├── 05-storage-cdn.md           ← media files, content distribution
│   ├── 06-notifications.md         ← push notifications to listener devices
│   ├── 07-deploy-your-own.md       ← step-by-step: spin up your own instance
│   ├── 08-cost-estimates.md        ← what to budget for a small self-hosted deployment
│   ├── 09-orphaned-resources.md    ← how to keep your account tidy
│   ├── 10-adrs.md                  ← architecture decision records
│   ├── 11-troubleshooting-faq.md   ← 22 issues + 22 FAQ items (Symptom → Cause → Diagnostic → Fix)
│   ├── delivery-brief-pack.md      ← handover guide for Shazacin (repo ownership + contributor engagement)
│   └── launch-website-page-brief.md ← creative brief for the shazacin.com/describeat landing page
│
├── diagrams/                       ← SVG architecture diagrams
│   ├── 01-overview.svg
│   └── 04-t2s-flow.svg
│
├── data-examples/                  ← anonymised sample data for each entity
│   ├── README.md                   ← what was redacted, how to use these
│   ├── titles.sample.json
│   ├── ad-tracks.sample.json
│   ├── user-notifications.sample.json
│   ├── user-feedback.sample.json
│   └── categories.sample.json
│
├── examples/                       ← example configurations
│   ├── env.example                 ← environment variable template
│   ├── amplify-meta.example.json   ← CloudFormation output shape
│   └── cognito-app-client.example.json
│
└── workflows/                      ← day-2 operations runbooks
    ├── adding-a-new-title.md
    ├── rotating-credentials.md
    └── incident-response.md
```

---

## How to read this repository (zero-knowledge reader)

**If you have 15 minutes:** Read [`docs/00-overview.md`](docs/00-overview.md) and look at [`diagrams/01-overview.svg`](diagrams/01-overview.svg). You'll come away with the mental model.

**If you have an hour:** Read `00` → `01` → `02` → `03` → `04` in order. Skim `07-deploy-your-own.md` to see what a self-hosted deployment looks like.

**If you want to deploy your own instance:** Start at [`docs/07-deploy-your-own.md`](docs/07-deploy-your-own.md) and follow the steps. Come back to the architecture docs when you hit something you need to understand in depth.

**If you're contributing back:** Read [`CONTRIBUTING.md`](CONTRIBUTING.md) first. The DCO sign-off rule is non-negotiable.

---

## ⚠️ Important caveats for self-hosters

These are the things the docs do not (and cannot) tell you — you have to decide for your own deployment.

### 1. The audio content is not free

AD tracks, reference audio, and fingerprint data are **not** covered by the AGPLv3 license. The code license applies to the application code and this documentation only. If you self-host DescribeAT, you are responsible for sourcing the AD content for your region. See [`LICENSE.media`](LICENSE.media).

### 2. The fingerprinting library is closed source

The audio fingerprinting engine (T2S — Time-To-Sync) uses a closed-source commercial library provided by the original Shazacin partners. You will need to license this separately or substitute an open-source alternative (the [Dejavu](https://github.com/worldveil/dejavu) project is the most common substitution, with reduced accuracy on noisy real-world audio). See [`docs/04-t2s-sync-engine.md`](docs/04-t2s-sync-engine.md) §"Choosing your fingerprinting engine" for the trade-offs.

### 3. The deployed reference instance is being decommissioned

The Shazacin team's own AWS backend (the one these docs were originally derived from) is being switched off in 2026 as part of Shazacin's shift to a community-supported model. **Self-hosters should not depend on any of the example AWS resource names, ARNs, account IDs, or endpoint URLs being live.** Everything in this repo is a *pattern* — you must instantiate it under your own AWS (or other cloud) account.

### 4. AGPLv3 means your improvements must be shared

If you deploy a modified DescribeAT backend as a service accessible to the public, the AGPLv3 network copyleft clause requires you to publish your modifications. The point of the open-source release is exactly this: improvements feed back to the community. See [`LICENSE`](LICENSE) §13 for the legal text.

---

## What this repository is NOT

- **Not the application code.** That lives in [describeat-app](https://github.com/ShazaCin/describeat-app-public).
- **Not a deployed service.** You cannot "use" this repository — you read it, follow the patterns, and deploy your own.
- **Not the AD content library.** AD tracks are Shakila/Sibonga's curated catalogue, licensed separately, and not redistributed from this repo.
- **Not a promise of feature parity.** The original Shazacin instance had proprietary integrations (FCM, custom fingerprinting, paid content licensing) that are documented for context but may not be reproducible by self-hosters.

---

## Contributing

We welcome:

- **Documentation fixes** — typos, broken links, unclear diagrams, missing context
- **Architecture corrections** — if you deployed DescribeAT and found something the docs got wrong, tell us
- **Alternative deployment recipes** — Kubernetes manifests, Terraform modules, self-hosted non-AWS setups
- **Translations** — Spanish, French, Arabic, and any major language improve accessibility of the docs

See [`CONTRIBUTING.md`](CONTRIBUTING.md) for the workflow and the DCO sign-off.

For security issues, do **not** open a public issue. See [`SECURITY.md`](SECURITY.md).

---

## Provenance

This documentation pack was originally produced by the BGC consulting team (Cersei) as part of the 2026 DescribeAT open-source preparation. The original pack was a code-first audit of Shazacin's production AWS backend — every documented resource was traced back to either a code reference or a deployed CloudFormation output. This public release has been redacted to remove all Shazacin-specific identifiers, account IDs, production endpoints, and personal information. The architecture and patterns are unchanged.

The full SME review history (internal) and the original BGC charter are kept in the BGC OracleGraph vault for accountability.

---

## License

- Code-adjacent documentation (this README, the `docs/`, the `examples/`, the `workflows/`): **AGPLv3** — see [`LICENSE`](LICENSE).
- Sample data files in `data-examples/`: **CC-BY-4.0** — use them, attribute this repo.
- AD content, audio tracks, fingerprint data: **separate terms** — see [`LICENSE.media`](LICENSE.media). Not redistributed.

---

*This documentation pack is for educational and operational reference. Deploy it under your own conditions. The Shazacin team is not responsible for the operation, security, or content of third-party deployments.*
