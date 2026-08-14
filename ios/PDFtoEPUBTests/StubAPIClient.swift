import Foundation
@testable import PDFtoEPUB

/// Scripted APIClient so view-model tests exercise the real state machine
/// without a live backend.
final class StubAPIClient: APIClient, @unchecked Sendable {
    var createResult: Result<ConversionCreatedResponse, Error>
    var progressSequence: [ConversionProgress]
    var summary: ConversionSummary?
    var result: ConversionResult?
    var downloadResult: Result<URL, Error>

    private(set) var createCallCount = 0
    private(set) var deleteCallCount = 0
    private var progressIndex = 0

    init(
        createResult: Result<ConversionCreatedResponse, Error> = .success(
            ConversionCreatedResponse(id: "job-1", status: .uploaded)
        ),
        progressSequence: [ConversionProgress] = [],
        summary: ConversionSummary? = nil,
        result: ConversionResult? = nil,
        downloadResult: Result<URL, Error> = .success(URL(fileURLWithPath: "/tmp/stub.epub"))
    ) {
        self.createResult = createResult
        self.progressSequence = progressSequence
        self.summary = summary
        self.result = result
        self.downloadResult = downloadResult
    }

    func createConversion(fileURL: URL, mode: ConversionMode) async throws -> ConversionCreatedResponse {
        createCallCount += 1
        return try createResult.get()
    }

    func fetchProgress(id: String) async throws -> ConversionProgress {
        guard progressIndex < progressSequence.count else {
            return progressSequence.last ?? ConversionProgress(
                id: id, status: .completed, stageDetail: "Done", page: 0, totalPages: 0, percent: 100
            )
        }
        defer { progressIndex += 1 }
        return progressSequence[progressIndex]
    }

    func fetchSummary(id: String) async throws -> ConversionSummary {
        guard let summary else { throw APIError.decoding }
        return summary
    }

    func fetchResult(id: String) async throws -> ConversionResult {
        guard let result else { throw APIError.decoding }
        return result
    }

    func downloadEPUB(id: String, suggestedFilename: String) async throws -> URL {
        try downloadResult.get()
    }

    func deleteConversion(id: String) async throws {
        deleteCallCount += 1
    }
}

extension QualityReport {
    static func stub(
        title: String = "Test Book",
        epubcheckPassed: Bool = true,
        aiProviderUsed: String = "none",
        ocrPageCount: Int = 0,
        imageFallbackCount: Int = 0,
        contentIntegritySuspicious: Bool = false,
        footnotesLinked: Int = 12,
        needsReview: Bool = false,
        reviewReasons: [String] = []
    ) -> QualityReport {
        QualityReport(
            title: title,
            author: "Author",
            pageCount: 100,
            chapterCount: 8,
            headingCount: 24,
            paragraphCount: 400,
            footnoteCount: 12,
            imageCount: 3,
            tableCount: 0,
            wordCountSource: 40000,
            wordCountEpub: 39800,
            contentIntegrityRatio: 0.995,
            epubcheckPassed: epubcheckPassed,
            epubcheckErrors: [],
            epubcheckWarnings: [],
            aiProviderUsed: aiProviderUsed,
            aiBlocksReviewed: 0,
            qualityScore: 98.5,
            endnoteCount: 0,
            verseCount: 0,
            formulaCount: 0,
            imageFallbackCount: imageFallbackCount,
            rtlBlockCount: 0,
            ocrPageCount: ocrPageCount,
            ocrMeanConfidence: ocrPageCount > 0 ? 94.2 : nil,
            contentIntegritySuspicious: contentIntegritySuspicious,
            contentIntegrityNotes: contentIntegritySuspicious ? ["2 source blocks did not reach the EPUB"] : [],
            footnotesLinked: footnotesLinked,
            endnotesLinked: 0,
            unmatchedMarkerCount: 0,
            navigationEntryCount: 32,
            structureScore: needsReview ? 62.5 : 98.0,
            needsReview: needsReview,
            reviewReasons: reviewReasons
        )
    }
}
