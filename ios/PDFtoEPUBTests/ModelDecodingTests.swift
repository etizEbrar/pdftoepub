import XCTest
@testable import PDFtoEPUB

/// These decode payloads captured from the real backend, so a drift between
/// the FastAPI response shape and these models fails here rather than at runtime.
final class ModelDecodingTests: XCTestCase {
    func testDecodesQualityReportFromRealBackendPayload() throws {
        let json = """
        {
          "title": "The Sample Chronicle",
          "author": "A. Test Author",
          "page_count": 3,
          "chapter_count": 3,
          "heading_count": 4,
          "paragraph_count": 3,
          "footnote_count": 1,
          "image_count": 0,
          "table_count": 0,
          "word_count_source": 127,
          "word_count_epub": 125,
          "content_integrity_ratio": 0.9843,
          "epubcheck_passed": true,
          "epubcheck_errors": [],
          "epubcheck_warnings": [],
          "ai_provider_used": "none",
          "ai_blocks_reviewed": 1,
          "quality_score": 99.4
        }
        """.data(using: .utf8)!

        let report = try JSONDecoder().decode(QualityReport.self, from: json)
        XCTAssertEqual(report.title, "The Sample Chronicle")
        XCTAssertEqual(report.chapterCount, 3)
        XCTAssertEqual(report.footnoteCount, 1)
        XCTAssertTrue(report.epubcheckPassed)
        XCTAssertEqual(report.aiProviderUsed, "none")
        XCTAssertEqual(report.qualityScore, 99.4, accuracy: 0.01)
    }

    func testDecodesProgressPayload() throws {
        let json = """
        {"id":"abc","status":"EXTRACTING","stage_detail":"Extracting text and images","page":12,"total_pages":524,"percent":28}
        """.data(using: .utf8)!

        let progress = try JSONDecoder().decode(ConversionProgress.self, from: json)
        XCTAssertEqual(progress.status, .extracting)
        XCTAssertEqual(progress.page, 12)
        XCTAssertEqual(progress.totalPages, 524)
        XCTAssertEqual(progress.percent, 28)
    }

    func testDecodesErrorPayload() throws {
        let json = """
        {"code":"encrypted_pdf","message":"This PDF is password-protected. Remove the password and try again."}
        """.data(using: .utf8)!

        let error = try JSONDecoder().decode(APIErrorResponse.self, from: json)
        XCTAssertEqual(error.code, "encrypted_pdf")
        XCTAssertFalse(error.message.isEmpty)
    }

    func testConversionModeRawValuesMatchBackendContract() {
        XCTAssertEqual(ConversionMode.fast.rawValue, "fast")
        XCTAssertEqual(ConversionMode.balanced.rawValue, "balanced")
        XCTAssertEqual(ConversionMode.maximumAccuracy.rawValue, "maximum_accuracy")
    }

    func testJobStageCoversEveryBackendStage() {
        // Mirrors app/models/job.py::JobStage — a new backend stage must be added here.
        let backendStages = [
            "UPLOADED", "ANALYZING", "EXTRACTING", "STRUCTURE_ANALYSIS", "AI_REVIEW",
            "BUILDING_EPUB", "VALIDATING", "QUALITY_CHECK", "COMPLETED", "FAILED"
        ]
        for raw in backendStages {
            XCTAssertNotNil(JobStage(rawValue: raw), "missing JobStage case for \(raw)")
        }
    }
}
