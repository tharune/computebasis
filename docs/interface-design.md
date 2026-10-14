# Interface design

The workspace serves analysts comparing evidence, contract economics and capacity.
Use readable working text, aligned figures and clear action hierarchy. Data and
decision states should carry the visual weight.

Use a neutral canvas, top navigation and thin section rules.
Keep tables and editors as clear working surfaces. Avoid nesting boxed cards,
adding decorative badges or using oversized full-width actions on desktop.
Color explains selected capacity, held decisions and errors.

Filled buttons identify the principal action, such as evaluation, validation
or saving. Outlined buttons
identify loading or applying a configuration. Quiet text buttons identify examples,
filter resets and other utilities. Each treatment has visible hover, pressed,
disabled and keyboard-focus states. Do not add decorative gradients, glow, shadow
or motion to controls.

Working text and labels use 12–14px desktop type; auxiliary timestamps and
attribution may be smaller. Mobile buttons and labelled form controls have a 44px minimum touch height. Mobile
inputs use 16px text to keep editing readable without automatic focus zoom.
Keep table overflow inside its own scroll region, and wrap long identifiers and
revision feedback without hiding page overflow.

Keep synthetic and held states explicit. Static explanatory labels use plain
metadata rather than status badges. Pricing precision, unit labels, source rights,
auth behavior and disabled execution remain governed by their existing contracts.

Review a completed synthetic scenario, the empty workspace, policy controls and
inventory on desktop and mobile. Check readable disabled controls, visible focus,
touch targets, long values and source-specific native units. Existing behavior and
security tests cover handlers; visual review covers the presentation.

Light and dark themes share the same information hierarchy. Start from the
system color preference; the top-bar toggle changes the current page without
reading a feed, clearing a draft or changing a pricing policy. The preference
stays in page memory. CSRF tokens and workspace data stay in page memory; session cookies are short-lived and HttpOnly.
Dark theme applies to tables, editors, notices, source states and local map
geometry, with separately reviewed text, control-border and focus contrast.
Keep the navigation horizontally scrollable within its own region at narrow
widths; the page itself must not overflow.
