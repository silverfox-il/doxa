# Weekly content routine

A scheduled agent runs this every Thursday. It fills the queue for the next 7 days
with posts written in the book's voice. Nobody reviews the output before it is queued, so
follow every rule below exactly. The automatic checks (`doxa rules`, `doxa validate`)
are a safety net; they do not replace them.

## Inputs

- This repo, `silverfox-il/doxa` (public).
- The private repo `silverfox-il/doxa-private`, checked out next to this one:
  - `book/*.md`: the book, new edition. **The only source of ideas, tone and positions.**
  - `book/old/*.txt`: old edition, PDF extract with broken line order. Do **not** use it.
  - `rules_private.yaml`: identity terms. Read it, never copy it anywhere.
- `content/used.yaml`: every line and book section already in the queue. Never repeat a line,
  and prefer sections no post has used yet.
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
   - one **teaser series** at `18:00`, id `YYYY-MM-DD-tease-<slug>` (see below)
   - one **carousel** at `20:00`, id `YYYY-MM-DD-<slug>`

That makes 21 posts. The slug is 1 to 4 lowercase English words joined by `-`.

Regular posts get no automatic story: the owner shares them to his story himself
(only the app can attach a link to the post).

## Teaser series (daily, 18:00)

A reel that provokes, plus 2 follow-up stories. The reel goes to the feed and
brings the traffic; the system then posts the reel video and the 2 follow-ups to
stories, in order. It is a `mode: reel` post with `reel.stories`:

- **Story 1 = the reel** (2 to 4 short lines): a provocation that stings. It calls
  the reader out on something he does, says the uncomfortable thing everyone
  thinks, or picks a fight with an excuse. In the book's voice, talking to him.
- **Story 2** (up to ~120 characters): the twist that makes it worse, or proves
  the point. Short, punchy, it should make him want to answer.
- **Story 3** (up to ~120 characters): the payoff or a cliffhanger that sends him
  to the profile ("זה בדיוק מה שנפרק בפוסט של הערב"), or asks him to answer the
  story. The image gets a banner pointing to the profile automatically.

Trolling means provoking the READER (his excuses, habits, ego), never mocking women
as a group, never fake urgency or fake numbers. Every hard rule applies to all
three parts. Pillar and call to action rotate like any post (`doxa validate`
checks both).

```yaml
id: 2026-10-11-tease-good-morning
publish_at: "2026-10-11 18:00"
approved: false
mode: reel
pillar: dating
caption: |-
  <the hook: reel line 1>

  <one line from config/cta.yaml, verbatim>
  .
  #גרושים #פרק_ב #היכרויות #גברים_מעל_45 #סילברפוקס
reel:
  lines:
  - <the hook, 3 to 12 words>
  - <next line>
  stories:
  - <story 2>
  - <story 3>
  music: <a file name from doxa-private/music/>
  per_line: 3.0
  hold: 5.0
source:
  file: 02.md
  section: <heading the idea comes from>
```

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
provocative, scroll-stopping line of the post, 3 to 12 words. Never a connector
("תזכור:", "אז"). The caption opens with the same hook line.

## Formats (rotate)

Carousels set `format:` and rotate it through the week: `photo` (text over a pool
photo, needs `background:` on every slide), `tweet` (the quote as a post card; no
`background:`; up to ~200 characters per slide) and `bold` (huge type on flat colour;
no `background:`; up to ~90 characters per slide). Use each at least twice a week.
Reels have no `format`.

## Call to action (mandatory)

Every caption has exactly one line copied word for word from `config/cta.yaml`.
Never write your own. Do not use the same line on two consecutive posts.

## Writing: the book's voice (the owner's rule)

The goal is an audience that is hooked on the content and learns from it, and
that feels it is real. So the posts are **not** copied word for word. Each post
takes one idea from one book section and turns it into insights and conclusions,
written exactly the way the book talks:

- **The book's voice.** Its tone, slang, bluntness, attitude and rhythm: short
  sentences, direct "you", spoken Hebrew, a punch in every line, no corporate or
  coaching language, no softening. Read the section first and write like its author.
  Strong book lines may be quoted as they are.
- **Talk to him, not about him.** Always second person, like the book: "אם אתה ...
  אז ...", "אם אתה עד כדי כך דפוק ש...", "אתה ...". Never preach in the third
  person ("גבר ש...", "גבר מהוסס ...", "וגבר שלא ..."); `style_rules` blocks it.
- **Correct, natural Hebrew.** Read every line aloud the way an Israeli guy talks.
  Right verb forms ("היא צריכה להידלק ממך", never "להיות נדלקת"), no sentences that
  sound translated, no stiff written register.
- **The book's positions only.** Never invent advice the book does not give, and
  never contradict it. Every post keeps `source:` with the section its idea comes from.
- **One idea per post.** Spread across the chapters: `02.md` (the market, the magnet,
  money, looks), `06.md` (approaching, fear), `08.md` (body, gym, sleep), `11.md`
  (second round, red flags), `01.md`.
- Skip `07.md` (explicit sex): Instagram would restrict the account.

### Crude words: keep the edge, mask the word

Instagram restricts accounts that are too explicit. Keep the attitude, but write
crude words masked, as `config/rules.yaml` (`masked_words`) lists them. The raw word
blocks the post. Examples:

| never write | write |
|---|---|
| זונה, זונות | Zונה, Zונות |
| לזיין, מזדיין, זיון | לעשות את המעשה, עושה את המעשה, המעשה |
| זין | Zין |
| סקס | Sקס |
| אורגזמה | אורגZמה |
| שרמוטה | שרמו*ה |
| כוסית | Kוסית |

An idiom that is crude only by its word ("לזיין את השכל") is rephrased in the
same spirit ("לבלבל את השכל").

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
  signature line "אתה צריך להיות הסיבה – לא האפקט".
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
  <the hook: slide 1>

  <one line from config/cta.yaml, verbatim>
  .
  #גרושים #פרק_ב #היכרויות #גברים_מעל_45 #סילברפוקס
slides:
- background: assets/backgrounds/2026-10-11-example.jpg
  title: <the hook, 3 to 12 words>
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
  <the hook: reel line 1>

  <one line from config/cta.yaml, verbatim>
  .
  #גרושים #פרק_ב #היכרויות #גברים_מעל_45 #סילברפוקס
reel:
  lines:
  - <the hook, 3 to 12 words>
  - <next line>
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
git add queue assets content && git commit -m "content: week of <D1> (7 reels, 7 teaser series, 7 carousels)"
git push origin HEAD:main
```

If any post has a finding, fix it by rewriting the line in the book's voice. Never edit the rules
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
