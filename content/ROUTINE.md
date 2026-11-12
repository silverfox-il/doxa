# Weekly content routine

A scheduled agent runs this every Thursday. It fills the queue for the next 7 days.
Nobody reviews the output before it is queued, so follow every rule below exactly.
The automatic checks (`doxa rules`, `doxa validate`) are a safety net; they do not
replace them.

**Rewritten 2026-11-13 for the owner's writing brief.** The owner rejected the old
routine's output (4 posts a day, teaser series, list carousels) as low quality.
Everything below replaces it.

## Inputs

- This repo, `silverfox-il/doxa` (public).
- The private repo `silverfox-il/doxa-private`, checked out next to this one:
  - `voice/BRIEF.md`: **the owner's writing brief. Read it fully first. It is the
    law for voice, formats, what is forbidden, and the self-check.**
  - `book/*.md`: the book, new edition. **The only source of ideas.** Never invent a
    principle the book does not hold. If a week cannot be filled from fresh book
    material, queue fewer posts and say so.
  - `rules_private.yaml`: identity terms. Read it, never copy it anywhere.
  - `video/`: licensed background clips. `music/`: licensed tracks.
- `content/used.yaml` and `queue/`: never reuse a book section, a line or a clip.

Set up:

```bash
pip install -e ".[dev]"
export DOXA_BOOK_DIR=<path to doxa-private>/book
git config user.name silverfox-il
git config user.email 333442913+silverfox-il@users.noreply.github.com
```

## What to produce (weekly mix from the brief)

1. D1 is the first day from tomorrow on with no post in `queue/`. Never move or
   replace an existing post.
2. Do nothing (report "queue already full") if D1 is more than 10 days from today.
3. For D1 through D7 create **10 posts**:
   - 5 **card reels** (the main format), id `YYYY-MM-DD-card-<slug>`
   - 2 **text reels on faceless footage**, one of them "דעה לא פופולרית",
     id `YYYY-MM-DD-<slug>`
   - 2 **carousels** built on a reversal, id `YYYY-MM-DD-<slug>`
   - 1 **comparison** carousel (5 or 6 matching pairs), id `YYYY-MM-DD-<slug>`
4. Schedule: one post at `20:00` every day, plus a second post at `10:00` on three
   of the days (carousels and the comparison go at 10:00). Never more than 2 a day.

Stories: the daily 12 to 15 frame sequence in the brief needs stickers, other
creators' reels and real proof, which the API cannot post. Do not queue it. The
owner asks for it in chat.

## Formats in DOXA terms

**Card reel** (`style: card`): a static tweet-style card. It has a black background,
the brand avatar (`assets/brand/avatar.jpg`), the name "סילבר פוקס" and white
right-aligned text. All lines are visible from the first frame. The brief's
structure is 4 to 6 short lines: a scroll-stopping opener, then 3 or 4 lines of
diagnosis, then a closer that lands like a punch.

```yaml
id: 2026-11-20-card-example
publish_at: "2026-11-20 20:00"
mode: reel
pillar: dating
caption: |-
  <line 1 of the card>

  <one line from config/cta.yaml, verbatim; prefer the book lines>
  .
  <5 hashtags>
reel:
  lines: [<4 to 6 short lines>]
  music: <slow, confident instrumental from doxa-private/music/>
  per_line: 1.0
  hold: <13 minus (number of lines minus 1)>
  style: card
source:
  file: 06.md
  section: <the ### heading>
status: queued
```

**Text reel on footage**: the same reel post with `video:` and no `style`.
- The clip must have **no faces**: a night drive, hands on a wheel, a watch, morning
  coffee, a gym from behind, a walk alone on the beach, a silhouette.
- Up to 6 lines (the validator caps plain reels at 6).
- Timing: `per_line 2.2`, `hold = 13 - 2.2 x (lines - 1)`.
- Every clip is used once. If no unused faceless clip fits, add a free Pexels clip
  to `doxa-private/video/` and credit it in `video/CREDITS.md`. If you cannot, use
  a card reel instead.

**Carousel / comparison**: `mode: render`, `format: bold`, slides with `title` and,
where needed, `body`. Follow the brief:
- 7 to 10 slides, one idea per slide.
- Slide 1 is the hook.
- Slides 2 and 3 show a scene the reader recognises.
- The middle slide holds the reversal (a one-question slide is allowed).
- The second to last slide holds the principle in one quotable sentence.
- The last slide is one step for tomorrow morning.
- A comparison puts the first man in the `title` and the second in the `body`, same
  length and rhythm, 5 or 6 pairs.

## Pillars, hook, call to action

- `pillar:` one of `dating`, `body`, `status`, `mind`, `second-round`. Two
  consecutive posts (by `publish_at`, across the whole queue) never share a pillar.
- Line 1 (reel) or slide 1 title (carousel) is the hook, 3 to 18 words. The caption
  opens with the same line.
- Exactly one line from `config/cta.yaml`, word for word, never the same as the
  previous post. Prefer the soft book lines ("זה מפורט בספר." / "הכל כתוב בספר.").
  Never "buy", never a price, never "link in bio" (there is no link yet).
- At most 5 hashtags, at the end of the caption only.

## Hard rules (owner's, all mandatory)

- Everything in `voice/BRIEF.md` "מה אסור". The rules that matter most:
  - no contempt for women and no generalizing about them
  - no mocking a person
  - no clichés
  - no "5 tips" lists
  - no promised results
  - nothing invented: no reader messages, numbers or stories
- The brand is anonymous. Never the owner's name, his life story or any identifying
  detail (see `rules_private.yaml`). Examples use "דני".
- The book's positions win: the man is the prize and does not chase. When she
  vanishes, nothing is sent. Never a restaurant on a first date. Consent is a red line.
- No dashes (`-`, `–`, `—`, `־`) except in the signature line. No "!". No emoji.
- No exact ages for people in the text. Write "בגילך" or "בשנות הארבעים".
- Mask crude words (Zונה, Sקס, לZיין). The brief prefers sharp over crude anyway.
- The reader is a doer: never build a post around a lonely man drinking at home and
  texting.

## Check, then publish to the queue

```bash
doxa rules --strict <all new ids>   # ✓ for every post, no findings
doxa validate                       # must pass
doxa used                           # refresh content/used.yaml
pytest -q                           # must pass
git add queue assets content && git commit -m "content: week of <D1> (brief mix)"
git push origin HEAD:main
```

If a post has a finding, rewrite the line. Never edit the rules to make a post pass.
GitHub then renders everything. Auto-approved posts wait 24 hours, and the owner can
veto any post with the `hold` label on its issue.

## Summary to print at the end

A table: date, time, id, format (card / text reel / carousel / comparison), pillar,
source section, hook.
