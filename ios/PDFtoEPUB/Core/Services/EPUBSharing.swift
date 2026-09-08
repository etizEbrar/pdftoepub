import LinkPresentation
import SwiftUI
import UIKit
import UniformTypeIdentifiers

/// Hands a finished EPUB to another app.
///
/// `ShareLink` alone gives the system a bare file URL, which is enough for
/// Files but leaves the receiving app to infer what it has been handed. An
/// explicit item source declares the type and a readable title, which is what
/// puts Kindle and Apple Books near the front of the share sheet instead of
/// buried behind "Copy" and "Save to Files".
final class EPUBActivityItemSource: NSObject, UIActivityItemSource {
    private let url: URL
    private let title: String

    init(url: URL, title: String) {
        self.url = url
        self.title = title
    }

    func activityViewControllerPlaceholderItem(_ controller: UIActivityViewController) -> Any {
        url
    }

    func activityViewController(
        _ controller: UIActivityViewController,
        itemForActivityType activityType: UIActivity.ActivityType?
    ) -> Any? {
        // Always the file itself. Handing back Data would lose the filename,
        // and the filename is what the receiving app shows as the book's name.
        url
    }

    func activityViewController(
        _ controller: UIActivityViewController,
        subjectForActivityType activityType: UIActivity.ActivityType?
    ) -> String {
        // Becomes the mail subject, and the document title in several readers.
        title
    }

    func activityViewController(
        _ controller: UIActivityViewController,
        dataTypeIdentifierForActivityType activityType: UIActivity.ActivityType?
    ) -> String {
        // org.idpf.epub-container — the registered identifier for an EPUB. An
        // app that filters on it (Kindle, Books) will not offer itself unless
        // the type is declared.
        UTType.epub.identifier
    }

    func activityViewControllerLinkMetadata(
        _ controller: UIActivityViewController
    ) -> LPLinkMetadata? {
        let metadata = LPLinkMetadata()
        metadata.title = title
        metadata.originalURL = url
        return metadata
    }
}

/// What the app knows about handing a book to Kindle.
enum KindleHandoff {
    /// Whether the Kindle app appears to be installed.
    ///
    /// Requires the scheme to be listed in LSApplicationQueriesSchemes;
    /// without that entry iOS answers false regardless, so a missing entry
    /// degrades to "offer the share sheet", never to a broken button.
    static var isKindleInstalled: Bool {
        guard let url = URL(string: "kindle://") else { return false }
        return UIApplication.shared.canOpenURL(url)
    }

    /// Amazon publishes no URL scheme for handing a *file* to Kindle — the
    /// documented route is the system share sheet, where Kindle registers as a
    /// handler for EPUB. So this deliberately opens the share sheet rather than
    /// attempting a direct hand-off that would silently do nothing.
    static var handoffExplanation: String {
        isKindleInstalled
            ? "Choose Kindle to add this book to your library."
            : "Install the Kindle app, or choose Mail to send it to your Send-to-Kindle address."
    }
}

/// Presents a share sheet for a finished book.
struct EPUBShareSheet: UIViewControllerRepresentable {
    let url: URL
    let title: String
    var onFinish: (() -> Void)?

    func makeUIViewController(context: Context) -> UIActivityViewController {
        let controller = UIActivityViewController(
            activityItems: [EPUBActivityItemSource(url: url, title: title)],
            applicationActivities: nil
        )
        controller.completionWithItemsHandler = { _, _, _, _ in onFinish?() }
        return controller
    }

    func updateUIViewController(_ controller: UIActivityViewController, context: Context) {}
}
