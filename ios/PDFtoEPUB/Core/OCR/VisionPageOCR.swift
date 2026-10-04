import CoreGraphics
import Foundation
import Vision

/// Reads one page with Apple's Vision framework, on this device.
///
/// Why this exists: a scanned page costs about 110 seconds on the 512 MB
/// shared-CPU container the backend runs on, and about two on a phone, which
/// has hardware for exactly this. A 253-page scanned book is the difference
/// between eight hours of server time and a few minutes of local work.
///
/// Turkish is the reason the level is fixed at `.accurate`. Vision's `.fast`
/// path supports six languages and Turkish is not among them; `.accurate`
/// supports thirty-three and does. Choosing `.fast` for speed would silently
/// read Turkish as though it were English.
enum VisionPageOCR {

    /// Preferred first, then English. Order matters to Vision: it biases
    /// correction toward the earlier languages, and these books are Turkish
    /// with English technical terms in them rather than the other way round.
    static let languages = ["tr-TR", "en-US"]

    enum Failure: Error, Equatable {
        case couldNotRasterize
        case recognitionFailed(String)
    }

    /// Recognise one page and return it in the server's coordinate space.
    static func recognise(
        page: CGPDFPage,
        pageNumber: Int,
        dpi: Double = PageRasterizer.defaultDPI
    ) throws -> ClientOCRPayload.Page {
        guard let (image, displayed) = PageRasterizer.render(page: page, dpi: dpi) else {
            throw Failure.couldNotRasterize
        }

        let request = VNRecognizeTextRequest()
        request.recognitionLevel = .accurate
        request.recognitionLanguages = languages
        // Turkish has long agglutinative words that a character-level reading
        // mangles, and the correction is what makes "öğrenmekle" come back
        // whole rather than as three plausible fragments.
        request.usesLanguageCorrection = true

        do {
            try VNImageRequestHandler(cgImage: image, options: [:]).perform([request])
        } catch {
            throw Failure.recognitionFailed(String(describing: error))
        }

        let observations = request.results ?? []
        var lines: [ClientOCRPayload.Line] = []
        lines.reserveCapacity(observations.count)

        for observation in observations {
            guard let candidate = observation.topCandidates(1).first else { continue }
            let words = self.words(in: candidate, displayed: displayed)
            guard !words.isEmpty else { continue }
            lines.append(
                ClientOCRPayload.Line(words: words, confidence: Double(candidate.confidence))
            )
        }

        return ClientOCRPayload.Page(page: pageNumber, lines: lines)
    }

    /// Split one recognised line into words, each with its own box.
    ///
    /// Vision's unit is a line; the server's layout analysis wants words,
    /// because a word's box is what tells it where a column ends and how big
    /// the type is. `boundingBox(for:)` gives the box for any substring of a
    /// candidate, so the words are taken from the string's own ranges rather
    /// than guessed at by dividing the line up.
    private static func words(
        in candidate: VNRecognizedText, displayed: CGSize
    ) -> [ClientOCRPayload.Word] {
        let text = candidate.string
        let confidence = Double(candidate.confidence)
        var words: [ClientOCRPayload.Word] = []

        for range in text.ranges(ofNonWhitespaceRuns: ()) {
            let piece = String(text[range])
            guard !piece.isEmpty else { continue }
            // A box is per-substring and can fail; without one the word has no
            // place on the page, so it is dropped rather than given a guess.
            guard let box = try? candidate.boundingBox(for: range) else { continue }
            words.append(
                ClientOCRPayload.Word(
                    text: piece,
                    bbox: PageGeometry.pdfRect(
                        fromNormalized: box.boundingBox, displayed: displayed
                    ),
                    confidence: confidence
                )
            )
        }
        return words
    }
}

extension String {
    /// Ranges of the whitespace-separated runs in this string.
    ///
    /// Taken as ranges, not as `split`, because `boundingBox(for:)` needs a
    /// range into this exact string to locate the word on the page.
    func ranges(ofNonWhitespaceRuns _: Void = ()) -> [Range<String.Index>] {
        var ranges: [Range<String.Index>] = []
        var start: String.Index?
        for index in indices {
            if self[index].isWhitespace {
                if let begun = start {
                    ranges.append(begun..<index)
                    start = nil
                }
            } else if start == nil {
                start = index
            }
        }
        if let begun = start {
            ranges.append(begun..<endIndex)
        }
        return ranges
    }
}
