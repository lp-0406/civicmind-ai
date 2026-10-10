# `configs/`

Runtime configuration for CivicMind AI.

## What belongs here

* Dataset manifests: reviewed `SourceDescriptor` metadata for approved sources
  (id, publisher, licence, URI, cadence) — **planned**.
* Pipeline configuration: preprocessing and profiling parameters — **planned**.
* Environment overlays for CI or scheduled jobs — **planned**.

Nothing is loaded from this directory yet; the current release is configured
exclusively through environment variables (see `.env.example` and
`civicmind.config.Settings`).

## Rules

* **No secrets.** Credentials live in the process environment or a git-ignored
  `.env` file, never in committed configuration.
* **No fabricated dataset metadata.** Values recorded here must be verifiable
  against the publisher's own documentation.
* **Reviewed changes only.** Manifest changes alter provenance; treat them like
  code changes (review, tests, changelog note).
