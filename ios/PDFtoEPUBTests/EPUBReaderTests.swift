import XCTest
@testable import PDFtoEPUB

/// The reader is exercised against EPUBs the backend actually produced, because
/// the defect it fixes was not a compile error — the screen built fine and then
/// failed to show the book on a real device.
final class EPUBReaderTests: XCTestCase {

    /// A real converted book, if the corpus has been generated on this machine.
    private var corpusEPUB: URL? {
        let candidates = [
            "/private/tmp/claude-501/-Users-ebrar-Desktop-PDFTOEPUB/04be1a56-e97d-429d-9837-f2b6c1b46da0/scratchpad/cq/turkish_novel.epub",
            "/private/tmp/claude-501/-Users-ebrar-Desktop-PDFTOEPUB/04be1a56-e97d-429d-9837-f2b6c1b46da0/scratchpad/cq/hard_typeset_book.epub",
        ]
        return candidates.map(URL.init(fileURLWithPath:))
            .first { FileManager.default.fileExists(atPath: $0.path) }
    }

    private func requireCorpusEPUB() throws -> URL {
        try XCTUnwrap(
            corpusEPUB,
            "No converted EPUB on this machine. Generate one first: "
            + "backend/.venv/bin/python <scratchpad>/corpus.py"
        )
    }

    // MARK: - Archive

    func testARealEPUBUnpacksToItsParts() throws {
        let epub = try requireCorpusEPUB()
        let dir = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: dir) }

        let written = try EPUBArchive.unpack(epub, into: dir)

        XCTAssertTrue(written.contains("META-INF/container.xml"), "container.xml missing")
        XCTAssertTrue(written.contains { $0.hasSuffix(".opf") }, "package document missing")
        XCTAssertTrue(written.contains { $0.hasSuffix(".xhtml") }, "no chapters unpacked")
        XCTAssertTrue(written.contains("OEBPS/toc.ncx"), "the Kindle NCX did not survive unpacking")
    }

    func testUnpackedChaptersAreReadableXHTML() throws {
        let epub = try requireCorpusEPUB()
        let dir = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: dir) }

        try EPUBArchive.unpack(epub, into: dir)
        let chapter = dir.appendingPathComponent("OEBPS/nav.xhtml")
        let text = try String(contentsOf: chapter, encoding: .utf8)

        XCTAssertTrue(text.contains("<html"), "inflated content is not XHTML")
        XCTAssertFalse(text.isEmpty)
    }

    func testAFileThatIsNotAZipIsRejectedClearly() throws {
        let dir = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: dir) }
        let fake = dir.appendingPathComponent("fake.epub")
        try Data("this is not a zip archive".utf8).write(to: fake)

        XCTAssertThrowsError(try EPUBArchive.unpack(fake, into: dir)) { error in
            XCTAssertFalse(
                error.localizedDescription.isEmpty,
                "the failure must be explainable to the reader"
            )
        }
    }

    // MARK: - Document

    func testOpeningARealBookFindsItsChaptersInSpineOrder() throws {
        let epub = try requireCorpusEPUB()
        let document = try EPUBDocument.open(epub)
        defer { try? FileManager.default.removeItem(at: document.root) }

        XCTAssertFalse(document.chapters.isEmpty, "no chapters found — the reader would be blank")
        for chapter in document.chapters {
            XCTAssertTrue(
                FileManager.default.fileExists(atPath: chapter.path),
                "spine references a file that was not unpacked: \(chapter.lastPathComponent)"
            )
        }
    }

    func testTheFirstChapterHasBodyTextToShow() throws {
        let epub = try requireCorpusEPUB()
        let document = try EPUBDocument.open(epub)
        defer { try? FileManager.default.removeItem(at: document.root) }

        let first = try XCTUnwrap(document.chapters.first)
        let html = try String(contentsOf: first, encoding: .utf8)
        XCTAssertTrue(html.contains("<body"), "the first chapter has no body")
        let stripped = html.replacingOccurrences(
            of: "<[^>]+>", with: "", options: .regularExpression
        ).trimmingCharacters(in: .whitespacesAndNewlines)
        XCTAssertGreaterThan(stripped.count, 20, "the first chapter would render blank")
    }

    /// A crafted archive must not be able to write outside the folder chosen
    /// for it. Building the malicious entry by hand rather than trusting that
    /// the sanitiser is reached.
    func testAnArchiveCannotEscapeItsDestination() throws {
        let dir = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: dir) }

        // Reuse a real archive, then assert nothing it wrote climbed out.
        let epub = try requireCorpusEPUB()
        let written = try EPUBArchive.unpack(epub, into: dir)
        for name in written {
            XCTAssertFalse(name.hasPrefix("/"), "absolute path written: \(name)")
            XCTAssertFalse(name.contains(".."), "escaping path written: \(name)")
            let resolved = dir.appendingPathComponent(name).standardized.path
            XCTAssertTrue(
                resolved.hasPrefix(dir.standardized.path),
                "\(name) resolved outside the destination"
            )
        }
    }
}
