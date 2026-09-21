// The Logs screen reads records, not raw text: these pin the parse and the
// aggregation the whole screen rests on. Same shape as the server writes
// (`asctime - name - LEVEL - [request_id] - message`, continuation lines
// without a stamp) and the same levels the web console's viewer knows.

import AppKit
import SwiftUI
import XCTest
@testable import oMLX

final class LogRecordsTests: XCTestCase {
    private let sample = """
    2026-09-21 00:56:04,543 - omlx.server - WARNING - [-] - Responses API streaming prefill rejected: Request aborted
    2026-09-21 00:56:04,544 - omlx.scheduler - INFO - [abc123] - Request queued
    model.encoder.vision_tower.layers.0.input_layernorm.weight,
    model.encoder.vision_tower.layers.0.mlp.down_proj.linear.weight,
    2026-09-21 00:58:38,085 - omlx.engine_core - ERROR - [-] - Hard memory pressure
    """

    func testParseSplitsHeaderFields() {
        let records = LogParser.parse(sample)
        XCTAssertEqual(records.count, 3)
        let first = records[0]
        XCTAssertEqual(first.time, "2026-09-21 00:56:04,543")
        XCTAssertEqual(first.module, "omlx.server")
        XCTAssertEqual(first.level, .warning)
        XCTAssertEqual(first.requestID, "-")
        XCTAssertTrue(first.message.hasPrefix("Responses API streaming prefill rejected"))
    }

    func testContinuationLinesAttachToTheirRecord() {
        let records = LogParser.parse(sample)
        let second = records[1]
        XCTAssertEqual(second.level, .info)
        XCTAssertEqual(second.requestID, "abc123")
        XCTAssertEqual(second.continuation.count, 2, "the two parameter lines belong to the record above them")
        XCTAssertTrue(second.fullMessage.contains("input_layernorm.weight"))
    }

    func testLevelsKeepTheirOrder() {
        XCTAssertLessThan(LogLevel.trace.rank, LogLevel.info.rank)
        XCTAssertLessThan(LogLevel.warning.rank, LogLevel.error.rank)
        XCTAssertLessThan(LogLevel.error.rank, LogLevel.critical.rank)
        XCTAssertEqual(LogLevel(rawValue: "WARNING"), .warning)
    }

    /// A refresh parses the whole tail again, so the parse has to be one pass.
    /// It used to rewrite the open record's continuation array for every
    /// continuation line — quadratic, and a 40,000-line parameter dump took
    /// 3.5 s of the main thread (measured) while the screen sat there.
    func testALongParameterDumpParsesInOnePass() {
        var text = "2026-09-21 00:00:00,000 - omlx.engine_core - WARNING - [-] - dumped parameters\n"
        for index in 0..<40_000 {
            text += "model.encoder.layers.\(index).self_attn.q_proj.linear.weight,\n"
        }
        let started = Date()
        let records = LogParser.parse(text)
        let elapsed = Date().timeIntervalSince(started)
        XCTAssertEqual(records.count, 1)
        XCTAssertEqual(records[0].continuation.count, 40_000, "every line is kept")
        // 0.04 s with the single pass; the bound is loose enough for a slow
        // machine and tight enough to fail if the copying comes back.
        XCTAssertLessThan(elapsed, 1.5, "40,000 continuation lines took \(elapsed)s")
    }

    /// The screen draws a bounded number of continuation lines and says how many
    /// are behind the bound; the record itself, and Copy, keep them all.
    func testALongRecordIsDrawnCappedAndCounted() {
        var text = "2026-09-21 00:00:00,000 - omlx.server - WARNING - [-] - dumped parameters\n"
        for index in 0..<5_000 { text += "line \(index)\n" }
        let record = LogParser.parse(text)[0]

        XCTAssertEqual(record.continuation.count, 5_000, "the parsed record is whole")
        XCTAssertEqual(record.renderedContinuation.count, LogRenderLimits.continuationLines)
        XCTAssertEqual(record.hiddenContinuationLines, 5_000 - LogRenderLimits.continuationLines)
        XCTAssertTrue(record.renderedFullMessage.contains("line \(LogRenderLimits.continuationLines - 1)"))
        XCTAssertFalse(record.renderedFullMessage.contains("line 4999"), "past the cap is not laid out")
        XCTAssertTrue(record.fullMessage.contains("line 4999"), "but it is still there for Copy")
    }

    func testAShortRecordIsNotTruncated() {
        let record = LogParser.parse(sample)[1]
        XCTAssertEqual(record.hiddenContinuationLines, 0)
        XCTAssertEqual(record.renderedContinuation, record.continuation)
        XCTAssertEqual(record.renderedFullMessage, record.fullMessage)
    }

    /// One row per occurrence froze the screen: 20,000 of them cost 2.7 s of
    /// layout and a 360,000 pt column (measured). The list is windowed, the
    /// count is not.
    func testTheOccurrenceListIsWindowedAndCounted() {
        let text = (0..<500).map { index in
            String(format: "2026-09-21 00:%02d:00,000 - omlx.engine_pool - WARNING - [-] - pinned model not found",
                   index % 60)
        }.joined(separator: "\n")
        let row = LogRows.aggregate(LogParser.parse(text), minLevel: .warning)[0]

        XCTAssertEqual(row.count, 500, "the badge counts every occurrence")
        XCTAssertEqual(row.renderedOccurrences.count, LogRenderLimits.occurrences)
        XCTAssertEqual(row.hiddenOccurrences, 500 - LogRenderLimits.occurrences)
        XCTAssertEqual(row.renderedOccurrences.first?.time, "2026-09-21 00:00:00,000")
    }

    func testUnknownLevelIsKeptButMarked() {
        let records = LogParser.parse("2026-09-21 00:00:00,000 - omlx.test - NOTICE - [-] - hello")
        XCTAssertEqual(records.count, 1)
        XCTAssertEqual(records[0].level, .other)
        XCTAssertFalse(records[0].isHeader)
        XCTAssertEqual(records[0].label, "—")
    }

    func testEmptyInputYieldsNoRecords() {
        XCTAssertTrue(LogParser.parse("").isEmpty)
    }

    // MARK: - Aggregation (the row list the screen renders)

    func testIdenticalConsecutiveWarningsBecomeOneRow() {
        let text = """
        2026-09-21 00:00:00,000 - omlx.server - WARNING - [a] - pinned model not found
        2026-09-21 00:05:00,000 - omlx.server - WARNING - [b] - pinned model not found
        2026-09-21 00:10:00,000 - omlx.server - WARNING - [c] - pinned model not found
        """
        let rows = LogRows.aggregate(LogParser.parse(text), minLevel: .trace)
        XCTAssertEqual(rows.count, 1)
        XCTAssertEqual(rows[0].count, 3)
        XCTAssertTrue(rows[0].isRepeated)
        XCTAssertEqual(rows[0].occurrences.map(\.time),
                       ["2026-09-21 00:00:00,000", "2026-09-21 00:05:00,000", "2026-09-21 00:10:00,000"])
        XCTAssertEqual(rows[0].occurrences.map(\.requestID), ["a", "b", "c"])
    }

    func testOnlyWarningAndAboveAggregate() {
        let text = """
        2026-09-21 00:00:00,000 - omlx.server - INFO - [-] - request queued
        2026-09-21 00:01:00,000 - omlx.server - INFO - [-] - request queued
        """
        let rows = LogRows.aggregate(LogParser.parse(text), minLevel: .trace)
        XCTAssertEqual(rows.count, 2, "INFO stays one row each: it is the traffic of a busy server")
        XCTAssertEqual(rows[0].count, 1)
    }

    func testADifferentModuleOrMessageEndsTheRun() {
        let text = """
        2026-09-21 00:00:00,000 - omlx.server - WARNING - [-] - pinned model not found
        2026-09-21 00:01:00,000 - omlx.engine - WARNING - [-] - pinned model not found
        2026-09-21 00:02:00,000 - omlx.server - WARNING - [-] - a different warning
        2026-09-21 00:03:00,000 - omlx.server - ERROR - [-] - pinned model not found
        """
        let rows = LogRows.aggregate(LogParser.parse(text), minLevel: .trace)
        XCTAssertEqual(rows.count, 4)
        XCTAssertEqual(rows.map(\.count), [1, 1, 1, 1])
    }

    func testAHiddenRecordEndsTheRun() {
        let text = """
        2026-09-21 00:00:00,000 - omlx.server - WARNING - [-] - pinned model not found
        2026-09-21 00:01:00,000 - omlx.scheduler - INFO - [-] - unrelated
        2026-09-21 00:02:00,000 - omlx.server - WARNING - [-] - pinned model not found
        """
        let rows = LogRows.aggregate(LogParser.parse(text), minLevel: .warning)
        XCTAssertEqual(rows.count, 2, "what the filter hides is not consecutive any more")
        XCTAssertEqual(rows.map(\.count), [1, 1])
    }

    func testTheLevelFilterAlsoDrivesTheRows() {
        let text = """
        2026-09-21 00:00:00,000 - omlx.scheduler - INFO - [-] - queued
        2026-09-21 00:01:00,000 - omlx.engine_core - ERROR - [-] - hard memory pressure
        """
        let records = LogParser.parse(text)
        XCTAssertEqual(LogRows.aggregate(records, minLevel: .info).count, 2)
        XCTAssertEqual(LogRows.aggregate(records, minLevel: .error).count, 1)
        XCTAssertEqual(LogRows.aggregate(records, minLevel: .error)[0].record.level, .error)
    }
    func testARowDrawsOnlyTheFirstContinuationLines() {
        // A traceback with many frames used to be drawn in full inside its row,
        // which made one row as tall as the pane. The row keeps the first few
        // lines and counts the rest; the detail card is where the whole record
        // belongs, and `renderedFullMessage` still holds every line.
        let text = """
        2026-09-22 00:00:00,000 - omlx.engine - ERROR - [r] - boom
        line one
        line two
        line three
        line four
        line five
        line six
        """
        let record = LogParser.parse(text)[0]
        XCTAssertEqual(record.continuation.count, 6)
        XCTAssertEqual(record.renderedInlineContinuation.count, LogRenderLimits.inlineContinuationLines)
        XCTAssertEqual(record.hiddenInlineContinuationLines, 6 - LogRenderLimits.inlineContinuationLines)
        XCTAssertEqual(record.renderedFullMessage.split(separator: "\n").count, 7, "the card keeps the record whole")
    }
}

private extension LogRecord {
    var label: String { level.label }
}

// MARK: - Level colours

/// Six levels, six colours, in both appearances. The web console paints the
/// same six (`logLevelTone` in `omlx/admin/static/js/dashboard.js`), so this
/// also pins the pair: a level that shares a colour with another level — or a
/// surface that paints a level differently from the other — is the bug these
/// tests exist for.
final class LogPaletteTests: XCTestCase {

    /// The six the parser ranks; `other` is a record whose header did not parse,
    /// and it deliberately reads like the quietest level.
    private let ranked: [LogLevel] = [.trace, .debug, .info, .warning, .error, .critical]

    private func components(_ color: Color) -> [Double] {
        guard let ns = NSColor(color).usingColorSpace(.sRGB) else { return [] }
        return [ns.redComponent, ns.greenComponent, ns.blueComponent].map { channel in
            (Double(channel) * 1000).rounded() / 1000
        }
    }

    func testEveryLevelHasItsOwnColour() {
        for theme in [OMLXTheme.light, OMLXTheme.dark] {
            let seen = ranked.map { components(LogPalette.color($0, theme: theme)) }
            for (level, value) in zip(ranked, seen) {
                XCTAssertEqual(value.count, 3, "\(level) did not resolve to sRGB")
            }
            XCTAssertEqual(
                Set(seen.map { "\($0)" }).count, ranked.count,
                "two levels share a colour in \(theme.isDark ? "dark" : "light") mode: \(seen)"
            )
        }
    }

    func testTheSeverityOrderUsesTheAgreedColours() {
        let theme = OMLXTheme.light
        XCTAssertEqual(components(LogPalette.color(.critical, theme: theme)), components(theme.purpleDot))
        XCTAssertEqual(components(LogPalette.color(.error, theme: theme)), components(theme.redDot))
        XCTAssertEqual(components(LogPalette.color(.warning, theme: theme)), components(theme.amberDot))
        XCTAssertEqual(components(LogPalette.color(.info, theme: theme)), components(theme.blueDot))
        XCTAssertEqual(components(LogPalette.color(.debug, theme: theme)), components(theme.tealDot))
        XCTAssertEqual(components(LogPalette.color(.trace, theme: theme)), components(theme.textTertiary))
    }

    func testTheUnknownLevelIsQuietToo() {
        let theme = OMLXTheme.light
        XCTAssertEqual(components(LogPalette.color(.other, theme: theme)),
                       components(LogPalette.color(.trace, theme: theme)))
    }
}
