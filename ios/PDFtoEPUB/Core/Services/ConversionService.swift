import Foundation

/// Drives one conversion job: upload, then poll until terminal, then fetch the
/// result. Polling backs off so a 500-page book doesn't hammer the server.
actor ConversionService {
    private let client: APIClient

    init(client: APIClient) {
        self.client = client
    }

    /// What the server accepts. Called before the upload so an impossible
    /// job, or an unreachable server, is reported in seconds.
    func capabilities() async throws -> BackendCapabilities {
        try await client.fetchCapabilities()
    }

    /// Recognise the document's scanned pages here, then upload the text with it.
    ///
    /// The server charges ~110 seconds a page for OCR on its free tier and this
    /// device charges about two, so for any scanned book this is the difference
    /// between a conversion that finishes and one that times out. A document
    /// with a text layer needs none of it and skips straight to the upload.
    func start(
        document: SelectedDocument,
        mode: ConversionMode,
        onOCRProgress: @Sendable @escaping (DocumentOCR.Progress) -> Void = { _ in }
    ) async throws -> String {
        let ocrFile = try? await Self.recogniseLocally(
            document: document, onProgress: onOCRProgress
        )
        defer { if let ocrFile { try? FileManager.default.removeItem(at: ocrFile) } }
        let created = try await client.createConversion(
            fileURL: document.url, mode: mode, clientOCR: ocrFile
        )
        return created.id
    }

    /// Returns a temp file holding the payload, or nil when there is nothing to
    /// send. Written to disk so the upload can stream it rather than hold a
    /// long book's worth of boxes in memory beside the PDF.
    private static func recogniseLocally(
        document: SelectedDocument,
        onProgress: @Sendable @escaping (DocumentOCR.Progress) -> Void
    ) async throws -> URL? {
        let scoped = document.url.startAccessingSecurityScopedResource()
        defer { if scoped { document.url.stopAccessingSecurityScopedResource() } }

        guard
            let payload = try await DocumentOCR().recognise(
                documentAt: document.url, onProgress: onProgress
            )
        else { return nil }

        let url = FileManager.default.temporaryDirectory
            .appendingPathComponent("client-ocr-\(UUID().uuidString).json")
        try payload.jsonData().write(to: url, options: .atomic)
        return url
    }

    /// Polls progress until the job reaches a terminal state, invoking
    /// `onProgress` for each update. Throws `APIError.server` carrying the
    /// backend's error code/message if the job fails.
    func awaitCompletion(
        id: String,
        onProgress: @Sendable @escaping (ConversionProgress) -> Void
    ) async throws -> ConversionResult {
        var consecutiveTransientFailures = 0

        while true {
            try Task.checkCancellation()

            let progress: ConversionProgress
            do {
                progress = try await client.fetchProgress(id: id)
                consecutiveTransientFailures = 0
            } catch let error as APIError where error.isTransient {
                // A dropped connection mid-job shouldn't lose the job: the work
                // continues server-side, so keep polling for a while before
                // surfacing the failure (spec section 41). Only transport
                // failures land here — a job the backend reports as FAILED is
                // terminal and is thrown below, outside this retry path.
                consecutiveTransientFailures += 1
                if consecutiveTransientFailures > Self.maxTransientFailures {
                    throw error
                }
                // Polling again a second later is what a throttle asked us
                // not to do; wait as long as it said, within reason.
                try await Task.sleep(for: .seconds(Self.backoff(for: error)))
                continue
            } catch APIError.server(let code, _) where code == "http_404" {
                // The job is gone mid-conversion. The server keeps jobs on a
                // disk a restart wipes, so that is what this nearly always is;
                // "This conversion job no longer exists" said so in words a
                // reader could do nothing with.
                throw Self.jobLost
            }

            onProgress(progress)

            if progress.status == .completed {
                return try await client.fetchResult(id: id)
            }
            if progress.status == .failed {
                let summary = try await client.fetchSummary(id: id)
                throw APIError.server(
                    code: summary.errorCode ?? "conversion_failed",
                    message: summary.errorMessage ?? "We couldn't convert this document."
                )
            }

            try await Task.sleep(for: .seconds(Self.pollIntervalSeconds))
        }
    }

    /// The book is finished by the time this runs, so a busy server is waited
    /// out rather than turned into an error that throws the conversion away.
    func download(id: String, filename: String) async throws -> URL {
        var attempt = 0
        while true {
            do {
                return try await client.downloadEPUB(id: id, suggestedFilename: filename)
            } catch let error as APIError {
                guard case .busy = error, attempt < 3 else { throw error }
                attempt += 1
                try await Task.sleep(for: .seconds(Self.backoff(for: error)))
            }
        }
    }

    static func backoff(for error: APIError) -> Double {
        if case .busy(let retryAfter, _) = error {
            return min(Double(max(retryAfter ?? 5, 1)), 30)
        }
        return pollIntervalSeconds
    }

    func cleanUp(id: String) async {
        try? await client.deleteConversion(id: id)
    }

    static let pollIntervalSeconds = 1.0
    private static let maxTransientFailures = 10

    private static let jobLost = APIError.server(
        code: "job_lost",
        message: """
            The server stopped working on this book before it finished, usually \
            because it restarted. Try again. Your original PDF was not modified.
            """
    )
}
