import Foundation

/// Text this device recognised, in the shape the backend's `ClientOCR` expects.
///
/// Only text and geometry cross the wire. Every layout decision — lines into
/// blocks, blocks into paragraphs, headings, footnotes, the table of contents —
/// stays on the server, because that logic has to behave identically whether a
/// page's words came from the PDF's own text layer, from Tesseract, or from
/// here, and it is only tested in one place.
///
/// Coordinates are PDF points in the page's displayed space: x to the right,
/// y downward from the top-left. That is the space the server's `Block.bbox`
/// uses, so nothing downstream can tell the sources apart.
struct ClientOCRPayload: Codable, Equatable {
    var engine: String = "apple-vision"
    var pages: [Page]

    struct Page: Codable, Equatable {
        /// 1-based, matching the backend's page numbering.
        let page: Int
        let lines: [Line]
    }

    struct Line: Codable, Equatable {
        let words: [Word]
        let confidence: Double
    }

    struct Word: Codable, Equatable {
        let text: String
        /// [x0, y0, x1, y1] in PDF points, top-left origin.
        let bbox: [Double]
        let confidence: Double
    }

    var recognisedPageCount: Int { pages.filter { !$0.lines.isEmpty }.count }

    var wordCount: Int {
        pages.reduce(0) { $0 + $1.lines.reduce(0) { $0 + $1.words.count } }
    }

    func jsonData() throws -> Data {
        let encoder = JSONEncoder()
        // Smaller on the wire; a long scanned book is tens of megabytes of
        // words and boxes either way.
        encoder.outputFormatting = []
        return try encoder.encode(self)
    }
}
