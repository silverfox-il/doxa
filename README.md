# DOXA

<div dir="rtl">

מפרסם קרוסלות אינסטגרם בעברית עבור ‎@the_silver_fox_men. תור מבוסס git, רץ על GitHub Actions, בלי שרת.
המפרט המלא: [`DOXA_SPEC.md`](DOXA_SPEC.md).

> **מצב נוכחי:** אבני דרך 1–4 מוכנות: תור, רינדור, Issue לאישור, ומפרסם.
> הפרסום האוטומטי כבוי עד שמדליקים את המתג `DOXA_LIVE` (פירוט למטה). רענון טוקן והתראות (אבן דרך 5) עוד לא קיימים.

## איך מוסיפים פוסט

1. יוצרים תיקייה `queue/<תאריך>-<שם>/`, למשל `queue/2026-09-26-body/`.
2. בתוכה יוצרים `post.yaml`:

</div>

```yaml
id: 2026-09-26-body                  # חייב להיות זהה לשם התיקייה
publish_at: "2026-09-26 07:00"       # שעון ישראל
approved: false                      # אל תשנה כאן — מאשרים ב־Issue
mode: render                         # render = המערכת מעצבת | prebuilt = JPEG מוכנים
caption: |
  טקסט הפוסט...
slides:                              # 2–10 שקופיות, רק ב־mode: render
  - background: assets/backgrounds/street-walk.jpg
    kicker: ""
    title: "בגיל חמישים\nאתה לא גמור"
    accent: "אתה בשיא"
    body: "רק שכחו להגיד לך"
    layout: bottom                   # bottom | top | list
  - background: assets/backgrounds/gym.jpg
    title: "3 דברים"
    layout: list
    items: ["גוף", "ביטחון", "דייטינג"]
```

<div dir="rtl">

3. ב־`mode: prebuilt` לא כותבים `slides:`. במקום זה שמים בתיקייה `slides/1.jpg … N.jpg`: בין 2 ל־10 קבצי JPEG בגודל 1080×1350.
4. עושים push ל־`main`. ה־workflow ‏`render` מרנדר את השקופיות (או בודק את ה־JPEG המוכנים), שומר אותן ב־commit, ופותח Issue בשם `Approve: <id>`. GitHub שולח לך מייל.

## איך מאשרים

ב־Issue רואים את כל השקופיות, את הכיתוב ואת שעת הפרסום. כדי לאשר, בוחרים אחת מהדרכים:

- מוסיפים ל־Issue את התווית `approved`. ה־workflow ‏`approve` כותב `approved: true` לתוך `post.yaml`.
- או משנים ידנית ל־`approved: true` ב־`post.yaml` ועושים push.

פוסט עם `approved: false` לא יתפרסם אף פעם. אם הסרת את התווית, זה **לא** מבטל את האישור. כדי לבטל, משנים ל־`approved: false` ב־`post.yaml`.
האישור קשור לתוכן. ברגע האישור המערכת שומרת טביעת אצבע (`approved_hash`) של הכיתוב, השקופיות, שעת הפרסום וקובצי ה־JPEG.
אם משנים משהו אחרי האישור, הרינדור הבא מבטל את האישור, מסיר את התווית `approved` ומוסיף תגובה ב־Issue. כדי לאשר שוב, בודקים את הגרסה החדשה ומוסיפים את התווית מחדש.
פוסט שהתוכן שלו השתנה מאז האישור לא יתפרסם.

## STATUS.md

[`STATUS.md`](STATUS.md) נוצר אוטומטית בכל רינדור ובכל אישור. יש בו טבלה של כל הפוסטים, מהחדש לישן: תאריך, id, אושר, סטטוס, קישור ושגיאה. בראש הקובץ מופיע הפוסט הבא בתור.
הסטטוסים: `queued` ← `rendered` ← `publishing` ← `published`, או `failed`.

## הרצה מקומית

</div>

```bash
python -m venv .venv && .venv/Scripts/activate      # macOS/Linux: source .venv/bin/activate
pip install -e ".[dev]"
python -m playwright install chromium
doxa validate                  # בדיקת כל ה־post.yaml
doxa render 2026-09-26-body    # רינדור מקומי (ה־JPEG נוצרים ב־queue/<id>/slides/)
pytest -q && ruff check .
```

<div dir="rtl">

## פרסום

`publish.yml` רץ כל שעה עגולה. בכל ריצה הוא מפרסם לכל היותר פוסט אחד: הפוסט הוותיק ביותר שאושר, שהתוכן שלו לא השתנה מאז האישור, ושהגיעה שעת הפרסום שלו.

**מתג בטיחות:** ריצות ה־cron מפרסמות באמת רק אם משתנה ה־repo ‏`DOXA_LIVE` שווה `true`.
המשתנה נמצא ב־Settings ← Secrets and variables ← Actions ← Variables. עד שמגדירים אותו, כל ריצה אוטומטית היא הרצה יבשה.

**הרצה יבשה (dry run):** נכנסים ל־Actions ← publish ← Run workflow. משאירים את `dry_run` מסומן, ואם רוצים ממלאים `post_id`.
ההרצה בודקת את כל מה שאפשר: אישור, שעה, קובצי JPEG, שכל כתובת תמונה מחזירה 200, ומכסת פרסום. היא מדפיסה מה הייתה שולחת לאינסטגרם, אבל לא שולחת כלום ולא משנה שום קובץ.
**פרסום ידני:** אותו מסך, עם `dry_run` לא מסומן.

**בדיקת טוקן:** Actions ← healthcheck ← Run workflow. הבדיקה מדפיסה רק את שם המשתמש, את ה־user_id ואת המכסה, ונכשלת אם החשבון הוא לא ‎@the_silver_fox_men.

## בקרוב

- **החלפת טוקן:** תגיע באבן דרך 5. ‏`refresh-token.yml` ירוץ פעם בשבוע.

</div>

---

## English

Hebrew Instagram carousel publisher for @the_silver_fox_men: a git-based queue running on GitHub
Actions. Full spec: [`DOXA_SPEC.md`](DOXA_SPEC.md).

**Status:** milestones 1–4 are done (queue + `doxa validate`, Hebrew RTL renderer, approval
issues, publisher). Scheduled publishing stays in dry-run mode until the repo variable
`DOXA_LIVE` is `true`. Token refresh and alerts (M5) are not built yet.

### Workflow

| Step | Who | What happens |
|------|-----|--------------|
| Add `queue/<id>/post.yaml` and push | owner | `render.yml` validates, renders `slides/*.jpg` (or checks prebuilt JPEGs), commits them and updates `STATUS.md` |
| Review | GitHub | `render.yml` opens/refreshes the issue `Approve: <id>` with slides pinned to the commit SHA, the caption and `publish_at` |
| Approve | owner | add the `approved` label (`approve.yml` writes `approved: true`) **or** set `approved: true` in `post.yaml` |
| Edit after approval | owner | the next render sees a changed content hash (`approved_hash`), resets `approved`, removes the label and comments on the issue |
| Publish | `publish.yml` (hourly) | at most one approved, due post whose `approved_hash` still matches; live only when `DOXA_LIVE=true` or when started manually with `dry_run` unticked |

### CLI

```
doxa validate                 # every post.yaml + slide JPEGs; exit 1 on any problem
doxa render [ID...]           # render / validate posts (never touches publishing/published/failed)
doxa changed BASE HEAD        # post ids touched between two commits
doxa status                   # regenerate STATUS.md
doxa open-issues --sha SHA [ID...]            # open/refresh approval issues (needs gh + GH_TOKEN)
doxa approve-sync [ID...] [--from-issue-title T]  # copy the `approved` label into post.yaml
doxa publish [--live] [--post-id ID] [--sha SHA]   # dry run unless --live (needs IG_* env vars)
doxa check [--expect-username U]                   # prints only username, user_id, quota
```

### Tests

- `pytest -q`: schema, Asia/Jerusalem time handling including DST, queue selection, the CLI, the
  approval flow (with a fake `gh`), and the renderer.
- Renderer bidi tests read glyph positions from the rendered DOM ("בגיל 50." → the period sits left
  of the number; "25:" → the colon sits left of the number). They run on every OS.
- Pixel goldens in `tests/golden/*.png` are Linux renders made by CI, so they only run on Linux. To
  accept an intentional visual change, commit an empty `tests/golden/REGENERATE` file. The
  `goldens` workflow re-renders on ubuntu, commits the PNGs and deletes the marker. Review the PNG
  diff before you trust it.

### Publisher safety

- Order: recover any post stuck in `publishing` (if Instagram already has its caption, the post
  is marked published, otherwise `failed-retryable`), check eligibility, validate the JPEGs,
  HEAD-check the commit-pinned raw URLs, check `content_publishing_limit`, create the containers,
  poll until `FINISHED`, **commit `status: publishing`**, then call `media_publish`.
- Container creation and reads are retried 3 times with exponential backoff on 5xx and throttling
  errors. `media_publish` is never retried automatically. If its outcome is unclear, the post stays
  `publishing` and the next run checks Instagram before it tries again.
- The token is sent only in the `Authorization: Bearer` header. It never appears in a URL or a log.
