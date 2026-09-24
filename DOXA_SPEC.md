# DOXA — Instagram carousel publisher for @the_silver_fox_men

> Build spec for Claude Code. Read fully before writing code. Ask before deviating.

## 0. Goal & principles (the "Doxa SUB 300" standard)

A small, boring, bulletproof system that publishes one Hebrew Instagram carousel per day
from a git-based queue, running on **GitHub Actions** (no server).

1. **Legibility** – anyone can see at a glance what is queued, approved, published, failed.
2. **Built-in safety** – nothing is published unless explicitly approved; dry-run mode; rate-limit checks; idempotent (a post is never published twice).
3. **Reliability** – runs unattended, retries transient errors, refreshes its own token, and raises an alert (GitHub Issue) on any failure.

Account: `@the_silver_fox_men` (Instagram **Creator** account, not linked to any Facebook Page).
Repo: `silverfox-il/doxa` — **public** (Instagram must fetch images from a public URL).
Never commit secrets. Never put personal names/emails/phones in the repo.

## 1. Instagram API (verify against current Meta docs before coding)

Use **Instagram API with Instagram Login** (host `graph.instagram.com`), NOT the Facebook-Page-based Graph API.
Check the current API version and endpoint shapes in Meta's docs at build time — do not trust memory.

Carousel publish flow (expected):
1. For each slide: `POST /{IG_USER_ID}/media` with `image_url=<public JPEG URL>`, `is_carousel_item=true` → child container id.
2. `POST /{IG_USER_ID}/media` with `media_type=CAROUSEL`, `children=<id1,id2,...>`, `caption=<text>` → carousel container id.
3. Poll `GET /{container_id}?fields=status_code` until `FINISHED` (timeout ~5 min; fail on `ERROR`/`EXPIRED`).
4. `POST /{IG_USER_ID}/media_publish` with `creation_id=<carousel container id>` → media id.
5. `GET /{media_id}?fields=permalink,timestamp` → store.

Also: before publishing call `GET /{IG_USER_ID}/content_publishing_limit` and abort with a clear error if quota is exhausted.
Constraints: JPEG only, 2–10 items per carousel, 4:5 (1080×1350) for all slides, caption ≤ 2,200 chars, ≤ 30 hashtags.

Required permissions/scopes (confirm in docs): `instagram_business_basic`, `instagram_business_content_publish`
(phase 2 adds `instagram_business_manage_comments`, `instagram_business_manage_messages`).

Token: long-lived user token (~60 days). Refresh weekly via
`GET https://graph.instagram.com/refresh_access_token?grant_type=ig_refresh_token&access_token=...`
and write the new value back to the repo secret with `gh secret set IG_ACCESS_TOKEN` (uses `GH_PAT`).

### Secrets (set by the owner in GitHub → Settings → Secrets → Actions; code must only read them)
- `IG_ACCESS_TOKEN` – long-lived Instagram token
- `IG_USER_ID` – Instagram professional account id
- `GH_PAT` – fine-grained PAT for this repo only, permissions: Secrets (RW), Contents (RW), Issues (RW)

## 2. Repo layout

```
doxa/
  queue/
    2026-09-25-manifesto/
      post.yaml
      slides/            # final JPEGs 1.jpg..N.jpg (rendered or prebuilt)
  templates/             # HTML/CSS slide templates (RTL Hebrew)
  assets/
    fonts/               # Heebo (OFL) woff2, committed
    backgrounds/         # licensed/AI-generated background photos (JPEG)
  doxa/                  # python package
    cli.py  render.py  publish.py  queue.py  instagram.py  alerts.py  token.py
  tests/
  .github/workflows/
    render.yml  publish.yml  refresh-token.yml  ci.yml
  STATUS.md              # auto-generated dashboard
  README.md              # Hebrew + English operator guide
```

### post.yaml schema
```yaml
id: 2026-09-25-manifesto
publish_at: "2026-09-25 07:00"        # Asia/Jerusalem local time
approved: false                       # owner flips to true → eligible to publish
mode: render                          # render | prebuilt
caption: |
  ...Hebrew caption...
slides:                               # only for mode: render
  - background: assets/backgrounds/street-walk.jpg
    kicker: ""                        # small line above
    title: "בגיל חמישים\nאתה לא גמור"
    accent: "אתה בשיא"                # silver-gradient line
    body: "רק שכחו להגיד לך"
    layout: bottom                    # bottom | top | list
    items: []                         # for layout: list
# written by the system — never edit by hand:
status: queued                        # queued | rendered | publishing | published | failed
ig_media_id: null
permalink: null
published_at: null
error: null
```

## 3. Renderer (`doxa render`)

- Playwright + Chromium, HTML templates with `<html dir="rtl" lang="he">`, Heebo font from `assets/fonts` (no network fonts).
- Output 1080×1350 JPEG (quality ~90, sRGB) → `slides/1.jpg…`.
- Background photo `object-fit: cover` + bottom dark gradient (transparent → rgba(0,0,0,.8)) for legibility; text right-aligned.
- Brand frame on every slide: "סילבר פוקס" top-right, `n/N` counter top-left, thin silver rule. Last slide shows `@the_silver_fox_men`.
- Correct RTL bidi: punctuation and numbers must render on the correct side (test with "בגיל 50." and "25:" — add a visual regression test that renders fixtures and compares against golden PNGs with a tolerance).
- `mode: prebuilt` skips rendering and only validates existing JPEGs (count 2–10, 1080×1350, JPEG).
- After rendering, set `status: rendered` and regenerate `STATUS.md`.

## 4. Approval flow (safety bezel)

- `render.yml` (on push to `queue/**`): render changed posts, commit JPEGs, then open/update a GitHub **Issue** titled `Approve: <id>` containing all slide images (raw URLs), the caption and `publish_at`. GitHub emails the owner automatically.
- Owner approves by setting `approved: true` in `post.yaml` (or adding label `approved` to the issue — implement both; label sync writes `approved: true` back).
- Nothing with `approved: false` is ever published.

## 5. Publisher (`doxa publish`)

- `publish.yml`: cron **hourly** (`0 * * * *`) + `workflow_dispatch` (with `dry_run` input and optional `post_id`).
- Picks posts where `approved: true`, `status in (rendered, failed-retryable)`, and `publish_at <= now (Asia/Jerusalem)`. At most **1** publish per run.
- Image URLs = `https://raw.githubusercontent.com/<owner>/<repo>/<commit-sha>/queue/<id>/slides/<n>.jpg` (pin to the commit SHA; HEAD-check each URL returns 200 + `image/jpeg` before calling Meta).
- Sets `status: publishing` and commits **before** calling `media_publish` (idempotency: if a run crashes mid-way, next run checks for an existing recent post with the same caption hash before retrying).
- Retries with exponential backoff on 5xx / rate-limit codes (max 3). Non-retryable → `status: failed`, `error: ...`.
- On success: store `ig_media_id`, `permalink`, `published_at`; close the approval issue with the permalink; regenerate `STATUS.md`.
- `concurrency: doxa-publish` so two runs never overlap.
- `DRY_RUN=1` does everything except the two POST calls to Meta and logs what it would send.

## 6. Token refresh & alerts

- `refresh-token.yml`: weekly cron + manual. Refresh token, update secret via `gh secret set`, log expiry date (never log the token).
- `alerts.py`: any failed workflow step opens (or comments on) a GitHub Issue `🚨 DOXA failure` with the step, error and run link. Also warn 10 days before token expiry.

## 7. STATUS.md dashboard

Auto-generated table, newest first: date · id · approved · status · permalink · error. Plus: next scheduled post, token expiry, today's publishing quota.

## 8. Quality bar

- Python 3.12, `uv` or `pip` with pinned deps, type hints, `ruff` + `pytest` in `ci.yml`.
- Unit tests for queue selection, time-zone handling (Asia/Jerusalem incl. DST), idempotency, API client (mock HTTP).
- `doxa validate` checks every post.yaml against the schema.
- README (Hebrew first) with: how to add a post, approve it, run a dry run, read STATUS.md, rotate the token.

## 9. Milestones

1. Skeleton repo + CLI + schema + `validate` + CI.
2. Renderer + golden tests (Hebrew bidi).
3. Approval issues.
4. Publisher with dry-run → owner runs one real publish of `2026-09-25-manifesto` (prebuilt, 5 slides from Canva).
5. Token refresh + alerts + STATUS.md.
6. (Phase 2) Comment keyword → private reply (poll comments hourly; reply once per commenter per keyword; keywords & messages in `config/keywords.yaml`).

## 10. First queue item (bootstrap)

`queue/2026-09-25-manifesto/` — `mode: prebuilt`. Slides: export all 5 pages of the Canva design
"סילבר פוקס — קרוסלת אינסטגרם" as JPG 1080×1350 and save as `slides/1.jpg … 5.jpg`.
Caption:
```
בגיל 50 אתה לא גמור. אתה בשיא. 🦊
העמוד הזה הוא לגבר שחוזר למשחק אחרי 20 שנה: גוף, ביטחון, ודייטינג שעובד היום.
כל בוקר פוסט אחד. תעקוב, ותגיב "בפנים" אם אתה מתחיל היום.
```

