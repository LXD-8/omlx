// Log line parsing for the Logs screen.
//
// The server writes `%(asctime)s - %(name)s - %(levelname)s - [%(request_id)s] - %(message)s`;
// a traceback or a parameter dump continues on following lines that carry no
// timestamp. Reading that as one raw string is what made the screen hard to
// scan, so the screen works on records instead: one entry per header line with
// its continuation lines attached, a level with its own colour, and the module
// kept separate from the message.
//
// Pure value types and pure functions: no AppKit, no SwiftUI, no I/O, so the
// contract is testable on its own (see LogsScreenTests).

import Foundation

/// The severities the server can emit, in increasing order.
enum LogLevel: String, CaseIterable, Sendable {
    case trace = "TRACE"
    case debug = "DEBUG"
    case info = "INFO"
    case warning = "WARNING"
    case error = "ERROR"
    case critical = "CRITICAL"
    case other = ""

    /// Short label for the level column. `other` is a record whose header could
    /// not be parsed (a wrapped fragment, say).
    var label: String {
        switch self {
        case .trace: "TRC"
        case .debug: "DBG"
        case .info: "INF"
        case .warning: "WRN"
        case .error: "ERR"
        case .critical: "CRT"
        case .other: "—"
        }
    }

    var rank: Int {
        switch self {
        case .trace: 0
        case .debug: 1
        case .info: 2
        case .warning: 3
        case .error: 4
        case .critical: 5
        case .other: -1
        }
    }
}

/// One log entry: the header line plus any continuation lines.
struct LogRecord: Identifiable, Sendable {
    let id: Int
    let time: String
    let level: LogLevel
    let module: String
    let message: String
    /// Continuation lines (tracebacks, parameter dumps), already trimmed.
    let continuation: [String]
    let requestID: String

    var isHeader: Bool { level != .other }

    /// The message a row shows, continuation included, for the detail pane.
    var fullMessage: String {
        continuation.isEmpty ? message : ([message] + continuation).joined(separator: "\n")
    }

    /// The continuation lines the screen draws, capped (see `LogRenderLimits`).
    var renderedContinuation: [String] {
        Array(continuation.prefix(LogRenderLimits.continuationLines))
    }

    /// Continuation lines the cap leaves out; 0 when the record is short enough.
    var hiddenContinuationLines: Int {
        max(0, continuation.count - LogRenderLimits.continuationLines)
    }

    /// What the detail card draws: the header line plus the capped continuation.
    var renderedFullMessage: String {
        continuation.isEmpty ? message : ([message] + renderedContinuation).joined(separator: "\n")
    }

    /// The continuation lines a row draws when expanded in place.
    var renderedInlineContinuation: [String] {
        Array(continuation.prefix(LogRenderLimits.inlineContinuationLines))
    }

    /// Continuation lines hidden behind `renderedInlineContinuation`.
    var hiddenInlineContinuationLines: Int {
        max(0, continuation.count - LogRenderLimits.inlineContinuationLines)
    }
}

/// How much of a record the screen lays out at once. A record can carry tens of
/// thousands of continuation lines (a dumped parameter list, a traceback with a
/// frame per layer) and a repeated line can have as many occurrences; drawing
/// every line and every occurrence in one pass is what froze the screen. The
/// numbers live next to the parsing so the row and the detail card cannot drift
/// apart, and the whole record stays available: `fullMessage` is untouched and
/// the screen's Copy puts the log text on the pasteboard.
enum LogRenderLimits {
    /// Continuation lines the detail card draws (they scroll inside its box).
    static let continuationLines = 200
    /// Occurrences listed behind a row's ×N badge.
    static let occurrences = 200
    /// Continuation lines a *row* draws when it is expanded in place. The card is
    /// where a whole traceback belongs; a row that drew one made the list a
    /// single 600pt row with nothing else in view, so the row shows the first
    /// few lines and counts the rest behind the same "≡ N more lines" note.
    static let inlineContinuationLines = 4
}

/// One occurrence of a repeated record: when it happened and which request it
/// belonged to. The web console shows the same list behind a row's ×N badge.
struct LogOccurrence: Sendable, Equatable, Identifiable {
    let time: String
    let requestID: String
    var id: String { time + "#" + requestID }
}

/// One row of the list. A row is usually a single record; consecutive records
/// that repeat — same level, module and message — become one row with a count,
/// which is what keeps a polling loop from burying everything else.
struct LogRow: Identifiable, Sendable {
    let record: LogRecord
    let occurrences: [LogOccurrence]

    var id: Int { record.id }
    var count: Int { occurrences.count }
    var isRepeated: Bool { count > 1 }

    /// The occurrences the detail card lists, capped (see `LogRenderLimits`).
    var renderedOccurrences: [LogOccurrence] {
        Array(occurrences.prefix(LogRenderLimits.occurrences))
    }

    /// Occurrences the cap leaves out; 0 when the group is short enough.
    var hiddenOccurrences: Int {
        max(0, occurrences.count - LogRenderLimits.occurrences)
    }
}

enum LogRows {
    /// Runs of identical records collapse from `WARNING` up; `INFO` and below
    /// are the traffic of a busy server and stay one row each. A record the
    /// level filter hides ends a run, because what is left is not consecutive.
    static let aggregateFrom: LogLevel = .warning

    static func aggregate(_ records: [LogRecord], minLevel: LogLevel) -> [LogRow] {
        var rows: [LogRow] = []
        var current: LogRecord?
        var times: [LogOccurrence] = []

        func closeRun() {
            guard let first = current else { return }
            rows.append(LogRow(record: first, occurrences: times))
        }

        for record in records where record.isHeader {
            guard record.level.rank >= minLevel.rank else {
                // A hidden record ends the run: what remains is not consecutive.
                closeRun()
                current = nil
                continue
            }
            if let run = current,
               run.level.rank >= aggregateFrom.rank,
               run.level == record.level,
               run.module == record.module,
               run.message == record.message {
                times.append(LogOccurrence(time: record.time, requestID: record.requestID))
                continue
            }
            closeRun()
            current = record
            times = [LogOccurrence(time: record.time, requestID: record.requestID)]
        }
        closeRun()
        return rows
    }
}

enum LogParser {
    /// `2026-09-21 00:56:04,543 - omlx.server - WARNING - [-] - …`
    private static let headerPattern = try! NSRegularExpression(
        pattern: #"^(\d{4}-\d{2}-\d{2} [\d:,]+) - ([^-]+?) - ([A-Z]+) - \[([^\]]*)\] - (.*)$"#
    )

    /// One pass over the text, with the open record's continuation lines
    /// collected in an array and handed over when the record closes. Appending
    /// to `records.last.continuation` instead would copy every line collected so
    /// far on every line of a 20,000-line parameter dump — quadratic, and the
    /// screen hung on the refresh that carried one.
    static func parse(_ text: String, startingAt firstID: Int = 0) -> [LogRecord] {
        var records: [LogRecord] = []
        var id = firstID
        // The record being read: its header fields plus the lines so far.
        var open: (id: Int, time: String, level: LogLevel, module: String,
                   message: String, requestID: String)?
        var continuation: [String] = []

        func closeOpen() {
            guard let record = open else { return }
            records.append(LogRecord(id: record.id, time: record.time, level: record.level,
                                     module: record.module, message: record.message,
                                     continuation: continuation, requestID: record.requestID))
            open = nil
            continuation = []
        }

        for rawLine in text.split(separator: "\n", omittingEmptySubsequences: false) {
            let line = String(rawLine)
            if let match = header(line) {
                closeOpen()
                open = (id, match.time, match.level, match.module, match.message, match.requestID)
                id += 1
            } else if !line.trimmingCharacters(in: .whitespaces).isEmpty {
                // A continuation line belongs to the record above it; a window
                // that starts mid-record has none, and drops the fragment.
                if open != nil { continuation.append(line) }
            }
        }
        closeOpen()
        return records
    }

    private static func header(_ line: String) -> (time: String, level: LogLevel, module: String,
                                                   message: String, requestID: String)? {
        let range = NSRange(line.startIndex..., in: line)
        guard let match = headerPattern.firstMatch(in: line, range: range),
              let timeRange = Range(match.range(at: 1), in: line),
              let moduleRange = Range(match.range(at: 2), in: line),
              let levelRange = Range(match.range(at: 3), in: line),
              let requestRange = Range(match.range(at: 4), in: line),
              let messageRange = Range(match.range(at: 5), in: line)
        else { return nil }
        let levelText = String(line[levelRange]).uppercased()
        return (String(line[timeRange]),
                LogLevel(rawValue: levelText) ?? .other,
                String(line[moduleRange]).trimmingCharacters(in: .whitespaces),
                String(line[messageRange]),
                String(line[requestRange]))
    }
}
