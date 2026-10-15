"""Motion rules in workbench.css: all of it behind no-preference, opacity and transform only, never hiding without a way back."""
from pathlib import Path
import re
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from compute_pricing.control.workbench.routes import ASSETS

def stripped(name):
    return re.sub(r"/\*.*?\*/", "", (ASSETS / name).read_text(encoding="utf-8"), flags=re.S)  # comments mention the selectors


CSS = stripped("landing.css")
GLOBAL_CSS = stripped("workbench.css")  # the all-pages reduced-motion switch lives here
ENTRANCE_KEYFRAMES = ("bf-rise", "bf-fade", "bf-grow", "view-in")


def block_after(marker, css=None):
    """The text between the braces of the block that opens with `marker`, and where it starts."""
    css = CSS if css is None else css
    start = css.index(marker)
    depth, index = 0, css.index("{", start)
    begin = index + 1
    while True:
        if css[index] == "{":
            depth += 1
        elif css[index] == "}":
            depth -= 1
            if depth == 0:
                return css[begin:index], begin
        index += 1


class MotionRulesTests(unittest.TestCase):
    def test_entrance_keyframes_live_only_inside_no_preference(self):
        body, offset = block_after("@media (prefers-reduced-motion: no-preference) {\n  @keyframes bf-rise")
        for name in ENTRANCE_KEYFRAMES:
            positions = [match.start() for match in re.finditer(r"@keyframes " + re.escape(name) + r"\b", CSS)]
            self.assertEqual(len(positions), 1, name + " is defined once")
            self.assertTrue(offset <= positions[0] < offset + len(body), name + " must sit inside prefers-reduced-motion: no-preference")

    def test_hiding_for_reveal_is_gated_and_armed(self):
        body, offset = block_after("@media (prefers-reduced-motion: no-preference) {\n  @keyframes bf-rise")
        hidden = [match for match in re.finditer(r"([^{}]+)\{[^{}]*opacity:\s*0[^{}]*\}", CSS) if "rv-in" in match.group(1)]
        self.assertTrue(hidden, "the reveal hidden state exists")
        for match in hidden:
            self.assertTrue(offset <= match.start() < offset + len(body), "a hidden state outside no-preference would hide content for people who asked for less motion")
            self.assertIn(".rv-on", match.group(1), "content is only hidden once the script has armed the reveal")

    def test_entrances_animate_only_opacity_and_transform(self):
        for name in ENTRANCE_KEYFRAMES:
            body, _ = block_after("@keyframes " + name)
            properties = set(re.findall(r"([a-z-]+)\s*:", body))
            self.assertLessEqual(properties, {"opacity", "transform"}, name + " animates " + ", ".join(sorted(properties)))

    def test_live_chart_transitions_move_only_geometry_and_only_where_motion_is_allowed(self):
        """A poll slides a bar (its path, `d`), its label (`transform`) and fades the tooltip; nothing else about a chart is animated."""
        body, offset = block_after("@media (prefers-reduced-motion: no-preference) {\n  @keyframes bf-rise")
        rules = [match for match in re.finditer(r"([^{}]+)\{([^{}]*\btransition\s*:[^{}]*)\}", CSS) if re.search(r"\.bf-(bar|value|note|chip|seg-label|tip)\b", match.group(1))]
        self.assertTrue(rules, "the chart's live-update transitions exist")
        moved = set()
        for match in rules:
            self.assertTrue(offset <= match.start() < offset + len(body), "a chart transition outside no-preference: " + match.group(1).strip())
            for item in re.search(r"transition\s*:([^;]+)", match.group(2)).group(1).split(","):
                moved.add(item.split()[0])
        self.assertLessEqual(moved, {"d", "transform", "opacity"}, "chart transitions animate " + ", ".join(sorted(moved)))
        self.assertIn("d", moved, "a bar slides to its new length")

    def test_the_first_load_sequence_staggers_in_small_steps_and_finishes_inside_about_a_second_and_a_fifth(self):
        """Header, headline, sentence, buttons, panel, then the numbers and chart rows: each starts later than the one before, none is slow."""
        starts = {}
        for match in re.finditer(r"([^{}]+)\{\s*animation:\s*bf-(?:rise|fade)\s+(\d+)ms\s+var\(--ease\)\s*(?:(\d+)ms\s+)?backwards;", CSS):
            for selector in match.group(1).split(","):
                starts[selector.strip()] = (int(match.group(3) or 0), int(match.group(2)))
        order = [".lp-header", ".brief:not(.bf-entered) .bf-hero-copy h1", ".brief:not(.bf-entered) .bf-hero-copy .bf-sub",
                 ".brief:not(.bf-entered) .bf-hero-copy .bf-actions"]
        delays = []
        for selector in order:
            hits = [value for key, value in starts.items() if selector in key]
            self.assertTrue(hits, selector + " has an entrance")
            delays.append(hits[0][0])
        self.assertEqual(delays, sorted(delays), "the entrance runs in reading order")
        self.assertTrue(all(b - a <= 90 for a, b in zip(delays, delays[1:])), "steps of 90ms or less: " + str(delays))
        entrance, _ = block_after("@media (prefers-reduced-motion: no-preference) {\n  @keyframes bf-rise")
        ends = [delay + length for delay, length in starts.values()]
        for match in re.finditer(r"animation-delay:\s*(\d+)ms", entrance):  # the chart rows and the figures set their own delays
            ends.append(int(match.group(1)) + 360)
        self.assertLessEqual(max(ends), 1200, "nothing in the entrance ends later than 1.2s after it starts: " + str(max(ends)))

    def test_children_of_a_revealed_group_follow_one_another_in_order(self):
        steps = [int(value) for value in re.findall(r"\.rv-group\.rv-in > :nth-child\(\d\) \{ transition-delay: (\d+)ms", CSS)]
        self.assertEqual(steps, [90, 180, 270], "siblings stagger by index, 90ms apart")

    def test_leaving_the_landing_page_fades_it_out_quickly_and_only_where_motion_is_allowed(self):
        body, offset = block_after("@media (prefers-reduced-motion: no-preference) {\n  @keyframes bf-rise")
        rule = re.search(r"([^{}]*\.lp-leaving[^{}]*)\{([^{}]*)\}", CSS)
        self.assertTrue(rule, "a leaving state exists")
        self.assertTrue(offset <= rule.start() < offset + len(body), "the leaving fade sits inside no-preference")
        self.assertIn("opacity: 0", rule.group(2))
        for selector in (".lp-header.lp-leaving", ".brief.lp-leaving", ".lp-footer.lp-leaving"):
            self.assertIn(selector, rule.group(1), "the whole page leaves together: " + selector)
        self.assertLessEqual(int(re.search(r"opacity (\d+)ms", rule.group(2)).group(1)), 200, "the fade out is short")

    def test_scroll_driven_fade_out_is_an_enhancement_that_cannot_hide_what_is_on_screen(self):
        body, offset = block_after("@media (prefers-reduced-motion: no-preference) {\n  @keyframes bf-rise")
        supports, inner = block_after("@supports (animation-timeline: view())")
        self.assertTrue(offset <= inner < offset + len(body), "the scroll-driven fade sits inside no-preference")
        self.assertIn("@keyframes bf-exit", supports)
        keyframes, _ = block_after("@keyframes bf-exit")
        self.assertLessEqual(set(re.findall(r"([a-z-]+)\s*:", keyframes)), {"opacity", "transform"})
        self.assertNotRegex(keyframes, r"\bfrom\b", "no from keyframe: before its range a block is exactly as it is drawn")
        self.assertIn("animation-timeline: view(", supports)
        self.assertRegex(supports, r"animation-range:\s*cover calc\(100% - [^)]*vh\) cover 100%",
                         "the fade covers the last stretch of the block's trailing edge, a length, so a tall block fades only the strip that is leaving")
        self.assertIn("forwards", supports)
        self.assertNotRegex(supports, r"\b(both|backwards)\b", "a backwards fill would draw the block before its range")

    def test_print_drops_every_animation(self):
        body, _ = block_after("@media print")
        self.assertIn("animation: none !important", body)

    def test_reduced_motion_still_stops_everything_else(self):
        body, _ = block_after("@media (prefers-reduced-motion: reduce)", GLOBAL_CSS)
        self.assertIn("animation: none !important", body)
        self.assertIn("transition: none !important", body)

    def test_print_shows_everything(self):
        body, _ = block_after("@media print")
        self.assertIn("opacity: 1", body)


if __name__ == "__main__":
    unittest.main()
