import UIKit
import PDFKit
import XCTest
@testable import PDFtoEPUB

/// The privacy documentation states that the user's document is removed from
/// the server as soon as the app has the finished book. This test is what makes
/// that a checked claim rather than a promise.
@MainActor
final class DataLifecycleTests: XCTestCase {

    /// A real one-page PDF, so the flow goes through the actual inspector
    /// rather than a stubbed document.
    private func writeTemporaryPDF() throws -> URL {
        let url = FileManager.default.temporaryDirectory
            .appendingPathComponent("lifecycle-\(UUID().uuidString).pdf")
        let bounds = CGRect(x: 0, y: 0, width: 612, height: 792)
        let renderer = UIGraphicsPDFRenderer(bounds: bounds)
        try renderer.writePDF(to: url) { context in
            context.beginPage()
            ("Hello" as NSString).draw(
                at: CGPoint(x: 72, y: 72),
                withAttributes: [.font: UIFont.systemFont(ofSize: 12)]
            )
        }
        return url
    }

    private func completedClient(returning epub: URL) -> StubAPIClient {
        StubAPIClient(
            progressSequence: [
                ConversionProgress(
                    id: "job-1", status: .completed, stageDetail: "Done",
                    page: 1, totalPages: 1, percent: 100
                )
            ],
            result: ConversionResult(
                id: "job-1", status: .completed, qualityReport: .stub(), downloadURL: nil
            ),
            downloadResult: .success(epub)
        )
    }

    private func waitForCompletion(_ viewModel: ConversionViewModel) async throws {
        for _ in 0..<200 {
            if case .completed = viewModel.phase { return }
            if case .failed(let failure) = viewModel.phase {
                XCTFail("conversion failed unexpectedly: \(failure.code) — \(failure.message)")
                return
            }
            try await Task.sleep(nanoseconds: 25_000_000)
        }
        XCTFail("conversion never completed")
    }

    func testTheUploadedDocumentIsDeletedFromTheServerAfterDownload() async throws {
        let pdf = try writeTemporaryPDF()
        defer { try? FileManager.default.removeItem(at: pdf) }

        let epub = FileManager.default.temporaryDirectory
            .appendingPathComponent("lifecycle-\(UUID().uuidString).epub")
        try Data("epub".utf8).write(to: epub)
        defer { try? FileManager.default.removeItem(at: epub) }

        let client = completedClient(returning: epub)
        let settings = AppSettings()
        let original = settings.baseURLString
        defer { settings.baseURLString = original }
        settings.baseURLString = "https://convert.example.com"

        let viewModel = ConversionViewModel(settings: settings, makeClient: { _ in client })
        viewModel.selectDocument(at: pdf)
        viewModel.startConversion()
        try await waitForCompletion(viewModel)

        XCTAssertEqual(
            client.deleteCallCount, 1,
            "the uploaded document must be deleted from the server once the app has the EPUB"
        )
    }

    /// The converted book is written to the app's own temporary directory, not
    /// anywhere shared, and not left on the server.
    func testTheConvertedBookLandsInTheAppsOwnStorage() async throws {
        let pdf = try writeTemporaryPDF()
        defer { try? FileManager.default.removeItem(at: pdf) }

        let epub = FileManager.default.temporaryDirectory
            .appendingPathComponent("lifecycle-\(UUID().uuidString).epub")
        try Data("epub".utf8).write(to: epub)
        defer { try? FileManager.default.removeItem(at: epub) }

        let settings = AppSettings()
        let original = settings.baseURLString
        defer { settings.baseURLString = original }
        settings.baseURLString = "https://convert.example.com"

        let viewModel = ConversionViewModel(
            settings: settings, makeClient: { _ in self.completedClient(returning: epub) }
        )
        viewModel.selectDocument(at: pdf)
        viewModel.startConversion()
        try await waitForCompletion(viewModel)

        guard case .completed(_, _, let epubURL) = viewModel.phase else {
            return XCTFail("expected a completed conversion")
        }
        XCTAssertTrue(
            epubURL.path.hasPrefix(FileManager.default.temporaryDirectory.path)
                || epubURL.path.contains(NSHomeDirectory()),
            "the EPUB must stay inside the app's container, was \(epubURL.path)"
        )
    }
}

/// The finished book is named after the book, not after the PDF it came from.
/// That name is what Kindle and Apple Books show in the library.
final class EPUBFilenameTests: XCTestCase {
    func testTheBookTitleBecomesTheFilename() {
        let name = ConversionViewModel.epubFilename(
            forTitle: "Piraye Seyir", fallback: "scan_final_2.pdf"
        )
        XCTAssertEqual(name, "Piraye Seyir.epub")
    }

    func testTurkishCharactersSurvive() {
        let name = ConversionViewModel.epubFilename(
            forTitle: "Sisin Ardındaki Şehir", fallback: "x.pdf"
        )
        XCTAssertEqual(name, "Sisin Ardındaki Şehir.epub")
    }

    func testCharactersThatBreakFilenamesAreRemoved() {
        let name = ConversionViewModel.epubFilename(
            forTitle: "A/B: C*D?E\"F<G>H|I", fallback: "x.pdf"
        )
        for bad in ["/", ":", "*", "?", "\"", "<", ">", "|", "\\"] {
            XCTAssertFalse(name.contains(bad), "\(bad) survived into \(name)")
        }
        XCTAssertTrue(name.hasSuffix(".epub"))
        XCTAssertFalse(name.contains("  "), "runs of spaces were not collapsed")
    }

    func testAnUntitledBookFallsBackToTheSourceName() {
        XCTAssertEqual(
            ConversionViewModel.epubFilename(forTitle: nil, fallback: "my_scan.pdf"),
            "my_scan.epub"
        )
        XCTAssertEqual(
            ConversionViewModel.epubFilename(forTitle: "   ", fallback: "my_scan.pdf"),
            "my_scan.epub"
        )
    }

    func testAVeryLongTitleIsTruncatedButStillValid() {
        let name = ConversionViewModel.epubFilename(
            forTitle: String(repeating: "A", count: 400), fallback: "x.pdf"
        )
        XCTAssertLessThanOrEqual(name.count, 90)
        XCTAssertTrue(name.hasSuffix(".epub"))
    }
}

/// The share sheet must declare what it is handing over, or Kindle and Books
/// do not offer themselves.
final class EPUBSharingTests: XCTestCase {
    func testTheItemSourceDeclaresTheEPUBType() {
        let url = URL(fileURLWithPath: "/tmp/Book.epub")
        let source = EPUBActivityItemSource(url: url, title: "Book")
        let controller = UIActivityViewController(activityItems: [source], applicationActivities: nil)

        XCTAssertEqual(
            source.activityViewController(controller, dataTypeIdentifierForActivityType: nil),
            "org.idpf.epub-container",
            "the EPUB type identifier is what makes Kindle offer itself"
        )
    }

    func testTheItemIsTheFileItselfSoTheNameSurvives() {
        let url = URL(fileURLWithPath: "/tmp/Piraye Seyir.epub")
        let source = EPUBActivityItemSource(url: url, title: "Piraye Seyir")
        let controller = UIActivityViewController(activityItems: [source], applicationActivities: nil)

        XCTAssertEqual(source.activityViewController(controller, itemForActivityType: nil) as? URL, url)
        XCTAssertEqual(source.activityViewControllerPlaceholderItem(controller) as? URL, url)
        XCTAssertEqual(
            source.activityViewController(controller, subjectForActivityType: nil),
            "Piraye Seyir"
        )
    }

    func testTheHandoffAlwaysExplainsItself() {
        XCTAssertFalse(KindleHandoff.handoffExplanation.isEmpty)
    }
}
