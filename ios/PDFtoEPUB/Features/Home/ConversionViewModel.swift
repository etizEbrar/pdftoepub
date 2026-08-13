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
    private var currentJobID: String?
    private var conversionTask: Task<Void, Never>?

    init(settings: AppSettings) {
        self.settings = settings
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
        guard let baseURL = settings.baseURL else {
            phase = .failed(
                ConversionFailure(code: "invalid_url", message: APIError.invalidURL.userMessage, isRetryable: false)
            )
            return
        }

        settings.preferredMode = selectedMode
        phase = .converting(document)
        progress = nil

        let service = ConversionService(client: LiveAPIClient(baseURL: baseURL))
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

    private static func failure(from error: APIError) -> ConversionFailure {
        let code: String
        if case .server(let serverCode, _) = error {
            code = serverCode
        } else {
            code = "network"
        }
        return ConversionFailure(code: code, message: error.userMessage, isRetryable: error.isRetryable)
    }
}
