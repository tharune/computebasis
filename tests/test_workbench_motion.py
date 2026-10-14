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
ENTRANCE_KEYFRAMES = ("bf-rise", "bf-fade", "bf-rule", "bf-grow", "view-in")


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

    def test_reduced_motion_still_stops_everything_else(self):
        body, _ = block_after("@media (prefers-reduced-motion: reduce)", GLOBAL_CSS)
        self.assertIn("animation: none !important", body)
        self.assertIn("transition: none !important", body)

    def test_print_shows_everything(self):
        body, _ = block_after("@media print")
        self.assertIn("opacity: 1", body)


if __name__ == "__main__":
    unittest.main()
