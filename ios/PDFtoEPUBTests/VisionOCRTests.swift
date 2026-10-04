import CoreGraphics
import PDFKit
import Vision
import XCTest
@testable import PDFtoEPUB

/// On-device OCR, tested against text this process renders itself.
///
/// No book is committed to the repository to test this: a Turkish page is
/// drawn into a PDF at runtime and then read back. That keeps the fixture free
/// of anyone's copyrighted scan and tests the thing that actually matters —
/// whether Vision returns Turkish letters, and whether the boxes it returns
/// land where the server expects them.
final class VisionOCRTests: XCTestCase {

    /// Every letter Turkish has that English does not, in real words.
    static let turkishLines = [
        "İÇİNDEKİLER",
        "Dilin insana yüklediği sorumluluk ağırdır.",
        "Çünkü her kelime bir iz bırakır.",
    ]

    /// A one-page PDF with the given lines drawn as real text, then flattened
    /// to an image so the only way to read it back is OCR.
    private func scannedPDF(lines: [String], pageSize: CGSize) throws -> URL {
        let url = FileManager.default.temporaryDirectory
            .appendingPathComponent("vision-\(UUID().uuidString).pdf")

        // Draw the text large: a 200dpi raster of 11pt type is legible, but
        // this test is about letters and geometry, not about how small a face
        // Vision can manage.
        let renderer = UIGraphicsPDFRenderer(
            bounds: CGRect(origin: .zero, size: pageSize)
        )
        try renderer.writePDF(to: url) { context in
            context.beginPage()
            let attributes: [NSAttributedString.Key: Any] = [
                .font: UIFont.systemFont(ofSize: 28),
                .foregroundColor: UIColor.black,
            ]
            for (index, line) in lines.enumerated() {
                let text = NSAttributedString(string: line, attributes: attributes)
                text.draw(at: CGPoint(x: 60, y: 80 + Double(index) * 56))
            }
        }
        return url
    }

    func testVisionReadsTurkishLettersBackOffAPage() throws {
        let size = CGSize(width: 595, height: 842)
        let url = try scannedPDF(lines: Self.turkishLines, pageSize: size)
        defer { try? FileManager.default.removeItem(at: url) }

        let document = try XCTUnwrap(PDFDocument(url: url))
        let pageRef = try XCTUnwrap(document.page(at: 0)?.pageRef)
        let page = try VisionPageOCR.recognise(page: pageRef, pageNumber: 1)

        XCTAssertFalse(page.lines.isEmpty, "Vision returned nothing for a page of text")
        let read = page.lines
            .map { $0.words.map(\.text).joined(separator: " ") }
            .joined(separator: "\n")

        // Diacritics are the whole reason for choosing Vision over a server
        // running Tesseract with eng+tur.
        for letter in ["İ", "Ç", "ğ", "ı", "ü"] {
            XCTAssertTrue(read.contains(letter), "'\(letter)' missing from: \(read)")
        }
        XCTAssertTrue(read.contains("kelime"), read)
    }

    func testWordBoxesLandOnThePageInTheServersSpace() throws {
        let size = CGSize(width: 595, height: 842)
        let url = try scannedPDF(lines: Self.turkishLines, pageSize: size)
        defer { try? FileManager.default.removeItem(at: url) }

        let document = try XCTUnwrap(PDFDocument(url: url))
        let pageRef = try XCTUnwrap(document.page(at: 0)?.pageRef)
        let page = try VisionPageOCR.recognise(page: pageRef, pageNumber: 1)
        let words = page.lines.flatMap(\.words)
        XCTAssertFalse(words.isEmpty)

        for word in words {
            XCTAssertEqual(word.bbox.count, 4)
            let (x0, y0, x1, y1) = (word.bbox[0], word.bbox[1], word.bbox[2], word.bbox[3])
            XCTAssertLessThan(x0, x1, "box is inside out: \(word.text)")
            XCTAssertLessThan(y0, y1, "box is inside out: \(word.text)")
            XCTAssertGreaterThanOrEqual(x0, 0)
            XCTAssertGreaterThanOrEqual(y0, 0)
            XCTAssertLessThanOrEqual(x1, Double(size.width) + 1)
            XCTAssertLessThanOrEqual(y1, Double(size.height) + 1)
        }

        // The first line was drawn near the top, so with a top-left origin it
        // must have a *small* y. If the y flip were missing this would be ~760
        // and the server would assemble the book bottom-up.
        let firstLineTop = try XCTUnwrap(page.lines.first?.words.first?.bbox[1])
        XCTAssertLessThan(firstLineTop, Double(size.height) / 3, "the y axis is flipped")
    }

    func testAPageOfRealTextIsNotSentForOCR() throws {
        /// A PDF with a text layer needs nothing from Vision; OCR'ing it would
        /// spend battery to produce worse text than the page already carries.
        let url = try scannedPDF(lines: Self.turkishLines, pageSize: CGSize(width: 595, height: 842))
        defer { try? FileManager.default.removeItem(at: url) }
        let document = try XCTUnwrap(PDFDocument(url: url))

        let characters = (document.page(at: 0)?.string ?? "").filter { !$0.isWhitespace }.count
        if characters >= ScannedPageFinder.minimumCharactersForNativeText {
            XCTAssertTrue(
                ScannedPageFinder.scannedPages(in: document).isEmpty,
                "a page with \(characters) characters of real text was sent for OCR"
            )
        } else {
            XCTAssertEqual(ScannedPageFinder.scannedPages(in: document), [1])
        }
    }
}

/// The coordinate arithmetic, on its own, where a mistake is visible.
final class PageGeometryTests: XCTestCase {

    func testAnUnrotatedPageKeepsItsSize() {
        let size = PageGeometry.displayedSize(
            cropBox: CGRect(x: 0, y: 0, width: 595, height: 842), rotationDegrees: 0
        )
        XCTAssertEqual(size.width, 595)
        XCTAssertEqual(size.height, 842)
    }

    func testAQuarterTurnSwapsWidthAndHeight() {
        /// Must match the server, where `page.rect` is already the rotated box:
        /// a 90°-rotated A4 page is 842x595 there, not 595x842.
        for rotation in [90, 270, -90, 450] {
            let size = PageGeometry.displayedSize(
                cropBox: CGRect(x: 0, y: 0, width: 595, height: 842),
                rotationDegrees: rotation
            )
            XCTAssertEqual(size.width, 842, "rotation \(rotation)")
            XCTAssertEqual(size.height, 595, "rotation \(rotation)")
        }
    }

    func testAHalfTurnKeepsTheSize() {
        let size = PageGeometry.displayedSize(
            cropBox: CGRect(x: 0, y: 0, width: 595, height: 842), rotationDegrees: 180
        )
        XCTAssertEqual(size.width, 595)
        XCTAssertEqual(size.height, 842)
    }

    func testTheTopOfThePageConvertsToASmallY() {
        /// Vision's y runs upward, the server's runs downward. A box at the top
        /// of the page has a *high* normalized y and must come out near zero.
        let displayed = CGSize(width: 600, height: 800)
        let nearTop = CGRect(x: 0.1, y: 0.9, width: 0.2, height: 0.05)
        let box = PageGeometry.pdfRect(fromNormalized: nearTop, displayed: displayed)

        XCTAssertEqual(box[0], 60, accuracy: 0.001)      // x0
        XCTAssertEqual(box[2], 180, accuracy: 0.001)     // x1
        XCTAssertEqual(box[1], 40, accuracy: 0.001)      // top  = (1 - 0.95) * 800
        XCTAssertEqual(box[3], 80, accuracy: 0.001)      // bottom = (1 - 0.90) * 800
    }

    func testTheBottomOfThePageConvertsToALargeY() {
        let displayed = CGSize(width: 600, height: 800)
        let nearBottom = CGRect(x: 0.1, y: 0.0, width: 0.2, height: 0.05)
        let box = PageGeometry.pdfRect(fromNormalized: nearBottom, displayed: displayed)
        XCTAssertEqual(box[1], 760, accuracy: 0.001)
        XCTAssertEqual(box[3], 800, accuracy: 0.001)
    }

    func testABoxIsNeverReportedOutsideThePage() {
        /// Vision occasionally puts a box a hair outside the frame; a negative
        /// coordinate is rejected by the server's validator.
        let displayed = CGSize(width: 600, height: 800)
        let overhanging = CGRect(x: -0.05, y: -0.05, width: 1.2, height: 1.2)
        let box = PageGeometry.pdfRect(fromNormalized: overhanging, displayed: displayed)
        XCTAssertGreaterThanOrEqual(box[0], 0)
        XCTAssertGreaterThanOrEqual(box[1], 0)
        XCTAssertLessThanOrEqual(box[2], 600)
        XCTAssertLessThanOrEqual(box[3], 800)
    }
}

/// Measured against a real scanned book, when one is on this machine.
///
/// Skips rather than fails without it: no copyrighted scan is committed to the
/// repository. The number it prints is the whole argument for doing OCR here —
/// the server's free tier was measured at about 110 seconds a page.
final class VisionOCRThroughputTests: XCTestCase {

    /// A real scanned book, if one has been placed in the scratchpad.
    private var scannedBook: URL? {
        let candidates = [
            "/private/tmp/claude-501/-Users-ebrar-Desktop-PDFTOEPUB/04be1a56-e97d-429d-9837-f2b6c1b46da0/scratchpad/scan20.pdf"
        ]
        return candidates.map(URL.init(fileURLWithPath:))
            .first { FileManager.default.fileExists(atPath: $0.path) }
    }

    func testThroughputOnARealScan() throws {
        guard let url = scannedBook else {
            throw XCTSkip("no scanned book on this machine")
        }
        let document = try XCTUnwrap(PDFDocument(url: url))
        let scanned = ScannedPageFinder.scannedPages(in: document)
        XCTAssertFalse(scanned.isEmpty, "a scanned book reported no scanned pages")

        let sample = Array(scanned.prefix(5))
        let started = Date()
        var words = 0
        for number in sample {
            let pageRef = try XCTUnwrap(document.page(at: number - 1)?.pageRef)
            let page = try VisionPageOCR.recognise(page: pageRef, pageNumber: number)
            words += page.lines.reduce(0) { $0 + $1.words.count }
        }
        let elapsed = Date().timeIntervalSince(started)
        let perPage = elapsed / Double(sample.count)

        print(String(
            format: "VISION OCR: %d pages in %.2fs = %.2fs/page, %d words",
            sample.count, elapsed, perPage, words
        ))
        XCTAssertGreaterThan(words, 50, "a page of a scanned book yielded almost no words")
        // The server's free tier was measured at ~110s a page. Anything in this
        // range makes a 253-page book minutes rather than hours; the assertion
        // is loose on purpose because simulator and device differ.
        XCTAssertLessThan(perPage, 30, "on-device OCR is too slow to be worth it")
    }
}
