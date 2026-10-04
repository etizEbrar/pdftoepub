import Foundation
import PDFKit

/// Which pages have no usable text layer, and so are worth OCR'ing here.
///
/// Mirrors the server's own classification closely enough that the two agree
/// about the same book. The server still decides independently, and a page
/// this finder skips is simply a page the server reads itself — so being
/// slightly generous is safe and being stingy is not.
///
/// PDFKit is used rather than a hand-rolled content-stream scan: text is shown
/// by several operators, `TJ` carries an array of strings rather than one
/// string, and miscounting that way means OCR'ing pages that already have
/// perfectly good text — slower, and worse than the text already there.
enum ScannedPageFinder {

    /// Below this many characters a page is treated as having no text layer.
    /// A scanned page is rarely completely empty: a page number or a running
    /// head is often a real text object laid over the image, so zero is too
    /// strict a test.
    static let minimumCharactersForNativeText = 120

    /// 1-based page numbers that look scanned, in order.
    static func scannedPages(in document: PDFDocument) -> [Int] {
        (0..<document.pageCount).compactMap { index in
            guard let page = document.page(at: index) else { return nil }
            let characters = (page.string ?? "")
                .filter { !$0.isWhitespace }
                .count
            return characters < minimumCharactersForNativeText ? index + 1 : nil
        }
    }
}
