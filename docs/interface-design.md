# Interface design

The workspace serves someone comparing GPU quotes. It should answer one question
quickly: what does each quote cost all-in, and which sellers are worth pricing?
Figures and decision states carry the visual weight; chrome stays out of the way.

## Flow

Four primary pages in one top navigation: **Brief**, **Overview**, **Quotes**,
**Pricing**. The Brief states the problem in the book's own numbers. Overview shows
what the desk holds and brokered (positions and bids from `GET /v1/book/desk`, simulated), the state of
the market (basis, price history, eligible supply, why quotes are held back, seller health) and a US map of
where quoted capacity sits; it holds the scenario controls. Quotes takes one model at a time: a headline, a
quote ladder on one price axis, why quotes are not eligible, a ranked table and the selected quote's cost breakdown. **Price this
quote** carries the selected ask to Pricing, which fills the contract form with it;
nothing is evaluated or saved until the person presses Evaluate contract.
There is no other page: the earlier advanced tools were removed from the browser (their API routes remain).

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
**Price this quote**, **Evaluate contract**. Outlined buttons start a scenario or
open a related page. Quiet text buttons are utilities such as Pause and Reset. Each
has visible hover, pressed, disabled and keyboard-focus states. Controls carry no
decorative gradient, glow or shadow, and no motion beyond a short colour change.

## Motion

Motion shows what arrived or what changed; it is not decoration. The Brief plays one
entrance, once, on first load, in steps of 60 to 90ms: the header fades, then the
headline, the sentence and the buttons rise, the chart panel follows, and when the
book arrives each chart row lands 50ms after the one above it (label and bar, then
the value) while the four figures rise beside them. Everything is in place by about
1.2s. Below the fold, each block rises as it scrolls into view and its children
follow 90ms apart (a block that is already above the screen is shown at once). Where
the browser supports scroll-driven animation, a block that scrolls up under the
header fades and drifts over its last stretch only: the range is measured from the
block's trailing edge, so a block taller than the screen fades just the strip that is
leaving, and nothing on screen is ever hidden. Choosing Open the overview or Browse
the quotes fades the whole landing page out over 180ms, then the app fades in; going
back fades the landing page in again, not the entrance. With reduced motion, no
timers, a hidden tab or a second click, the page switches at once. Live updates
redraw without any entrance, so nothing flickers while the book ticks.

Entrances animate opacity and transform only, with the shared ease token. All of it
sits inside `prefers-reduced-motion: no-preference`; with reduced motion, or without
`IntersectionObserver`, nothing is hidden, moved or timed. A block marked `rv` in
`index.html` must also be listed in `REVEAL` in `page-brief.js`, or it would stay
invisible; a test holds the two together.

## Honesty about the data

The book is simulated locally, and the only disclosure is the footer line. Prices
keep their native units and exact digits. Held and indicative states stay explicit,
and nothing on screen implies an executed trade. A hold is explained, not hidden.

## Checks

Working text in the app is 12–14px on desktop. The Brief has its own fluid scale in `landing.css` (display, h2, h3, lede, intro, body, small, figure), which grows with the viewport from 390 to 2000px: nothing is under 13px and body copy is 17px or more from 1024px up. The Brief sits on full-width tonal bands (canvas, band, panel, one deep closing band); each surface resets `--canvas` so a chart's text halo matches it. On mobile, buttons, tabs and form fields outside
tables are at least 44px tall and inputs use 16px text; table rows stay compact.
Tables scroll inside their own region, and the page never scrolls sideways.

Tests enforce the structural rules: no inline style or script, no `innerHTML`, no
`localStorage`, every `byId` id present in `index.html`, and light, dark and
system-mirror tokens in parity. Visual review covers the rest: each page in light and
dark, at desktop width and at 390px, with the book moving (Price war, Supply shock,
Provider downgrade, Reset) and with long values and missing data.
