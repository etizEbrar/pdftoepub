import Foundation
import Observation

@Observable
@MainActor
final class ConversionViewModel {
    enum Phase: Equatable {
        case idle
        case documentSelected(SelectedDocument)
        case converting(SelectedDocument)
        case completed(SelectedDocument, QualityReport, epubURL: URL)
        case failed(ConversionFailure)
    }

    struct ConversionFailure: Equatable {
        let code: String
        let message: String
        let isRetryable: Bool
    }

    private(set) var phase: Phase = .idle
    private(set) var progress: ConversionProgress?
    var selectedMode: ConversionMode

    private let settings: AppSettings
    private let makeClient: (URL) -> APIClient
    private var currentJobID: String?
    private var conversionTask: Task<Void, Never>?

    init(
        settings: AppSettings,
        makeClient: @escaping (URL) -> APIClient = { LiveAPIClient(baseURL: $0) }
    ) {
        self.settings = settings
        self.makeClient = makeClient
        self.selectedMode = settings.preferredMode
    }

    var selectedDocument: SelectedDocument? {
        switch phase {
        case .documentSelected(let doc), .converting(let doc), .completed(let doc, _, _):
            return doc
        case .idle, .failed:
            return nil
        }
    }

    var isConverting: Bool {
        if case .converting = phase { return true }
        return false
    }

    // MARK: - Document selection

    func selectDocument(at url: URL) {
        do {
            let document = try PDFInspector.inspect(url: url)
            phase = .documentSelected(document)
            progress = nil
        } catch {
            phase = .failed(
                ConversionFailure(
                    code: "invalid_pdf",
                    message: error.localizedDescription,
                    isRetryable: false
                )
            )
        }
    }

    func clearSelection() {
        conversionTask?.cancel()
        conversionTask = nil
        currentJobID = nil
        progress = nil
        phase = .idle
    }

    // MARK: - Conversion

    func startConversion() {
        guard let document = selectedDocument else { return }
        // Separate "you have not set this up yet" from "what you set up is
        // wrong" — the first is a normal first run, the second is a mistake to
        // correct. Both send the user to Settings rather than offering a retry
        // that would fail identically.
        guard let baseURL = settings.baseURL else {
            phase = .failed(
                ConversionFailure(
                    code: "backend_not_configured",
                    message: APIError.notConfigured.userMessage,
                    isRetryable: false
                )
            )
            return
        }
        if let issue = settings.addressIssue {
            phase = .failed(
                ConversionFailure(code: "invalid_url", message: issue.message, isRetryable: false)
            )
            return
        }
        // Check before uploading rather than after converting: failing at the
        // download step would throw away the whole conversion.
        if DiskSpace.isInsufficient(forSourceOfSize: Int64(document.byteCount)) {
            phase = .failed(
                ConversionFailure(
                    code: "insufficient_storage",
                    message: """
                        There isn't enough free space on this device to save the \
                        converted book. Free up some space and try again.
                        """,
                    isRetryable: false
                )
            )
            return
        }

        settings.preferredMode = selectedMode
        phase = .converting(document)
        progress = nil

        let service = ConversionService(client: makeClient(baseURL))
        let mode = selectedMode

        conversionTask = Task { [weak self] in
            guard let self else { return }
            do {
                let jobID = try await service.start(document: document, mode: mode)
                await MainActor.run { self.currentJobID = jobID }

                let result = try await service.awaitCompletion(id: jobID) { update in
                    Task { @MainActor [weak self] in self?.progress = update }
                }

                guard let report = result.qualityReport else {
                    throw APIError.decoding
                }

                let epubFilename = (document.filename as NSString).deletingPathExtension + ".epub"
                let epubURL = try await service.download(id: jobID, filename: epubFilename)

                // The book is on the device now, so the server has no further
                // reason to hold the user's document. The TTL sweep would get
                // there eventually; asking immediately means the window is
                // seconds rather than hours. Best-effort by design — a failure
                // here must not turn a finished conversion into an error.
                await service.cleanUp(id: jobID)

                await MainActor.run {
                    self.phase = .completed(document, report, epubURL: epubURL)
                }
            } catch is CancellationError {
                await MainActor.run { self.phase = .documentSelected(document) }
            } catch let error as APIError {
                await MainActor.run { self.phase = .failed(Self.failure(from: error)) }
            } catch {
                await MainActor.run {
                    self.phase = .failed(
                        ConversionFailure(
                            code: "unknown",
                            message: "Something went wrong. Your original PDF was not modified.",
                            isRetryable: true
                        )
                    )
                }
            }
        }
    }

    func cancelConversion() {
        conversionTask?.cancel()
        conversionTask = nil
        if let document = selectedDocument {
            phase = .documentSelected(document)
        } else {
            phase = .idle
        }
        progress = nil
    }

    func retry() {
        if let document = selectedDocument {
            phase = .documentSelected(document)
            startConversion()
        } else {
            phase = .idle
        }
    }

    /// Backend error codes that describe something about *this PDF* can't be
    /// fixed by trying the same file again — those offer "choose a different
    /// PDF" instead. Transport problems and server-side hiccups do offer retry.
    private static let nonRetryableCodes: Set<String> = [
        "encrypted_pdf", "corrupted_pdf", "unsupported_pdf", "invalid_pdf",
        "file_too_large", "unsupported_complexity", "invalid_url",
        "backend_not_configured", "host_not_found", "insufficient_storage"
    ]

    private static func failure(from error: APIError) -> ConversionFailure {
        let code: String
        switch error {
        case .server(let serverCode, _): code = serverCode
        case .invalidURL: code = "invalid_url"
        case .notConfigured: code = "backend_not_configured"
        case .hostNotFound: code = "host_not_found"
        case .offline: code = "offline"
        case .serverUnavailable: code = "server_unavailable"
        case .timedOut: code = "timeout"
        default: code = "network"
        }
        return ConversionFailure(
            code: code,
            message: error.userMessage,
            isRetryable: !nonRetryableCodes.contains(code)
        )
    }
}
