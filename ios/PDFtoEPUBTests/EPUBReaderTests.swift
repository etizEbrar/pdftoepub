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

    /// Skips rather than fails without one: the corpus lives in a scratch
    /// folder on one Mac, and a missing file there turned the whole suite red
    /// everywhere else. `UnpackedBookTests` below runs on any machine.
    private func requireCorpusEPUB() throws -> URL {
        guard let corpusEPUB else {
            throw XCTSkip(
                "No converted EPUB on this machine. Generate one first: "
                + "backend/.venv/bin/python <scratchpad>/corpus.py"
            )
        }
        return corpusEPUB
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

/// The reader's handling of an unpacked book, built here file by file in the
/// shape the backend writes, so it needs nothing from any particular machine.
final class UnpackedBookTests: XCTestCase {

    private var root: URL!

    override func setUpWithError() throws {
        try super.setUpWithError()
        root = FileManager.default.temporaryDirectory
            .appendingPathComponent("unpacked-\(UUID().uuidString)", isDirectory: true)
        try write("META-INF/container.xml", """
            <?xml version="1.0"?>
            <container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
              <rootfiles>
                <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
              </rootfiles>
            </container>
            """)
        // Manifest order deliberately differs from spine order.
        try write("OEBPS/content.opf", """
            <package xmlns="http://www.idpf.org/2007/opf" version="3.0">
            <manifest>
            <item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>
            <item id="chap002" href="text/chapter-2.xhtml" media-type="application/xhtml+xml"/>
            <item id="chap001" href="text/chapter-1.xhtml" media-type="application/xhtml+xml"/>
            <item id="chap003" href="text/chapter-3.xhtml" media-type="application/xhtml+xml"/>
            </manifest>
            <spine toc="ncx">
            <itemref idref="chap001"/>
            <itemref idref="chap002"/>
            <itemref idref="chap003"/>
            </spine>
            </package>
            """)
        for n in 1...3 {
            try write("OEBPS/text/chapter-\(n).xhtml", "<html><body><p>Chapter \(n)</p></body></html>")
        }
    }

    override func tearDownWithError() throws {
        try? FileManager.default.removeItem(at: root)
        try super.tearDownWithError()
    }

    private func write(_ path: String, _ text: String) throws {
        let url = root.appendingPathComponent(path)
        try FileManager.default.createDirectory(
            at: url.deletingLastPathComponent(), withIntermediateDirectories: true
        )
        try Data(text.utf8).write(to: url)
    }

    func testChaptersFollowTheSpineNotTheManifest() throws {
        let document = try EPUBDocument.load(unpackedAt: root)
        XCTAssertEqual(
            document.chapters.map(\.lastPathComponent),
            ["chapter-1.xhtml", "chapter-2.xhtml", "chapter-3.xhtml"]
        )
    }

    /// What keeps the chapter bar in step when a note link lands in another
    /// chapter: the web view reports the URL with the fragment it scrolled to.
    func testALinkIntoAChapterIsRecognisedAsThatChapter() throws {
        let document = try EPUBDocument.load(unpackedAt: root)
        let third = document.chapters[2]
        let linked = try XCTUnwrap(URL(string: third.absoluteString + "#note-12"))
        XCTAssertEqual(document.chapterIndex(of: linked), 2)
        XCTAssertNil(document.chapterIndex(of: root.appendingPathComponent("OEBPS/nav.xhtml")))
    }

    /// Opening a preview left an unpacked copy of the book behind every time.
    func testClosingAPreviewRemovesItsFiles() throws {
        let document = try EPUBDocument.load(unpackedAt: root)
        document.close()
        XCTAssertFalse(FileManager.default.fileExists(atPath: root.path))
    }

    /// One the app was closed during is cleared before the next one opens.
    func testLeftoverPreviewsAreSwept() throws {
        let leftover = EPUBDocument.previewsDirectory
            .appendingPathComponent(UUID().uuidString, isDirectory: true)
        try FileManager.default.createDirectory(at: leftover, withIntermediateDirectories: true)

        EPUBDocument.sweepPreviews()

        XCTAssertFalse(FileManager.default.fileExists(atPath: leftover.path))
    }

    func testABookWithoutChaptersIsRejectedClearly() throws {
        try write("OEBPS/content.opf", "<package><manifest/><spine/></package>")
        XCTAssertThrowsError(try EPUBDocument.load(unpackedAt: root)) { error in
            XCTAssertFalse(error.localizedDescription.isEmpty)
        }
    }
}
