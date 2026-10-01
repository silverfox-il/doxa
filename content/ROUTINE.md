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
   - one **carousel** at `07:30`, id `YYYY-MM-DD-<slug>`
   - one **reel** at `18:00`, id `YYYY-MM-DD-reel-<slug>`

That makes 14 posts. The slug is 1 to 4 lowercase English words joined by `-`.

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
publish_at: "2026-10-11 07:30"
approved: false
mode: render
caption: |-
  <one line from the slides, verbatim>
  .
  #גרושים #פרק_ב #היכרויות #גברים_מעל_45 #סילברפוקס
slides:
- background: assets/backgrounds/2026-10-11-example.jpg
  title: <verbatim quote>
  layout: bottom
# ...one block per slide, same background
source:
  file: 02.md
  section: <the ### heading the passage sits under>
```

Get the background with `doxa pool-take <post-id> --tag <whiskey|wine|watch|gym|city|sea|car|home|bar|balcony|work|rain|coffee|style>`.
Pick a tag that fits the passage. It copies a free pool photo and marks it used.

Reel (2 to 6 short lines that appear one by one, 10 to 15 seconds):

```yaml
id: 2026-10-11-reel-example
publish_at: "2026-10-11 18:00"
approved: false
mode: reel
caption: |-
  <the strongest reel line, verbatim (not a connector like "תזכור:")>
  .
  #גרושים #פרק_ב #היכרויות #גברים_מעל_45 #סילברפוקס
reel:
  lines:
  - <verbatim>
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
git add queue assets content && git commit -m "content: week of <D1> (7 carousels, 7 reels)"
git push origin HEAD:main
```

If any post has a finding, fix it by choosing different lines. Never edit the rules
to make a post pass. If you cannot fill all 14 slots cleanly, queue fewer and say
so in the summary. If the push to `main` is refused, push a branch and open a pull
request instead.

GitHub then renders everything. If the owner has set `DOXA_AUTO_APPROVE=true`,
posts with zero findings are approved and wait 24 hours. The owner can veto any
post with the `hold` label on its issue.

## Summary to print at the end

A table: date, time, id, type, source section, first line. Then the number of free
photos left in the pool (`doxa pool-take` prints it); warn below 20.
