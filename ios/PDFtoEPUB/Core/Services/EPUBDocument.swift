import Foundation

/// An unpacked book: where it lives, and the chapters in reading order.
///
/// Kept apart from the reader view so the parts that can go wrong — finding
/// the package, ordering the spine, cleaning up — are testable without one.
struct EPUBDocument {
    let root: URL
    /// Absolute file URLs of the spine documents, in order.
    let chapters: [URL]

    /// Where previews are unpacked, one folder per open book.
    static var previewsDirectory: URL {
        FileManager.default.temporaryDirectory
            .appendingPathComponent("epub-previews", isDirectory: true)
    }

    /// Unpacks `archive` for reading.
    ///
    /// Each preview used to unpack into a folder that nothing ever removed, so
    /// opening a book five times left five copies of it, images and all.
    /// Anything an earlier preview left behind — one the app was closed
    /// during, say — is cleared first, and `close()` removes this one.
    static func open(_ archive: URL) throws -> EPUBDocument {
        sweepPreviews()
        let root = previewsDirectory.appendingPathComponent(UUID().uuidString, isDirectory: true)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        do {
            try EPUBArchive.unpack(archive, into: root)
            return try load(unpackedAt: root)
        } catch {
            try? FileManager.default.removeItem(at: root)
            throw error
        }
    }

    /// Reads a book that is already unpacked at `root`.
    static func load(unpackedAt root: URL) throws -> EPUBDocument {
        let opf = try locateOPF(in: root)
        let chapters = try spine(from: opf)
        guard !chapters.isEmpty else {
            throw EPUBArchive.Failure.corruptEntry("the book lists no chapters")
        }
        return EPUBDocument(root: root, chapters: chapters)
    }

    /// Removes this book's unpacked files.
    func close() {
        try? FileManager.default.removeItem(at: root)
    }

    /// Removes every unpacked preview.
    static func sweepPreviews() {
        try? FileManager.default.removeItem(at: previewsDirectory)
    }

    /// The chapter `url` shows, ignoring any #fragment, or nil when it is not
    /// one of this book's chapters. Symlinks are resolved on both sides: the
    /// web view reports /private/var where the temporary directory says /var.
    func chapterIndex(of url: URL) -> Int? {
        let target = url.resolvingSymlinksInPath().path
        return chapters.firstIndex { $0.resolvingSymlinksInPath().path == target }
    }

    /// META-INF/container.xml names the package document; its location is not
    /// fixed by the specification, so it is read rather than assumed.
    private static func locateOPF(in root: URL) throws -> URL {
        let container = root.appendingPathComponent("META-INF/container.xml")
        let xml = try String(contentsOf: container, encoding: .utf8)
        guard let path = firstAttribute("full-path", in: xml) else {
            throw EPUBArchive.Failure.corruptEntry("container.xml")
        }
        return root.appendingPathComponent(path)
    }

    /// The spine gives reading order by idref; the manifest maps each id to a
    /// file. Both are needed, and the order is the spine's, not the manifest's.
    private static func spine(from opf: URL) throws -> [URL] {
        let xml = try String(contentsOf: opf, encoding: .utf8)
        let base = opf.deletingLastPathComponent()

        var manifest: [String: String] = [:]
        for item in matches(of: "<item\\b[^>]*>", in: xml) {
            if let id = firstAttribute("id", in: item), let href = firstAttribute("href", in: item) {
                manifest[id] = href
            }
        }
        var ordered: [URL] = []
        for ref in matches(of: "<itemref\\b[^>]*>", in: xml) {
            if let idref = firstAttribute("idref", in: ref), let href = manifest[idref] {
                ordered.append(base.appendingPathComponent(href))
            }
        }
        return ordered
    }

    private static func matches(of pattern: String, in text: String) -> [String] {
        guard let re = try? NSRegularExpression(pattern: pattern, options: .caseInsensitive) else {
            return []
        }
        let range = NSRange(text.startIndex..., in: text)
        return re.matches(in: text, range: range).compactMap {
            Range($0.range, in: text).map { r in String(text[r]) }
        }
    }

    private static func firstAttribute(_ name: String, in fragment: String) -> String? {
        let pattern = "\(name)\\s*=\\s*[\"']([^\"']+)[\"']"
        guard let re = try? NSRegularExpression(pattern: pattern, options: .caseInsensitive),
              let m = re.firstMatch(in: fragment, range: NSRange(fragment.startIndex..., in: fragment)),
              let r = Range(m.range(at: 1), in: fragment)
        else { return nil }
        return String(fragment[r])
    }
}
