import SwiftUI

@MainActor
@Observable
final class LogsScreenVM {
    var lines: Int = 100
    var selectedFile: String = ""
    var logText: String = ""
    /// Parsed once per refresh: the screen renders records, not the raw text.
    private(set) var records: [LogRecord] = []
    /// Lowest level the list shows. `trace` keeps everything. The rail is the
    /// list's own filter, so a change re-aggregates it.
    var minLevel: LogLevel = .info { didSet { aggregate() } }
    /// The row whose occurrences are open in the detail card, if any.
    var selectedRowID: Int?
    /// Follow the tail: when it is on, a refresh scrolls to the newest row.
    var autoScroll: Bool = true

    /// The list the screen renders: identical consecutive records are one row.
    /// Aggregated once per refresh (and once per filter change) rather than on
    /// every read: the body read it several times per draw, and a 20,000-line
    /// refresh is 20,000 records to walk each time.
    private(set) var rows: [LogRow] = []
    var selectedRow: LogRow? { rows.first { $0.id == selectedRowID } }
    var availableFiles: [String] = []
    var lastError: String?
    private(set) var isLoading: Bool = false
    private(set) var totalLines: Int = 0

    private func reparse() {
        records = LogParser.parse(logText)
        aggregate()
        // A selection survives a refresh only while its record is still here.
        if let id = selectedRowID, !rows.contains(where: { $0.id == id }) {
            selectedRowID = nil
        }
    }

    private func aggregate() {
        rows = LogRows.aggregate(records, minLevel: minLevel)
    }
    private(set) var refreshKey: Int = 0

    @ObservationIgnored
    private weak var client: OMLXClient?
    @ObservationIgnored
    private var pollTask: Task<Void, Never>?

    var subtitle: String {
        guard !logText.isEmpty else { return "" }
        return String(localized: "logs.subtitle.line_count",
                      defaultValue: "Lines: \(totalLines.formatted())",
                      comment: "Section header subtitle on the Logs screen; placeholder is the total number of log lines")
    }

    var fileOptions: [(String, String)] {
        availableFiles.map { name in
            let label = name == "server.log"
                ? String(localized: "logs.file.current",
                         defaultValue: "server.log (current)",
                         comment: "Popup label for the active server log file in the Logs screen file selector")
                : name
            return (name, label)
        }
    }

    func start(client: OMLXClient) async {
        self.client = client
        pollTask?.cancel()
        pollTask = Task { [weak self] in
            while !Task.isCancelled {
                guard let self else { return }
                await self.tick()
                try? await Task.sleep(for: .seconds(5))
            }
        }
    }

    func stop() {
        pollTask?.cancel()
        pollTask = nil
    }

    func reload() async {
        await tick()
    }

    func bumpRefreshKey() {
        refreshKey &+= 1
    }

    func select(_ row: LogRow) {
        selectedRowID = selectedRowID == row.id ? nil : row.id
    }

    func clearSelection() {
        selectedRowID = nil
    }

    func copyToPasteboard() {
        let pb = NSPasteboard.general
        pb.clearContents()
        pb.setString(logText, forType: .string)
    }

    private func tick() async {
        guard let client else { return }
        isLoading = true
        defer { isLoading = false }

        let file = selectedFile.isEmpty ? nil : selectedFile
        do {
            let dto = try await client.getLogs(lines: lines, file: file)
            self.logText = dto.logs
            self.reparse()
            self.totalLines = dto.totalLines
            self.availableFiles = dto.availableFiles
            if selectedFile.isEmpty {
                self.selectedFile = dto.logFile
            }
            self.lastError = nil
        } catch {
            self.lastError = error.omlxDescription
        }
    }

}
