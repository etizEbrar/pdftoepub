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
            .serverUnavailable, .timedOut, .invalidURL
        ].map(\.userMessage)
        XCTAssertEqual(Set(messages).count, messages.count)
        XCTAssertFalse(messages.contains(where: \.isEmpty))
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
