import Foundation

/// Drives one conversion job: upload, then poll until terminal, then fetch the
/// result. Polling backs off so a 500-page book doesn't hammer the server.
actor ConversionService {
    private let client: APIClient

    init(client: APIClient) {
        self.client = client
    }

    func start(document: SelectedDocument, mode: ConversionMode) async throws -> String {
        let created = try await client.createConversion(fileURL: document.url, mode: mode)
        return created.id
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

            do {
                let progress = try await client.fetchProgress(id: id)
                consecutiveTransientFailures = 0
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
            } catch let error as APIError where error.isRetryable && error != .cancelled {
                // A dropped connection mid-job shouldn't lose the job: the work
                // continues server-side, so keep polling for a while before
                // surfacing the failure (spec section 41).
                consecutiveTransientFailures += 1
                if consecutiveTransientFailures > Self.maxTransientFailures {
                    throw error
                }
            }

            try await Task.sleep(for: .seconds(Self.pollIntervalSeconds))
        }
    }

    func download(id: String, filename: String) async throws -> URL {
        try await client.downloadEPUB(id: id, suggestedFilename: filename)
    }

    func cleanUp(id: String) async {
        try? await client.deleteConversion(id: id)
    }

    private static let pollIntervalSeconds = 1.0
    private static let maxTransientFailures = 10
}
