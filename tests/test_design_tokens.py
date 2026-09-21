# SPDX-License-Identifier: Apache-2.0
"""Design-token contract for the admin console and the macOS app.

``omlx/admin/tokens.json`` is the single source for every colour, spacing,
radius and type size; ``static/css/tokens.css`` and
``apps/omlx-mac/Sources/Theme/DesignTokens.swift`` are generated from it and
committed. These are static assertions (no browser, no server): they pin the
generated artifacts to the source, keep the six-level type scale and its floor
honest on both platforms, and keep literal colours/sizes out of the shared
component stylesheet.
"""

import importlib.util
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ADMIN = ROOT / "omlx" / "admin"
TOKENS_PATH = ADMIN / "tokens.json"
TOKENS = json.loads(TOKENS_PATH.read_text(encoding="utf-8"))

CSS = (ADMIN / "static" / "css" / "tokens.css").read_text(encoding="utf-8")
COMPONENTS_CSS = (ADMIN / "static" / "css" / "components.css").read_text(encoding="utf-8")
TAILWIND_CONFIG = (ADMIN / "tailwind.config.js").read_text(encoding="utf-8")
BASE = (ADMIN / "templates" / "base.html").read_text(encoding="utf-8")
DASHBOARD = (ADMIN / "templates" / "dashboard.html").read_text(encoding="utf-8")
SWIFT = (ROOT / "apps" / "omlx-mac" / "Sources" / "Theme" / "DesignTokens.swift").read_text(
    encoding="utf-8"
)
PBXPROJ = (ROOT / "apps" / "omlx-mac" / "oMLX.xcodeproj" / "project.pbxproj").read_text(
    encoding="utf-8"
)

TEMPLATES = sorted((ADMIN / "templates").rglob("*.html"))
# Only the stylesheets the console authors itself; the rest is vendor JavaScript.
OWN_STYLESHEETS = [ADMIN / "static" / "css" / "dashboard.css", ADMIN / "static" / "css" / "components.css"]
OWN_SCRIPTS = [
    ADMIN / "static" / "js" / name
    for name in ("dashboard.js", "cluster_v2.js", "usage.js", "logs.js")
]
SWIFT_SOURCES = sorted((ROOT / "apps" / "omlx-mac" / "Sources").rglob("*.swift"))

SCALE = TOKENS["typography"]["scale"]
FLOOR = TOKENS["typography"]["floor"]
APP_FONT_MODIFIERS = ("omlxText", "omlxMono", "omlxDisplay")
APP_FONT_CALL = re.compile(rf"(?:{'|'.join(APP_FONT_MODIFIERS)})\(\s*(\d+(?:\.\d+)?)")


def _declares(name: str, value: str, stylesheet: str = CSS) -> bool:
    """True when the stylesheet declares `name: value` (values are aligned)."""
    return re.search(rf"{re.escape(name)}:\s*{re.escape(value)};", stylesheet) is not None


def _load_generator():
    spec = importlib.util.spec_from_file_location(
        "omlx_build_tokens", ADMIN / "build_tokens.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# === Generated artifacts match tokens.json ===


def test_generated_css_is_current():
    assert _load_generator().render_css(TOKENS) == CSS, (
        "tokens.css is stale; run python omlx/admin/build_tokens.py"
    )


def test_generated_swift_is_current():
    assert _load_generator().render_swift(TOKENS) == SWIFT, (
        "DesignTokens.swift is stale; run python omlx/admin/build_tokens.py"
    )


def test_swift_tokens_are_compiled_by_the_app():
    assert "DesignTokens.swift" in PBXPROJ
    assert PBXPROJ.count("DesignTokens.swift") >= 4, (
        "a new Swift file needs a PBXBuildFile, a PBXFileReference, a group "
        "child and a Sources-phase entry"
    )


# === One six-level type scale ===


def test_scale_has_exactly_six_levels():
    assert list(SCALE) == ["aux", "body", "emphasis", "section", "page", "kpi"]
    assert [step["px"] for step in SCALE.values()] == [10, 12, 15, 17, 20, 28]


def test_css_exposes_the_scale_and_the_floor():
    for name, step in SCALE.items():
        assert _declares(f"--fs-{name}", f"{step['px']}px")
        assert f".text-{name} {{" in CSS
        assert f"var(--fs-{name})" in CSS
    assert _declares("--fs-floor", f"{FLOOR['aux']}px")
    assert _declares("--fs-floor-body", f"{FLOOR['body']}px")
    assert _declares("--fs-floor-enhanced", f"{FLOOR['enhancedReadability']}px")


def test_tailwind_named_sizes_resolve_to_tokens():
    block = re.search(r"fontSize:\s*\{(.*?)\n    \},", TAILWIND_CONFIG, re.DOTALL)
    assert block is not None, "tailwind.config.js must define the type scale"
    sizes = re.findall(r"'?([a-z0-9]+)'?:\s*\[([^\]]+)\]", block.group(1))
    assert sizes, "no font sizes found in the Tailwind theme"
    allowed = {f"var(--fs-{name})" for name in SCALE}
    for name, value in sizes:
        first = value.split(",")[0].strip().strip("'")
        assert first in allowed, f"text-{name} is not a token step: {first}"
    # Every alias maps onto a step of the ladder.
    aliases = TOKENS["typography"]["tailwindAliases"]
    mapping = {name: value.split(",")[0].strip().strip("'") for name, value in sizes}
    for alias, step in aliases.items():
        if alias in mapping:
            assert mapping[alias] == f"var(--fs-{step})"


def test_off_scale_arbitrary_sizes_snap_to_the_ladder():
    # tokens.css pulls the two off-scale sizes that existed in the markup onto
    # the ladder, so they cannot come back through a copy-pasted class.
    assert re.search(r"\.text-\\\[9px\\\]\s*\{[^}]*var\(--fs-aux\)", CSS)
    assert re.search(r"\.text-\\\[11px\\\]\s*\{[^}]*var\(--fs-body\)", CSS)


def test_templates_only_use_scale_sizes():
    allowed = {step["px"] for step in SCALE.values()}
    offenders = {}
    for path in TEMPLATES:
        for size in re.findall(r"text-\[(\d+)px\]", path.read_text(encoding="utf-8")):
            if int(size) not in allowed:
                offenders.setdefault(str(path.relative_to(ROOT)), set()).add(size)
    assert not offenders, f"off-scale Tailwind font sizes: {offenders}"


def test_no_text_below_the_auxiliary_floor():
    offenders = {}
    pattern = re.compile(r"font-size:\s*(\d+(?:\.\d+)?)px")
    for path in TEMPLATES + OWN_STYLESHEETS + OWN_SCRIPTS:
        for value in pattern.findall(path.read_text(encoding="utf-8")):
            if float(value) < FLOOR["aux"]:
                offenders.setdefault(str(path.relative_to(ROOT)), set()).add(value)
    assert not offenders, f"text below the {FLOOR['aux']}px floor: {offenders}"


def test_app_text_respects_the_floor():
    offenders = {}
    for path in SWIFT_SOURCES:
        for value in APP_FONT_CALL.findall(path.read_text(encoding="utf-8")):
            if float(value) < FLOOR["aux"]:
                offenders.setdefault(str(path.relative_to(ROOT)), set()).add(value)
    assert not offenders, f"app text below the {FLOOR['aux']}pt floor: {offenders}"


def test_enhanced_readability_floor_matches_the_token():
    assert _declares("--fs-floor-enhanced", f"{FLOOR['enhancedReadability']}px")
    assert "font-size: 12px !important" in BASE, (
        "base.html lifts sub-12px text to the enhanced-readability floor"
    )


# === The token layer owns colour ===


def test_components_use_tokens_only():
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", COMPONENTS_CSS), "literal colour in components.css"
    sizes = set(re.findall(r"(\d+(?:\.\d+)?)px", COMPONENTS_CSS))
    assert sizes <= {"1"}, f"literal sizes in components.css: {sizes}"
    for value in re.findall(r"(?:font-size|padding|margin|gap|border-radius):[^;]+;", COMPONENTS_CSS):
        assert "var(--" in value or value.rstrip(";").endswith(": 0"), (
            f"value not backed by a token: {value}"
        )


def test_base_loads_the_token_layer_before_page_styles():
    tailwind = BASE.index("css/tailwind.css")
    tokens = BASE.index("css/tokens.css")
    components = BASE.index("css/components.css")
    assert tailwind < tokens < components
    assert "css/tokens.css" in BASE and "css/components.css" in BASE


def test_base_uses_the_system_font_stack():
    assert "/fonts/inter" not in BASE, "no self-hosted webfonts"
    assert "noto-sans" not in BASE, "no self-hosted CJK webfonts"
    assert "BlinkMacSystemFont" in CSS


# === Layout skeleton ===


def test_one_gutter_and_two_content_measures():
    layout = TOKENS["layout"]
    assert _declares("--gutter", f"{layout['gutter']}px")
    assert _declares("--container-form", f"{layout['formMaxWidth']}px")
    assert _declares("--container-wide", f"{layout['wideMaxWidth']}px")
    assert ".page-gutter {" in CSS
    assert ".page-wide {" in CSS
    assert ".page-narrow {" in CSS
    assert f"scrollbar-gutter: {layout['scrollbarGutter']};" in CSS


def test_dashboard_pages_use_the_layout_classes():
    assert "page-gutter" in DASHBOARD, "one gutter for every tab"
    # The Status tab keeps the width control the layout feature ships
    # (`dashboardWidthClass`); every other tab takes a fixed measure.
    tabs = {
        "_models.html": "page-wide",
        "_logs.html": "page-wide",
        "_cluster_v2.html": "page-wide",
        "_settings.html": "page-narrow",
        "_bench.html": "page-narrow",
    }
    for name, expected in tabs.items():
        text = (ADMIN / "templates" / "dashboard" / name).read_text(encoding="utf-8")
        assert expected in text, f"{name} must use {expected}"
    status = (ADMIN / "templates" / "dashboard" / "_status.html").read_text(encoding="utf-8")
    assert "page-wide" not in status, "the dashboard width control owns this tab"


def test_topbar_is_the_only_translucent_layer():
    assert ".topbar-material {" in CSS
    assert "backdrop-filter: blur(var(--topbar-blur))" in CSS
    navbar = (ADMIN / "templates" / "dashboard" / "_navbar.html").read_text(encoding="utf-8")
    assert "topbar-material" in navbar
    assert "page-gutter" in navbar
