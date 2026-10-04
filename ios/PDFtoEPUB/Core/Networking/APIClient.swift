import Foundation

/// Protocol-based so views/view models can be tested against a stub without a
/// live backend (see PDFtoEPUBTests/StubAPIClient.swift).
protocol APIClient: Sendable {
    func fetchCapabilities() async throws -> BackendCapabilities
    func createConversion(fileURL: URL, mode: ConversionMode) async throws -> ConversionCreatedResponse
    func fetchProgress(id: String) async throws -> ConversionProgress
    func fetchSummary(id: String) async throws -> ConversionSummary
    func fetchResult(id: String) async throws -> ConversionResult
    func downloadEPUB(id: String, suggestedFilename: String) async throws -> URL
    func deleteConversion(id: String) async throws
}

/// Timeouts for talking to the backend.
///
/// `URLSession.shared` carries a `timeoutIntervalForResource` of seven days.
/// A connection that stalls without dropping — a sleeping free-tier host, a
/// server that closes the read side mid-upload, a flaky mobile link —
/// therefore never failed, and the app sat on "Waking the conversion server"
/// indefinitely with no way out but force-quitting. Every request the app
/// makes is now bounded, so a stall becomes an error the user can act on.
enum BackendTimeouts {
    /// Longest silence tolerated *within* a transfer. Reset by every byte, so
    /// this bounds a dead connection, not a slow one.
    static let betweenBytes: TimeInterval = 90
    /// Longest any single request may take end to end. The upload returns as
    /// soon as the job is queued and progress polls are tiny, so the binding
    /// case is downloading a finished book over a slow link.
    static let wholeRequest: TimeInterval = 600

    static func makeSession() -> URLSession {
        let config = URLSessionConfiguration.default
        config.timeoutIntervalForRequest = betweenBytes
        config.timeoutIntervalForResource = wholeRequest
        // Fail now rather than parking the task until the network returns:
        // the user is watching a spinner and needs to be told.
        config.waitsForConnectivity = false
        return URLSession(configuration: config)
    }
}

final class LiveAPIClient: APIClient {
    private let baseURL: URL
    private let session: URLSession

    init(baseURL: URL, session: URLSession = BackendTimeouts.makeSession()) {
        self.baseURL = baseURL
        self.session = session
    }

    func fetchCapabilities() async throws -> BackendCapabilities {
        try await get(BackendCapabilities.self, path: "health")
    }

    private func endpoint(_ path: String) -> URL {
        baseURL.appendingPathComponent(path)
    }

    func createConversion(fileURL: URL, mode: ConversionMode) async throws -> ConversionCreatedResponse {
        let boundary = "Boundary-\(UUID().uuidString)"
        var request = URLRequest(url: endpoint("v1/conversions"))
        request.httpMethod = "POST"
        request.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")

        let needsScopedAccess = fileURL.startAccessingSecurityScopedResource()
        defer { if needsScopedAccess { fileURL.stopAccessingSecurityScopedResource() } }

        let bodyFileURL = try MultipartBodyWriter.writeBody(
            fileURL: fileURL,
            filename: fileURL.lastPathComponent,
            mode: mode,
            boundary: boundary
        )
        defer { try? FileManager.default.removeItem(at: bodyFileURL) }

        let (data, response) = try await performUpload(request: request, bodyFileURL: bodyFileURL)
        try Self.validate(response: response, data: data)
        return try Self.decode(ConversionCreatedResponse.self, from: data)
    }

    func fetchProgress(id: String) async throws -> ConversionProgress {
        try await get(ConversionProgress.self, path: "v1/conversions/\(id)/progress")
    }

    func fetchSummary(id: String) async throws -> ConversionSummary {
        try await get(ConversionSummary.self, path: "v1/conversions/\(id)")
    }

    func fetchResult(id: String) async throws -> ConversionResult {
        try await get(ConversionResult.self, path: "v1/conversions/\(id)/result")
    }

    func downloadEPUB(id: String, suggestedFilename: String) async throws -> URL {
        let request = URLRequest(url: endpoint("v1/conversions/\(id)/download"))
        let (tempURL, response) = try await performDownload(request: request)
        try Self.validate(response: response, data: nil)

        let destination = FileManager.default.temporaryDirectory
            .appendingPathComponent(suggestedFilename)
        try? FileManager.default.removeItem(at: destination)
        try FileManager.default.moveItem(at: tempURL, to: destination)
        return destination
    }

    func deleteConversion(id: String) async throws {
        var request = URLRequest(url: endpoint("v1/conversions/\(id)"))
        request.httpMethod = "DELETE"
        let (data, response) = try await performData(request: request)
        try Self.validate(response: response, data: data)
    }

    // MARK: - Transport

    private func get<T: Decodable>(_ type: T.Type, path: String) async throws -> T {
        let request = URLRequest(url: endpoint(path))
        let (data, response) = try await performData(request: request)
        try Self.validate(response: response, data: data)
        return try Self.decode(type, from: data)
    }

    private func performData(request: URLRequest) async throws -> (Data, URLResponse) {
        do {
            return try await session.data(for: request)
        } catch {
            throw Self.mapTransportError(error)
        }
    }

    private func performUpload(request: URLRequest, bodyFileURL: URL) async throws -> (Data, URLResponse) {
        do {
            return try await session.upload(for: request, fromFile: bodyFileURL)
        } catch {
            throw Self.mapTransportError(error)
        }
    }

    private func performDownload(request: URLRequest) async throws -> (URL, URLResponse) {
        do {
            return try await session.download(for: request)
        } catch {
            throw Self.mapTransportError(error)
        }
    }

    private static func mapTransportError(_ error: Error) -> APIError {
        if error is CancellationError { return .cancelled }
        let nsError = error as NSError
        guard nsError.domain == NSURLErrorDomain else { return .decoding }
        switch nsError.code {
        // Kept apart because the fix differs: reconnect, fix the address, or
        // start the server. Collapsing them into one "offline" message sends
        // people to check Wi-Fi when their server simply isn't running.
        case NSURLErrorNotConnectedToInternet, NSURLErrorNetworkConnectionLost,
             NSURLErrorInternationalRoamingOff, NSURLErrorDataNotAllowed:
            return .offline
        case NSURLErrorCannotFindHost, NSURLErrorDNSLookupFailed:
            return .hostNotFound
        case NSURLErrorCannotConnectToHost, NSURLErrorSecureConnectionFailed,
             NSURLErrorServerCertificateUntrusted, NSURLErrorAppTransportSecurityRequiresSecureConnection:
            return .serverUnavailable
        case NSURLErrorTimedOut:
            return .timedOut
        case NSURLErrorCancelled:
            return .cancelled
        default:
            return .unexpectedStatus(nsError.code)
        }
    }

    private static func validate(response: URLResponse, data: Data?) throws {
        guard let http = response as? HTTPURLResponse else { throw APIError.decoding }
        guard !(200..<300).contains(http.statusCode) else { return }

        if let data, let apiError = try? JSONDecoder().decode(APIErrorResponse.self, from: data) {
            throw APIError.server(code: apiError.code, message: apiError.message)
        }
        // FastAPI's HTTPException shape: {"detail": "..."}
        if let data,
           let detail = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any],
           let message = detail["detail"] as? String {
            throw APIError.server(code: "http_\(http.statusCode)", message: message)
        }
        throw APIError.unexpectedStatus(http.statusCode)
    }

    private static func decode<T: Decodable>(_ type: T.Type, from data: Data) throws -> T {
        do {
            return try JSONDecoder().decode(type, from: data)
        } catch {
            throw APIError.decoding
        }
    }
}
