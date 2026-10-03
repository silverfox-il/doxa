# Weekly content routine

A scheduled agent runs this every Thursday. It fills the queue for the next 7 days
using only text from the book. Nobody reviews the output before it is queued, so
follow every rule below exactly. The automatic checks (`doxa rules`, `doxa validate`)
are a safety net; they do not replace them.

## Inputs

- This repo, `silverfox-il/doxa` (public).
- The private repo `silverfox-il/doxa-private`, checked out next to this one:
  - `book/*.md`: the book, new edition. **This is the only text you may use.**
  - `book/old/*.txt`: old edition, PDF extract with broken line order. Do **not** use it.
  - `rules_private.yaml`: identity terms. Read it, never copy it anywhere.
- `content/used.yaml`: every quote already in the queue. Never reuse a quote.
- `assets/pool/pool.yaml`: licensed background photos (`used_by: null` = free).

Set up:

```bash
pip install -e ".[dev]"
export DOXA_BOOK_DIR=<path to doxa-private>/book
git config user.name silverfox-il
git config user.email 333442913+silverfox-il@users.noreply.github.com
```

## What to produce

1. Find the last `publish_at` date in `queue/*/post.yaml`. Call the next day D1.
2. Do nothing (report "queue already full") if D1 is more than 10 days from today.
3. For D1 through D7 create:
   - one **reel** at `13:00`, id `YYYY-MM-DD-reel-<slug>`
   - one **carousel** at `20:00`, id `YYYY-MM-DD-<slug>`

That makes 14 posts. The slug is 1 to 4 lowercase English words joined by `-`.

## Pillars (rotate, never two in a row)

Every post has `pillar:`. Ordered by `publish_at` across the whole queue (including
the last posts already queued before D1), two consecutive posts may never share a
pillar; `doxa validate` blocks it. Over a week use each pillar 2 or 3 times.

| pillar | what | where in the book |
|---|---|---|
| `dating` | dating at 45+, approaching, the man is the prize | `06.md`, `02.md` |
| `body` | body, gym, sleep, looks | `08.md`, `02.md` |
| `status` | money, status, image, the market | `02.md`, `01.md` |
| `mind` | the head after the divorce, fear, ego | `06.md`, `02.md` |
| `second-round` | a second relationship, red flags | `11.md` |

## The hook (mandatory)

Slide 1 of a carousel and line 1 of a reel are the hook: the single most
provocative, scroll-stopping line of the post, 3 to 12 words, verbatim. Never a
connector ("תזכור:", "אז"). You may reorder whole slides so the hook comes first;
every line must still be an exact substring of the book. The caption opens with the
same hook line.

## Formats (rotate)

Carousels set `format:` and rotate it through the week: `photo` (text over a pool
photo, needs `background:` on every slide), `tweet` (the quote as a post card; no
`background:`; up to ~200 characters per slide) and `bold` (huge type on flat colour;
no `background:`; up to ~90 characters per slide). Use each at least twice a week.
Reels have no `format`.

## Call to action (mandatory, the only non-book text)

Every caption has exactly one line copied word for word from `config/cta.yaml`.
Never write your own. Do not use the same line on two consecutive posts.

## Choosing passages

- One strong passage per post: the punchiest, most quotable lines of a section. It
  should hit like a punch to the gut. Prefer sections no post has used yet (see the
  `source:` keys in `content/used.yaml`), and spread across the chapters: `02.md`
  (the market, the magnet, money, looks), `06.md` (approaching, fear),
  `08.md` (body, gym, sleep), `11.md` (second round, red flags).
- Skip `07.md` (explicit sex): Instagram would restrict the account.
- **Word for word.** You may only cut: drop whole sentences, or cut a sentence at a
  comma or a full stop. Never rephrase, reorder words, merge sentences, fix spelling,
  add words, or write "in the style of" the book. Every slide line, reel line and
  caption hook must be an exact substring of the book.
- Keep the profanity and the edge. Do not soften anything.

## Hard rules (the owner's, all mandatory)

- No hint of a book, an edition, a sale, a price or a course before 500 followers.
  Never mention "fire your boss". Never "the original book", "the old version".
- Examples use "דני". Never the owner's name or any identifying detail (name, city,
  workplace). See `rules_private.yaml`.
- Ages: the audience is men 45+. A 45 year old dates women from 37, a 50 year old
  from 42. Skip any passage that implies younger women.
- The book's positions: the man is the prize and does not chase. No date without a
  phone number. First date at his home over good wine (in summer also a beach, a
  lookout or a night swim). Never a restaurant on a first date. Nothing about going
  down on her or vibrators.
- Consent is a red line. No humiliating women as a group. No ethnic stereotypes.
- No dashes of any kind (`-`, `–`, `—`, the Hebrew maqaf `־`), except in the
  signature line "אתה צריך להיות הסיבה – לא האפקט". If a passage has a dash,
  cut around it or pick another passage.
- Never the word "זרג".
- No calls to buy followers, follow/unfollow, fake reviews or fake urgency.

## Format

Carousel (4 to 7 slides, one quote per slide, `title` only):

```yaml
id: 2026-10-11-example
publish_at: "2026-10-11 20:00"
approved: false
mode: render
format: photo            # or tweet / bold (then no background: lines)
pillar: dating
caption: |-
  <the hook: slide 1, verbatim>

  <one line from config/cta.yaml, verbatim>
  .
  #גרושים #פרק_ב #היכרויות #גברים_מעל_45 #סילברפוקס
slides:
- background: assets/backgrounds/2026-10-11-example.jpg
  title: <the hook, verbatim, 3 to 12 words>
  layout: bottom
# ...one block per slide, same background
source:
  file: 02.md
  section: <the ### heading the passage sits under>
```

For `format: photo`, get the background with `doxa pool-take <post-id> --tag <whiskey|wine|watch|gym|city|sea|car|home|bar|balcony|work|rain|coffee|style>`.
Pick a tag that fits the passage. It copies a free pool photo and marks it used.

Reel (2 to 6 short lines that appear one by one, 10 to 15 seconds):

```yaml
id: 2026-10-11-reel-example
publish_at: "2026-10-11 13:00"
approved: false
mode: reel
pillar: status
caption: |-
  <the hook: reel line 1, verbatim>

  <one line from config/cta.yaml, verbatim>
  .
  #גרושים #פרק_ב #היכרויות #גברים_מעל_45 #סילברפוקס
reel:
  lines:
  - <the hook, verbatim, 3 to 12 words>
  - <verbatim>
  music: <a file name from doxa-private/music/>
  per_line: 3.0
  hold: 5.0
source:
  file: 02.md
  section: <heading>
```

Timing by line count: 2 lines: `per_line 4.0, hold 7.0`. 3 lines: `3.0, 5.0`.
4 lines: `2.4, 4.0`. 5 lines: `2.2, 4.0`. 6 lines: `1.9, 4.0`.
Pick the music at random, without repeating the previous day's track.

## Check, then publish to the queue

```bash
doxa rules --strict <all new ids>   # must print ✓ for every post, no findings at all
doxa validate                       # must pass
doxa used                           # refresh content/used.yaml
pytest -q                           # must pass
git add queue assets content && git commit -m "content: week of <D1> (7 reels, 7 carousels)"
git push origin HEAD:main
```

If any post has a finding, fix it by choosing different lines. Never edit the rules
to make a post pass. If you cannot fill all 14 slots cleanly, queue fewer and say
so in the summary. If the push to `main` is refused, push a branch and open a pull
request instead.

GitHub then renders everything. If the owner has set `DOXA_AUTO_APPROVE=true`,
posts with zero findings are approved and wait 24 hours. The owner can veto any
post with the `hold` label on its issue.

Every published post is also shared once as a story automatically (the reel
itself, or slide 1 of a carousel framed 9:16). Nothing to do for that.

## Summary to print at the end

A table: date, time, id, type, format, pillar, source section, hook. Then the number of free
photos left in the pool (`doxa pool-take` prints it); warn below 20.
