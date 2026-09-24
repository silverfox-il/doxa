# DOXA

<div dir="rtl">

מפרסם קרוסלות אינסטגרם בעברית עבור ‎@the_silver_fox_men. תור מבוסס git, רץ על GitHub Actions, בלי שרת.
המפרט המלא: [`DOXA_SPEC.md`](DOXA_SPEC.md).

> **מצב נוכחי:** אבני דרך 1–3 מוכנות: תור, סכימה, `validate`, רינדור שקופיות, ו־Issue לאישור.
> פרסום לאינסטגרם (אבן דרך 4) ורענון טוקן והתראות (אבן דרך 5) עוד לא קיימים. שום דבר לא עולה לאינסטגרם בינתיים.

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
אם משנים פוסט אחרי שאושר, השקופיות מתרנדרות מחדש וה־Issue מתעדכן, אבל האישור נשאר. חשוב לבדוק שוב.

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

## בקרוב

- **הרצה יבשה (dry run):** תגיע באבן דרך 4. ‏`publish.yml` יורץ עם `dry_run`.
- **החלפת טוקן:** תגיע באבן דרך 5. ‏`refresh-token.yml` ירוץ פעם בשבוע.

</div>

---

## English

Hebrew Instagram carousel publisher for @the_silver_fox_men: a git-based queue running on GitHub
Actions. Full spec: [`DOXA_SPEC.md`](DOXA_SPEC.md).

**Status:** milestones 1–3 are done (queue schema + `doxa validate`, Hebrew RTL renderer, approval
issues). Publishing (M4) and token refresh/alerts (M5) are not built yet, so nothing reaches Instagram.

### Workflow

| Step | Who | What happens |
|------|-----|--------------|
| Add `queue/<id>/post.yaml` and push | owner | `render.yml` validates, renders `slides/*.jpg` (or checks prebuilt JPEGs), commits them and updates `STATUS.md` |
| Review | GitHub | `render.yml` opens/refreshes the issue `Approve: <id>` with slides pinned to the commit SHA, the caption and `publish_at` |
| Approve | owner | add the `approved` label (`approve.yml` writes `approved: true`) **or** set `approved: true` in `post.yaml` |
| Publish | — | milestone 4 |

### CLI

```
doxa validate                 # every post.yaml + slide JPEGs; exit 1 on any problem
doxa render [ID...]           # render / validate posts (never touches publishing/published/failed)
doxa changed BASE HEAD        # post ids touched between two commits
doxa status                   # regenerate STATUS.md
doxa open-issues --sha SHA [ID...]            # open/refresh approval issues (needs gh + GH_TOKEN)
doxa approve-sync [ID...] [--from-issue-title T]  # copy the `approved` label into post.yaml
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
