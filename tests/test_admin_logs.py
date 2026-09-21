# SPDX-License-Identifier: Apache-2.0
"""Structure of the Logs tab after the console refactor.

The tab used to be one dark ``<textarea>`` of raw text with a client-side
minimum-level filter. It is now a four-column viewer (time / level / module /
message) that keeps continuation lines with their record, collapses consecutive
identical warnings and errors behind a ×N counter, parses the memory-guard lines
into chips with the two remedies they suggest as inline actions, appends each
poll instead of rebuilding the list, and mounts only the rows near the viewport.

These are static assertions over the template and the scripts; the parser, the
aggregator and the windowing math are covered by tests/admin_logs.test.cjs.
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ADMIN = ROOT / "omlx" / "admin"
LOGS = (ADMIN / "templates" / "dashboard" / "_logs.html").read_text(encoding="utf-8")
SETTINGS = (ADMIN / "templates" / "dashboard" / "_settings.html").read_text(encoding="utf-8")
DASHBOARD = (ADMIN / "templates" / "dashboard.html").read_text(encoding="utf-8")
DASHBOARD_JS = (ADMIN / "static" / "js" / "dashboard.js").read_text(encoding="utf-8")
LOGS_JS = (ADMIN / "static" / "js" / "logs.js").read_text(encoding="utf-8")
COMPONENTS_CSS = (ADMIN / "static" / "css" / "components.css").read_text(encoding="utf-8")
TOKENS_CSS = (ADMIN / "static" / "css" / "tokens.css").read_text(encoding="utf-8")
EN = json.loads((ADMIN / "i18n" / "en.json").read_text(encoding="utf-8"))


def test_four_structured_columns():
    for key in ("logs.col.time", "logs.col.level", "logs.col.module", "logs.col.message"):
        assert f"t('{key}')" in LOGS
        assert key in EN
    # One grid aligns the header with the rows; the message column is the
    # flexible one.
    assert "log-grid" in LOGS
    assert "grid-template-columns" in COMPONENTS_CSS
    for name in (".log-head", ".log-row", ".log-viewport"):
        assert f"{name} {{" in COMPONENTS_CSS


def test_a_row_is_the_parsed_record():
    for field in ("row.time", "row.level", "row.module", "row.message"):
        assert field in LOGS
    assert "parseLogText" in LOGS_JS
    assert "continuation" in LOGS_JS, "continuation lines stay with their record"
    assert "requestId" in LOGS_JS


def test_the_raw_textarea_is_gone():
    assert "<textarea" not in LOGS
    assert "filteredLogContent" not in LOGS
    assert "filteredLogContent" not in DASHBOARD_JS


def test_level_badges_use_the_shared_palette():
    body = DASHBOARD_JS[DASHBOARD_JS.index("logLevelTone(level)") :][:400]
    assert "badge--red" in body
    assert "badge--orange" in body
    assert "badge--blue" in body
    assert "levelRank" in LOGS_JS, "the ranking comes from the parser module"


def test_consecutive_repeats_collapse_behind_a_counter():
    assert "aggregateLogRows" in LOGS_JS
    assert "AGGREGATE_FROM" in LOGS_JS, "only warnings and above collapse"
    assert "'×' + row.count" in LOGS
    assert "row.count > 1" in LOGS
    assert "logs.repeat_tooltip" in EN
    # Every occurrence stays reachable, with its own timestamp.
    assert "occurrences" in LOGS_JS
    assert "logSelectedRow.occurrences" in LOGS
    assert "logs.detail.occurrences" in EN


def test_memory_guard_chips_and_inline_actions():
    assert "memoryGuardFor" in LOGS_JS
    assert "memoryGuardChips" in LOGS_JS
    assert "logMemoryChips(row)" in LOGS
    assert "log-chips" in LOGS
    for chip in ("usage", "watermark", "ceiling"):
        assert f"logs.memory.{chip}" in LOGS or f"logs.memory.{chip}" in DASHBOARD_JS
        assert f"logs.memory.{chip}" in EN
    # The two remedies switch to Settings and scroll to the section that holds
    # the lever.
    assert "logs.action.raise_tier" in EN
    assert "logs.action.reduce_context" in EN
    assert "anchor: 'memory-guard'" in DASHBOARD_JS
    assert "anchor: 'context-window'" in DASHBOARD_JS
    assert "openLogAction(action.anchor)" in LOGS
    assert 'data-anchor="memory-guard"' in SETTINGS
    assert "setSettingsTab('global')" in DASHBOARD_JS
    assert "data-anchor=" in DASHBOARD_JS, "the fallback target is looked up by anchor"


def test_incremental_refresh_appends_instead_of_rebuilding():
    assert "mergeLogText" in LOGS_JS
    for helper in ("ingestLogText", "commitLogRecords", "dropLeadingLogRecords", "rebuildLogRows"):
        assert helper in DASHBOARD_JS
    # The rows that leave the top of the window must not drag the view with
    # them: the row under the offset is remembered across the poll.
    assert "logAnchor" in DASHBOARD_JS
    assert "restoreLogAnchor" in DASHBOARD_JS
    # The endpoint is untouched: same route, same parameters.
    assert "/admin/api/logs?" in DASHBOARD_JS
    assert "lines: this.logLines.toString()" in DASHBOARD_JS
    assert "fetch(" not in LOGS_JS, "the parser fetches nothing"
    # Auto-scroll survives and now drives the viewport.
    assert "logAutoScroll" in DASHBOARD_JS
    assert "scrollLogToBottom" in DASHBOARD_JS
    assert "logs.auto_scroll" in LOGS and "logs.auto_scroll" in EN


def test_virtual_scrolling_keeps_only_the_window_mounted():
    assert "visibleRange" in LOGS_JS
    assert "logWindow" in DASHBOARD_JS
    assert "visibleLogRows" in DASHBOARD_JS
    assert 'x-for="(row, i) in visibleLogRows"' in LOGS
    assert "translateY(" in LOGS and "logRowHeight" in LOGS
    assert "log-spacer" in LOGS
    assert ".log-spacer {" in COMPONENTS_CSS
    assert "--log-row-height" in TOKENS_CSS
    assert "height: var(--log-row-height)" in COMPONENTS_CSS, "uniform rows keep the window exact"
    for hook in ("onLogScroll", "measureLogViewport", "measureLogRowHeight"):
        assert hook in DASHBOARD_JS


def test_controls_are_the_six_that_were_here_on_shared_components():
    assert "{% call ui.card(" in LOGS
    assert "ui.button(" in LOGS
    assert "ui.segmented(" in LOGS
    assert "ui.empty_state(" in LOGS
    assert "ui.badge(" in LOGS
    for key in (
        "logs.lines_label",
        "logs.refresh_label",
        "logs.file_label",
        "logs.refresh_button",
        "logs.auto_scroll",
        "logs.level_label",
    ):
        assert key in LOGS
        assert key in EN
    assert "setLogMinLevel('{value}')" in LOGS
    assert "restartLogRefresh()" in LOGS
    assert "changeLogFile()" in LOGS


def test_logs_js_loads_before_the_dashboard_script():
    assert "js/logs.js" in DASHBOARD
    assert DASHBOARD.index("js/logs.js") < DASHBOARD.index("js/dashboard.js")
