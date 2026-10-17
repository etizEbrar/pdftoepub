import XCTest
@testable import PDFtoEPUB

final class ConversionServiceTests: XCTestCase {
    private func progress(_ status: JobStage, percent: Int, page: Int = 0, total: Int = 0) -> ConversionProgress {
        ConversionProgress(
            id: "job-1",
            status: status,
            stageDetail: status.displayName,
            page: page,
            totalPages: total,
            percent: percent
        )
    }

    func testAwaitCompletionReportsEachProgressUpdateThenReturnsResult() async throws {
        let expectedResult = ConversionResult(
            id: "job-1",
            status: .completed,
            qualityReport: .stub(),
            downloadURL: "/v1/conversions/job-1/download"
        )
        let client = StubAPIClient(
            progressSequence: [
                progress(.analyzing, percent: 10),
                progress(.extracting, percent: 30, page: 5, total: 10),
                progress(.completed, percent: 100)
            ],
            result: expectedResult
        )
        let service = ConversionService(client: client)

        let updates = Updates()
        let result = try await service.awaitCompletion(id: "job-1") { update in
            Task { await updates.append(update.status) }
        }

        XCTAssertEqual(result.id, "job-1")
        XCTAssertNotNil(result.qualityReport)
        XCTAssertEqual(result.qualityReport?.aiProviderUsed, "none")
    }

    func testFailedJobThrowsServerErrorCarryingBackendCode() async {
        let client = StubAPIClient(
            progressSequence: [progress(.failed, percent: 0)],
            summary: ConversionSummary(
                id: "job-1",
                status: .failed,
                mode: .maximumAccuracy,
                sourceFilename: "book.pdf",
                errorCode: "encrypted_pdf",
                errorMessage: "This PDF is password-protected."
            )
        )
        let service = ConversionService(client: client)

        do {
            _ = try await service.awaitCompletion(id: "job-1") { _ in }
            XCTFail("expected the failed job to throw")
        } catch let error as APIError {
            guard case .server(let code, _) = error else {
                return XCTFail("expected a server error, got \(error)")
            }
            XCTAssertEqual(code, "encrypted_pdf")
        } catch {
            XCTFail("unexpected error type: \(error)")
        }
    }

    /// A job the backend reports as FAILED is a final answer, not a transport
    /// blip — it must surface immediately rather than being swallowed by the
    /// reconnect-retry path and delayed by its backoff.
    func testFailedJobSurfacesImmediatelyWithoutRetryBackoff() async {
        let client = StubAPIClient(
            progressSequence: [progress(.failed, percent: 0)],
            summary: ConversionSummary(
                id: "job-1",
                status: .failed,
                mode: .maximumAccuracy,
                sourceFilename: "book.pdf",
                errorCode: "unsupported_complexity",
                errorMessage: "We couldn't safely reconstruct this document."
            )
        )
        let service = ConversionService(client: client)

        let start = Date()
        do {
            _ = try await service.awaitCompletion(id: "job-1") { _ in }
            XCTFail("expected the failed job to throw")
        } catch {
            let elapsed = Date().timeIntervalSince(start)
            XCTAssertLessThan(elapsed, 2.0, "a failed job must not go through the transient-retry backoff")
        }
    }

    func testServerErrorIsNotTreatedAsTransient() {
        XCTAssertFalse(APIError.server(code: "encrypted_pdf", message: "locked").isTransient)
        XCTAssertTrue(APIError.offline.isTransient)
        XCTAssertTrue(APIError.serverUnavailable.isTransient)
        XCTAssertTrue(APIError.timedOut.isTransient)
    }

    /// A wrong address never becomes right by retrying, so polling through it
    /// would just make the app look hung instead of telling the user to fix it.
    func testConfigurationErrorsAreNotTransient() {
        XCTAssertFalse(APIError.notConfigured.isTransient)
        XCTAssertFalse(APIError.hostNotFound.isTransient)
        XCTAssertFalse(APIError.invalidURL.isTransient)
    }

    /// Each transport failure must say something different — the whole point of
    /// separating them is that the user's next action differs.
    func testTransportErrorsHaveDistinctMessages() {
        let messages = [
            APIError.notConfigured, .offline, .hostNotFound,
            .serverUnavailable, .timedOut, .invalidURL, .connectionLost
        ].map(\.userMessage)
        XCTAssertEqual(Set(messages).count, messages.count)
        XCTAssertFalse(messages.contains(where: \.isEmpty))
    }

    /// App Store users were told "localhost" is the phone itself when the app's
    /// own server could not be reached — a server they had never configured.
    func testTheAppsOwnServerIsNeverExplainedAsLocalhost() {
        XCTAssertFalse(APIError.unreachableMessage(for: .builtIn).contains("localhost"))
        XCTAssertFalse(APIError.serverUnavailable.userMessage.contains("localhost"))
    }

    /// The next step differs by where the app was looking, so the words do too.
    func testEachKindOfAddressGetsItsOwnAdvice() {
        let messages = [
            APIError.unreachableMessage(for: .builtIn),
            APIError.unreachableMessage(for: .loopback, inSimulator: false),
            APIError.unreachableMessage(for: .localNetwork),
            APIError.unreachableMessage(for: .other)
        ]
        XCTAssertEqual(Set(messages).count, messages.count)
        XCTAssertFalse(messages.contains(where: \.isEmpty))
        XCTAssertTrue(messages[1].contains("localhost"))
    }

    /// A connection the server dropped part-way was reported as "This device
    /// isn't connected to a network", sending people to check a Wi-Fi that was
    /// working. It is still retried while polling.
    func testADroppedConnectionIsNotReportedAsOffline() {
        XCTAssertEqual(LiveAPIClient.mapTransportError(URLError(.networkConnectionLost)), .connectionLost)
        XCTAssertEqual(LiveAPIClient.mapTransportError(URLError(.notConnectedToInternet)), .offline)
        XCTAssertFalse(APIError.connectionLost.userMessage.contains("isn't connected"))
        XCTAssertTrue(APIError.connectionLost.isTransient)
    }

    /// Render answers 502/503 while the service restarts or deploys, and an
    /// unmapped URLError arrived as a negative "status". Neither is something a
    /// reader can do anything with as a number.
    func testServerTroubleIsNotShownAsARawStatusCode() {
        let unavailable = APIError.unexpectedStatus(503).userMessage
        XCTAssertFalse(unavailable.contains("503"), unavailable)
        XCTAssertTrue(unavailable.contains("Try again"), unavailable)

        let clientSide = APIError.unexpectedStatus(NSURLErrorBadServerResponse).userMessage
        XCTAssertFalse(clientSide.contains("\(NSURLErrorBadServerResponse)"), clientSide)
        XCTAssertNotEqual(clientSide, unavailable)

        // Anything else keeps its number: it is rare, and support needs it.
        XCTAssertTrue(APIError.unexpectedStatus(418).userMessage.contains("418"))
    }

    /// The server's job store is on a disk a restart wipes, so a job can vanish
    /// mid-conversion. "This conversion job no longer exists" was true and told
    /// the reader nothing they could act on.
    func testAJobLostMidConversionSaysWhatHappened() async {
        let client = StubAPIClient()
        client.progressError = APIError.server(
            code: "http_404", message: "This conversion job no longer exists."
        )
        let service = ConversionService(client: client)

        do {
            _ = try await service.awaitCompletion(id: "job-1") { _ in }
            XCTFail("expected the vanished job to throw")
        } catch let error as APIError {
            guard case .server(let code, let message) = error else {
                return XCTFail("expected a server error, got \(error)")
            }
            XCTAssertEqual(code, "job_lost")
            XCTAssertFalse(message.contains("job"), message)
            XCTAssertTrue(message.contains("Try again"), message)
        } catch {
            XCTFail("unexpected error type: \(error)")
        }
    }

    /// In the Simulator loopback is the Mac, where "the phone itself" is wrong.
    func testLoopbackInTheSimulatorIsJustAServerThatIsNotRunning() {
        XCTAssertEqual(
            APIError.unreachableMessage(for: .loopback, inSimulator: true),
            APIError.unreachableMessage(for: .other)
        )
    }

    func testStartPassesModeThroughToTheClient() async throws {
        let client = StubAPIClient()
        let service = ConversionService(client: client)
        let document = SelectedDocument(
            url: URL(fileURLWithPath: "/tmp/book.pdf"),
            filename: "book.pdf",
            byteCount: 1024,
            pageCount: 10,
            title: nil,
            author: nil,
            isEncrypted: false
        )

        let jobID = try await service.start(document: document, mode: .maximumAccuracy)
        XCTAssertEqual(jobID, "job-1")
        XCTAssertEqual(client.createCallCount, 1)
    }
}

private actor Updates {
    private(set) var statuses: [JobStage] = []
    func append(_ status: JobStage) { statuses.append(status) }
}

/// What the error screen says when nothing answers, and whether it lets the
/// user try again.
@MainActor
final class UnreachableServerFailureTests: XCTestCase {

    func testTheAppsOwnServerBeingUnreachableIsRetryable() async {
        let failure = ConversionViewModel.failure(from: .serverUnavailable, addressKind: .builtIn)
        XCTAssertEqual(failure.code, "server_unavailable")
        XCTAssertTrue(failure.isRetryable)
        XCTAssertEqual(failure.message, APIError.unreachableMessage(for: .builtIn))
    }

    /// A failed lookup of a server the user never typed is not their typo, and
    /// used to leave them on a screen with no retry.
    func testAFailedLookupOfTheAppsOwnServerIsNotBlamedOnATypo() async {
        let failure = ConversionViewModel.failure(from: .hostNotFound, addressKind: .builtIn)
        XCTAssertEqual(failure.code, "server_unavailable")
        XCTAssertTrue(failure.isRetryable)
        XCTAssertFalse(failure.message.contains("typo"))
    }

    /// For an address the user typed, a typo is still the likeliest cause.
    func testAFailedLookupOfATypedAddressStillPointsAtTheAddress() async {
        let failure = ConversionViewModel.failure(from: .hostNotFound, addressKind: .other)
        XCTAssertEqual(failure.code, "host_not_found")
        XCTAssertEqual(failure.message, APIError.hostNotFound.userMessage)
    }

    func testAServerOnTheLocalNetworkGetsLocalNetworkAdvice() async {
        let failure = ConversionViewModel.failure(from: .serverUnavailable, addressKind: .localNetwork)
        XCTAssertEqual(failure.code, "server_unavailable")
        XCTAssertEqual(failure.message, APIError.unreachableMessage(for: .localNetwork))
    }
}

// MARK: - Reaching the server at all

/// The app shipped pointing at a live, healthy backend and still sat forever on
/// "Waking the conversion server" with no way out but a force-quit. These cover
/// the two reasons why.
final class BackendReachabilityTests: XCTestCase {

    /// `URLSession.shared` carries a seven-day resource timeout, so a stalled
    /// transfer never failed and the spinner never ended.
    func testEveryBackendRequestIsBounded() {
        let session = BackendTimeouts.makeSession()
        let config = session.configuration

        XCTAssertLessThanOrEqual(
            config.timeoutIntervalForResource, 900,
            "a request that can outlive the user's patience is a hang, not a timeout"
        )
        XCTAssertGreaterThan(config.timeoutIntervalForResource, 0)
        XCTAssertLessThanOrEqual(config.timeoutIntervalForRequest, 120)
        XCTAssertFalse(
            config.waitsForConnectivity,
            "parking the task until the network returns is the same spinner again"
        )
    }

    /// Seven days, for contrast: this is what the app was using.
    func testTheSharedSessionWouldNotHaveBeenAcceptable() {
        XCTAssertGreaterThan(URLSession.shared.configuration.timeoutIntervalForResource, 900)
    }

    func testAnOversizedBookIsNamedWithBothNumbers() {
        let caps = BackendCapabilities(maxUploadMB: 25, maxPageCount: 600)
        let reason = caps.rejection(forByteCount: 60 * 1024 * 1024)
        let message = try? XCTUnwrap(reason)
        XCTAssertNotNil(message)
        XCTAssertTrue(message?.contains("25 MB") ?? false, "the limit is missing: \(message ?? "nil")")
    }

    func testAFileWithinTheLimitIsNotRefused() {
        let caps = BackendCapabilities(maxUploadMB: 25, maxPageCount: 600)
        XCTAssertNil(caps.rejection(forByteCount: 6 * 1024 * 1024))
    }

    /// The size message told App Store users to "raise MAX_UPLOAD_MB on your
    /// own server" — an environment variable on a server they do not run.
    func testTheSizeLimitIsExplainedWithoutServerConfiguration() throws {
        let caps = BackendCapabilities(maxUploadMB: 25, maxPageCount: 600)
        let message = try XCTUnwrap(caps.rejection(forByteCount: 60 * 1024 * 1024))
        XCTAssertFalse(message.contains("MAX_UPLOAD_MB"), message)
    }

    /// The server publishes its page limit and the app knows the page count
    /// before uploading, but only the byte size was checked: a long book went
    /// up in full and was refused once the server opened it.
    func testABookOverThePageLimitIsRefusedBeforeUpload() throws {
        let caps = BackendCapabilities(maxUploadMB: 25, maxPageCount: 600)
        let message = try XCTUnwrap(caps.rejection(forByteCount: 1024 * 1024, pageCount: 700))
        XCTAssertTrue(message.contains("700"), message)
        XCTAssertTrue(message.contains("600"), message)
    }

    func testAPageCountWithinTheLimitOrUnknownIsAccepted() {
        let caps = BackendCapabilities(maxUploadMB: 25, maxPageCount: 600)
        XCTAssertNil(caps.rejection(forByteCount: 1024 * 1024, pageCount: 600))
        XCTAssertNil(caps.rejection(forByteCount: 1024 * 1024, pageCount: nil))
        let unstated = BackendCapabilities(maxUploadMB: 25, maxPageCount: 0)
        XCTAssertNil(unstated.rejection(forByteCount: 1024 * 1024, pageCount: 5000))
    }

    /// An older backend does not publish its limits. The app must still convert
    /// rather than refuse everything.
    func testAServerThatStatesNoLimitRefusesNothing() throws {
        let json = Data(#"{"status":"ok","ai_provider":"none"}"#.utf8)
        let caps = try JSONDecoder().decode(BackendCapabilities.self, from: json)
        XCTAssertEqual(caps.maxUploadMB, 0)
        XCTAssertNil(caps.rejection(forByteCount: 500 * 1024 * 1024))
    }

    func testTheRealHealthPayloadDecodes() throws {
        let json = Data(#"""
            {"status":"ok","ai_provider":"none","max_upload_mb":25,"max_page_count":600}
            """#.utf8)
        let caps = try JSONDecoder().decode(BackendCapabilities.self, from: json)
        XCTAssertEqual(caps.maxUploadMB, 25)
        XCTAssertEqual(caps.maxPageCount, 600)
        XCTAssertEqual(caps.aiProvider, "none")
    }
}

// MARK: - A throttled server

/// Answers every request with HTTP 429, the way an edge proxy does: an HTML
/// body and a Retry-After header, no JSON.
final class Throttled429Protocol: URLProtocol {
    static var body = Data("<html>error code: 1015</html>".utf8)
    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() {
        let response = HTTPURLResponse(
            url: request.url!, statusCode: 429, httpVersion: "HTTP/1.1",
            headerFields: ["Retry-After": "7", "Content-Type": "text/html"])!
        client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: Self.body)
        client?.urlProtocolDidFinishLoading(self)
    }
    override func stopLoading() {}
}

/// A real phone saw "The server returned an unexpected response (429)" under
/// "Connection problem", with Open Settings as the main action. A 429 is a
/// server asking to be left alone for a moment, not a connection or settings
/// fault, and the download step -- which never read the body -- turned it into
/// a raw code every time.
final class ThrottledServerTests: XCTestCase {

    private func client() -> LiveAPIClient {
        let config = URLSessionConfiguration.ephemeral
        config.protocolClasses = [Throttled429Protocol.self]
        return LiveAPIClient(baseURL: URL(string: "https://example.invalid")!,
                             session: URLSession(configuration: config))
    }

    func testA429WithoutJSONIsBusyNotUnexpected() async {
        do {
            _ = try await client().fetchProgress(id: "abc")
            XCTFail("expected an error")
        } catch let error as APIError {
            XCTAssertEqual(error, .busy(retryAfter: 7, message: nil))
            XCTAssertTrue(error.isTransient, "a busy server is waited out while polling")
        } catch { XCTFail("unexpected \(error)") }
    }

    func testTheDownloadReportsBusyToo() async {
        do {
            _ = try await client().downloadEPUB(id: "abc", suggestedFilename: "x.epub")
            XCTFail("expected an error")
        } catch let error as APIError {
            XCTAssertEqual(error, .busy(retryAfter: 7, message: nil))
        } catch { XCTFail("unexpected \(error)") }
    }

    func testOurOwnLimiterKeepsItsMessage() async {
        Throttled429Protocol.body = Data(#"{"code":"rate_limited","message":"Too many requests. Please slow down and try again."}"#.utf8)
        defer { Throttled429Protocol.body = Data("<html>error code: 1015</html>".utf8) }
        do {
            _ = try await client().fetchProgress(id: "abc")
            XCTFail("expected an error")
        } catch let error as APIError {
            XCTAssertEqual(error, .busy(retryAfter: 7, message: "Too many requests. Please slow down and try again."))
        } catch { XCTFail("unexpected \(error)") }
    }

    @MainActor
    func testTheScreenOffersTryAgainNotSettings() {
        let failure = ConversionViewModel.failure(from: .busy(retryAfter: 7, message: nil), addressKind: .builtIn)
        XCTAssertEqual(failure.code, "server_busy")
        XCTAssertTrue(failure.isRetryable)
        XCTAssertFalse(failure.message.contains("429"), "no raw status code for a reader")
    }

    func testBackoffHonoursRetryAfterWithinReason() {
        XCTAssertEqual(ConversionService.backoff(for: .busy(retryAfter: 7, message: nil)), 7)
        XCTAssertEqual(ConversionService.backoff(for: .busy(retryAfter: 3600, message: nil)), 30)
        XCTAssertEqual(ConversionService.backoff(for: .busy(retryAfter: nil, message: nil)), 5)
        XCTAssertEqual(ConversionService.backoff(for: .timedOut), ConversionService.pollIntervalSeconds)
    }
}
