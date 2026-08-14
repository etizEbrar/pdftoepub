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
        XCTAssertTrue(APIError.notConnected.isTransient)
        XCTAssertTrue(APIError.timedOut.isTransient)
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
