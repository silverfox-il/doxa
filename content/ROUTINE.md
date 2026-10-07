# Weekly content routine

A scheduled agent runs this every Thursday. It fills the queue for the next 7 days
with posts written in the book's voice. Nobody reviews the output before it is queued, so
follow every rule below exactly. The automatic checks (`doxa rules`, `doxa validate`)
are a safety net; they do not replace them.

## Inputs

- This repo, `silverfox-il/doxa` (public).
- The private repo `silverfox-il/doxa-private`, checked out next to this one:
  - `book/*.md`: the book, new edition. **The only source of ideas, tone and positions.**
  - `book/old/*.txt`: the OLD edition (PDF extract, broken line order). It sold 4,000
    copies; its ideas and voice are the gold standard. Take IDEAS from it, never copy it.
  - `voice/VOICE.md`: the voice bible built from the old edition. Read it fully first.
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

1. D1 is the first day from tomorrow on that does not yet have all three daily slots
   (13:00, 18:00, 20:00) in `queue/`. Fill only the empty slots; never move or replace
   an existing post.
2. Do nothing (report "queue already full") if D1 is more than 10 days from today.
3. For D1 through D7 create:
   - one **reel** at `13:00`, id `YYYY-MM-DD-reel-<slug>`
   - one **teaser series** at `18:00`, id `YYYY-MM-DD-tease-<slug>` (see below)
   - one **carousel** at `20:00`, id `YYYY-MM-DD-<slug>`

That makes 21 posts. The slug is 1 to 4 lowercase English words joined by `-`.

Regular posts get no automatic story: the owner shares them to his story himself
(only the app can attach a link to the post).

## Hashtags (rotate by pillar)

Replace the hashtag line with the set that fits the post's pillar (researched
2026-10-07). Never use #dating, #single, #singlelife, #date or #sexy (banned-list
risk), and avoid #silverfox / #menover50 (they pull an unrelated audience).

- dating, second-round: #גרושים #גירושין #פרקב #זוגיות #היכרויות #דייטינג #גבריות #datingafterdivorce #lifeafterdivorce #divorcedmen #israel
- body: #כושר #אימוןכושר #כושרגופני #אחרי50 #גיל50 #גבריות #fitover40 #fitover50 #over50fitness #greyhair #mensstyle
- mind, status: #גירושין #גרוש #אבאגרוש #הורותמשותפת #אבא #mindset #divorcerecovery #divorceddad #coparenting #singledad #ישראל

## Teaser series (daily, 18:00)

A reel that provokes, plus 2 follow-up stories. The reel goes to the feed and
brings the traffic; the system then posts the reel video and the 2 follow-ups to
stories, in order. It is a `mode: reel` post with `reel.stories`:

- **Story 1 = the reel** (5 to 8 short lines; per_line 1.4 to 1.8 so it stays
  10 to 15 seconds): the owner's trolling style. A detached, cynical narrator,
  not a coach:
  - open with a sweeping "state of the world" claim ("אנחנו בעידן ...",
    "רוב הנשים היום ...", "רוב הגברים בגילך ...");
  - every line escalates one short step, dry, no explanations, no advice;
  - third person narration is fine here ("הוא", "הן");
  - end on a sarcastic sting ("פלקס אדיר.", "בונוס.", "כל הכבוד, אלוף.").
  The owner's example: "אנחנו בעידן הפראייר-מקס של נשים בדייטים / רוב הנשים כיום
  מחפשות גברים חלשים לניצול / אחד שיסבול את כל חוסר הכבוד ולא יעזוב לעולם /
  מוכן להיות מנוצל שוב למחרת / אם הוא נראה טוב וגם עשיר? אז בכלל / פלקס אדיר".
  The rendered reel is black, right aligned, like that example.
- **Story 2** (up to ~120 characters): the twist that makes it worse, or proves
  the point. Short, punchy, it should make him want to answer.
- **Story 3** (up to ~120 characters): the payoff or a cliffhanger that sends him
  to the profile ("זה בדיוק מה שנפרק בפוסט של הערב"), or asks him to answer the
  story. The image gets a banner pointing to the profile automatically.

The owner decided (2026-10-04) that teaser series MAY generalize about women
("רוב הנשים ...") like his example. Still never slurs (כלבה, Zונה as an insult,
and the like), never contempt for their worth as people, nothing about consent,
never fake urgency or fake numbers. Regular posts keep the rule: no generalizing
about women as a group. Every hard rule applies to all
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

## Reels: truths about men and women (the owner's rule, 2026-10-07)

Reels (13:00) follow the approach of @shiraz_mizrahi777, whose text reels reach 5K to
37K views on 9K followers, combined with the NEW book (quote it freely):
plain everyday Hebrew, no slang to decode; a claim, a contrast, an ironic sting
("אמרו לגברים: ... אז הם ... והיא? ... תודה על העצה 👏"); truths about men and women
in the third person ("רוב הגברים...", "גבר לא...") are welcome HERE (carousels still
talk to him); describe, never instruct; short lines; one line that stays in the head,
often a verbatim new-book line. Approved examples: `2026-10-05-reel-turned-on`,
`2026-10-09-reel-garden`, `2026-10-11-reel-second-round`.

Every 13:00 reel sets `reel.video` to a background clip from `doxa-private/video/`
(licensed Pexels clips, see its CREDITS.md) that fits the text: `gray-hair`,
`gym-tattoo`, `gym-workout`, `gym-treadmill`, `phone-texting`, `phone-bed`,
`wine-pour`, `wine-sea`, `bar-cheers`, `dinner-candles`, `coffee-garden`,
`coffee-window`, `city-night-walk`, `city-crossing`, `drive-tunnel`, `beach-walk`,
`beach-sunset`, `suit-watch`, `window-silhouette` (file name + `.mp4`). Don't use the
same clip two days in a row.

## Writing: an experienced man telling it (the owner's rule, 2026-10-07)

Thousands already read the old book, so posts must NOT repeat its wording: they'd
be bored. Take ONE idea from the old edition (or the new one), keep the idea, and
retell it fresh, in smart, human words, the way an experienced man who has been
through it explains it to a friend over a beer. The owner approved this through
review rounds; these posts are the reference, match them:

- `2026-10-05-what-looking-for` ("מה אתה מחפש?" היא שואלת. ופה רוב הגברים נופלים.)
- `2026-10-06-first-message` (אם כבר החלטת לשלוח לה הודעה, אז לפחות תעשה את זה נכון:)
- `2026-10-05-approval-chase` (אתה בודק כל חמש דקות אם היא מרוצה ממך? אחי, אתה לא מלצר.)
- `2026-10-05-old-flame` (יש אקס אחד שהיא עוד לא שחררה...)

What the owner asked for, round by round:

- **Spice.** Be a bit cheeky, a bit cynical, a bit chauvinist in a charming way: a
  real man's man, a charmer. Tease her, never humiliate women as a group.
- **Bluntness that lands.** Short lines, real situations ("תראי, אני אחרי גירושים, אני
  עוד לא יודע, תלוי..."), dialogue in quotes, a concrete image, one street word.
- **Open straight into the situation.** "אם כבר החלטת ..., אז לפחות תעשה את זה נכון:"
- **Clear in one read.** If a line needs a second read, rewrite it. Natural spoken
  Hebrew, right verb forms ("להידלק", "וזה מייבש אותה ממש מהר").
- **Closers rotate, and only about one post in three gets one.** Never the same twice
  in a row: "תלמד לשחק את המשחק." / "ככה זה עובד. תתרגל." / "ברוך הבא לסבב השני." /
  "תתחיל להתנהג כמו הפרס." / "אל תהיה עוד אחד בתור." / "תן לה סיבה לרדוף." / "זה לא
  אכזרי. זה המשחק." / "אתה צריך להיות הסיבה – לא האפקט." The rest end on their own punch.
- **Tell, don't lecture or judge.** Describe a scene he recognizes and land an
  insight with a wink. Few imperatives, no "do this, do that" lists, no looking down
  on him ("זה קורה לכולנו" beats "אתה מגוחך"). Rejected round 3 (2026-10-07) read as
  instructions and judgment; approved rewrites read as a story.
- **No clever metaphors that need decoding.** The owner rejected every line he had
  to stop and think about: "תמדוד אותך כמו דירה", "ככה רק קונים מקום בתור", "החולצה
  המהוהה" (literary word). Fixed versions say it plainly: "תעשה לך ראיון עבודה לתפקיד
  'בעל' כבר בדייט הראשון", "ככה קונים תשומת לב. לא משיכה.", "החולצה הדהויה". Use only
  words a 45+ Israeli says out loud; if an image needs explaining, drop it.
- **"אחי" sparingly:** at most once in a post, and not in most posts.
- **The audience is 45 and up, not "50".** Say "אחרי 45", "בגיל שלך", or nothing.
- **Avoid the copywriter tic.** "אתה לא X. אתה Y" at most once per post.
- **45+ only in the technical details:** ages (women 37+), divorce, kids, alimony, the
  ex, the second round, the body after 50, "נשים"/"היא" instead of "בחורות". Never
  soften the expressions, humor, rhythm or attitude.
- **Talk to him.** Second person; never a line that starts with "גבר".
- **The book's positions only.** Never invent advice the book does not give. Keep
  `source:` with the section the idea comes from (internal only, never in the post).
- **Spread across topics:** dating, approaching, texting, red flags, body, the head
  after divorce, money and status. Skip anything explicitly sexual.

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
  layout: center         # photo format: text centered; tweet/bold: bottom
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
