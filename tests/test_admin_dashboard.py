# SPDX-License-Identifier: Apache-2.0
"""Structure of the Status tab after the dashboard was rebuilt.

Main turned the tab into a GridStack block layout (`dashboard_blocks` in
`dashboard/_status.html`, one partial per block in `dashboard/blocks/`). This PR
adds the pieces the review asked for on top of that layout: a server status
header card above the grid, KPI cards with sparklines in the serving-stats
block, a memory watermark bar in the active-models block, and the hourly trend
in the usage-history block. The three groups the review described as sub-tabs
are expressed by the block registry and its tray instead of a second navigation
layer — see the PR body.

These are static assertions; the drawing math is covered by
tests/admin_dashboard.test.cjs.
"""

import json
from pathlib import Path

import jinja2

ROOT = Path(__file__).resolve().parents[1]
ADMIN = ROOT / "omlx" / "admin"
DASH = ADMIN / "templates" / "dashboard"
BLOCKS = DASH / "blocks"
STATUS = (DASH / "_status.html").read_text(encoding="utf-8")
SERVING = (BLOCKS / "_serving_stats.html").read_text(encoding="utf-8")
ACTIVE = (BLOCKS / "_active_models.html").read_text(encoding="utf-8")
USAGE = (DASH / "_usage.html").read_text(encoding="utf-8")
DASHBOARD_JS = (ADMIN / "static" / "js" / "dashboard.js").read_text(encoding="utf-8")
USAGE_JS = (ADMIN / "static" / "js" / "usage.js").read_text(encoding="utf-8")
EN = json.loads((ADMIN / "i18n" / "en.json").read_text(encoding="utf-8"))


def _env() -> jinja2.Environment:
    env = jinja2.Environment(loader=jinja2.FileSystemLoader(str(ADMIN / "templates")))
    env.globals.update(t=lambda key: key, static=lambda path: path, version="0.0.0")
    return env


def test_blocks_are_registered_with_their_own_partials():
    for block_id in ("serving_stats", "usage_history", "active_models",
                     "cache_observability", "api_endpoints", "claude_code",
                     "applications", "engine_versions"):
        assert f"('{block_id}', '_{block_id}.html')" in STATUS
        assert (BLOCKS / f"_{block_id}.html").exists()


def test_each_block_partial_renders_on_its_own():
    """The layout editor and the template tests render a partial without the
    dashboard's context, so a partial that needs the shared macros imports them."""
    env = _env()
    for partial in sorted(BLOCKS.glob("_*.html")):
        env.get_template(f"dashboard/blocks/{partial.name}").render()


def test_server_status_header_card():
    header = STATUS[: STATUS.index("<!-- Layout toolbar")]
    assert "status-header__icon" in header
    assert "{{ version }}" in header, "the header shows the running version"
    assert "ui.badge(t('status.header.running'), tone='green', dot=True)" in header
    assert "status.header.uptime" in header
    assert "restartServerStart()" in header, "restart is reachable from the header"
    assert "unloadAllModels()" in header
    assert "mainTab === 'status'" in STATUS


def test_kpi_cards_are_left_aligned_with_a_sparkline_each():
    assert SERVING.count('class="kpi"') == 4
    for key in ("requests", "prompt", "cached", "cache"):
        assert f"sparkPath('{key}')" in SERVING
    assert 'class="kpi__value"' in SERVING
    assert "text-center" not in SERVING, "KPI cards are left aligned"
    assert "kpiHistory" in DASHBOARD_JS
    assert "recordKpiHistory" in DASHBOARD_JS


def test_kpi_history_records_the_series_the_cards_draw():
    body = DASHBOARD_JS[DASHBOARD_JS.index("            recordKpiHistory() {"):][:900]
    for field in ("total_requests", "total_prompt_tokens", "total_cached_tokens", "cache_efficiency"):
        assert field in body, f"{field} is not sampled"


def test_memory_watermark_bar():
    assert "watermark__bar--estimated" in ACTIVE
    assert "watermark__bar--actual" in ACTIVE
    assert "watermark__marker" in ACTIVE
    for key in ("status.memory.actual", "status.memory.estimated",
                "status.memory.soft", "status.memory.hard"):
        assert f"t('{key}')" in ACTIVE
        assert key in EN
    for getter in ("memoryWatermark", "watermarkBarStyle", "watermarkMarkerStyle"):
        assert getter in DASHBOARD_JS


def test_memory_watermark_is_scaled_to_the_hard_limit():
    body = DASHBOARD_JS[DASHBOARD_JS.index("get memoryWatermark()"):][:1400]
    assert "hard_bytes" in body
    assert "soft_bytes" in body
    assert "current_bytes" in body
    assert "estimated_size" in body, "the estimate is summed from the resident models"


def test_hourly_trend_sits_above_the_heatmap():
    assert "heat-strip" in USAGE
    assert "hourlyTotals()" in USAGE
    assert "usage.trend" in EN
    assert USAGE.index("heat-strip") < USAGE.index("data.heatmap"), "the trend reads before the grid"
    assert "hourlyBarStyle" in USAGE_JS


def test_status_tab_helpers_exist_and_are_pure():
    for helper in ("formatUptime", "unloadAllModels"):
        assert helper in DASHBOARD_JS
    # unloadAllModels must reuse the per-model endpoint rather than invent one:
    # the task scope is front-end only.
    body = DASHBOARD_JS[DASHBOARD_JS.index("async unloadAllModels()"):][:600]
    assert "this.unloadModel(model.id)" in body
    assert "/api/" not in body, "no new endpoint"
