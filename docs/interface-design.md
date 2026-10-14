# Interface design

The workspace serves someone comparing GPU quotes. It should answer one question
quickly: what does each quote cost all-in, and which sellers are worth pricing?
Figures and decision states carry the visual weight; chrome stays out of the way.

## Flow

Four primary pages in one top navigation: **Brief**, **Overview**, **Quotes**,
**Pricing**. The Brief states the problem in the book's own numbers. Overview shows
scale, eligibility, basis and provider health, and holds the scenario controls.
Quotes ranks every quote for one model and opens its cost breakdown. **Price this
quote** carries the selected ask to Pricing, which loads the labelled example in
the editor only; nothing is evaluated or saved until the person presses Evaluate.
Policies, inference, cash, portfolio and the other earlier tools stay under **More**.

Changing page starts at the top of the new page. Choosing the page already showing
leaves the scroll position alone.

## Type, colour and charts

System font stack at 13px, with a monospace face only for identifiers, timestamps
and the all-in formula. Figures are tabular. Headings are sentence case. Labels sit
beside what they describe; do not add an eyebrow above a heading that already says
the same thing, and do not number items that are not a sequence.

Teal is the single accent. Seller grades A to D have fixed colours, and a grade is
never shown by colour alone: badges carry the letter and charts carry a legend.
Expected loss uses the warm warning colour, financing
the accent, and the quoted price a neutral grey. Light and dark themes share the
same hierarchy; the toggle follows the system setting until it is used.

Charts are SVG built by `workbench-charts.js`. Colour arrives only through CSS
classes, so the content security policy needs no inline styles. Each chart states its
unit and its finding in the text beside it, not only in the marks.

## Actions

Filled buttons mark the principal action on a page: **Launch the overview**,
**Price this quote**, **Evaluate scenario**. Outlined buttons start a scenario or
open a related page. Quiet text buttons are utilities such as Pause and Reset. Each
has visible hover, pressed, disabled and keyboard-focus states. Controls carry no
decorative gradient, glow or shadow, and no motion beyond a short colour change.

## Motion

Motion shows what arrived or what changed; it is not decoration. The Brief plays one
entrance, once, on first load: the headline, lede and buttons rise 100ms apart, the
chart's rule draws, and when the book arrives each chart row lands 70ms after the one
above it (label, bar, then value) before the four figures follow. Blocks below the
fold fade up once, as they scroll into view. Between pages, and when the More menu
opens, there is a short fade of a few pixels. Coming back to the Brief is that plain
fade, not the entrance again. Live updates redraw without any entrance, so nothing
flickers while the book ticks.

Entrances animate opacity and transform only, with the shared ease token. All of it
sits inside `prefers-reduced-motion: no-preference`; with reduced motion, or without
`IntersectionObserver`, nothing is hidden, moved or timed. A block marked `rv` in
`index.html` must also be listed in `REVEAL` in `workbench-demo.js`, or it would stay
invisible; a test holds the two together.

## Honesty about the data

The book is simulated locally, and the only disclosure is the footer line. Prices
keep their native units and exact digits. Held and indicative states stay explicit,
and nothing on screen implies an executed trade. A hold is explained, not hidden.

## Checks

Working text is 12–14px on desktop. On mobile, buttons, tabs and form fields outside
tables are at least 44px tall and inputs use 16px text; table rows stay compact, and
the disclosure rows in the advanced editors are smaller than 44px. Tables and editors
scroll inside their own region, and the page never scrolls sideways.

Tests enforce the structural rules: no inline style or script, no `innerHTML`, no
`localStorage`, every `byId` id present in `index.html`, and light, dark and
system-mirror tokens in parity. Visual review covers the rest: each page in light and
dark, at desktop width and at 390px, with the book moving (Price war, Supply shock,
Provider downgrade, Reset) and with long values and missing data.
