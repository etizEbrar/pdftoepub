import Foundation
import PDFKit

/// Recognises every scanned page of a document on this device.
///
/// Runs off the main actor: a 253-page scan is minutes of sustained work, and
/// the progress bar has to keep moving while it happens. Cancellation is
/// checked between pages so backing out of a conversion stops the OCR too
/// rather than leaving the phone working on a book nobody is waiting for.
actor DocumentOCR {

    struct Progress: Sendable, Equatable {
        let pagesDone: Int
        let pagesTotal: Int
        var fraction: Double {
            pagesTotal > 0 ? Double(pagesDone) / Double(pagesTotal) : 0
        }
    }

    enum Failure: Error, Equatable {
        case couldNotOpenDocument
    }

    /// Recognise the scanned pages of `url`, reporting progress per page.
    ///
    /// Returns nil when the document has no scanned pages — a text PDF needs
    /// nothing from Vision, and sending an empty payload would only invite the
    /// server to think OCR had been attempted and found nothing.
    func recognise(
        documentAt url: URL,
        onProgress: @Sendable (Progress) -> Void = { _ in }
    ) async throws -> ClientOCRPayload? {
        guard let document = PDFDocument(url: url) else {
            throw Failure.couldNotOpenDocument
        }

        let scanned = ScannedPageFinder.scannedPages(in: document)
        guard !scanned.isEmpty else { return nil }

        var pages: [ClientOCRPayload.Page] = []
        pages.reserveCapacity(scanned.count)
        onProgress(Progress(pagesDone: 0, pagesTotal: scanned.count))

        for (index, pageNumber) in scanned.enumerated() {
            try Task.checkCancellation()
            // A page that will not render or will not read is left to the
            // server. Failing the whole book because one page of a 253-page
            // scan was unreadable would be the worse outcome by far.
            if let pdfPage = document.page(at: pageNumber - 1),
               let pageRef = pdfPage.pageRef,
               let recognised = try? VisionPageOCR.recognise(
                   page: pageRef, pageNumber: pageNumber
               ),
               !recognised.lines.isEmpty {
                pages.append(recognised)
            }
            onProgress(Progress(pagesDone: index + 1, pagesTotal: scanned.count))
        }

        guard !pages.isEmpty else { return nil }
        return ClientOCRPayload(pages: pages)
    }
}
