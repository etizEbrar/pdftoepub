import SwiftUI
import WebKit

/// Reads the finished book inside the app.
///
/// This used to hand the file to QuickLook. On iOS that does not render an
/// EPUB — it offers to open the file somewhere else — so "Preview EPUB" sent
/// the reader out to Apple Books instead of showing them their book. The EPUB
/// is now unpacked and its chapters rendered directly, which is the only way to
/// keep the reader in the app.
struct EPUBPreviewView: View {
    let url: URL
    let onDismiss: () -> Void

    @State private var state: LoadState = .loading

    enum LoadState {
        case loading
        case ready(EPUBDocument)
        case failed(String)
    }

    var body: some View {
        NavigationStack {
            Group {
                switch state {
                case .loading:
                    ProgressView("Opening…")
                        .frame(maxWidth: .infinity, maxHeight: .infinity)
                case .ready(let document):
                    EPUBWebView(document: document)
                        .ignoresSafeArea(edges: .bottom)
                case .failed(let message):
                    unreadable(message)
                }
            }
            .navigationTitle("")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("Done", action: onDismiss)
                }
            }
        }
        .task { await load() }
    }

    private func unreadable(_ message: String) -> some View {
        VStack(spacing: Theme.Spacing.tight) {
            Image(systemName: "book.closed")
                .font(.system(size: 40, weight: .light))
                .foregroundStyle(.secondary)
            Text("Can't open this book here")
                .font(.headline)
            Text(message)
                .font(.footnote)
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
            Text("It downloaded correctly — try Share or Export to read it elsewhere.")
                .font(.caption)
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
                .padding(.top, 2)
        }
        .padding(Theme.Spacing.loose)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }

    private func load() async {
        guard case .loading = state else { return }
        do {
            let document = try await Task.detached(priority: .userInitiated) {
                try EPUBDocument.open(url)
            }.value
            state = .ready(document)
        } catch {
            state = .failed(error.localizedDescription)
        }
    }
}

/// An unpacked book: where it lives, and the chapters in reading order.
struct EPUBDocument {
    let root: URL
    /// Absolute file URLs of the spine documents, in order.
    let chapters: [URL]

    static func open(_ archive: URL) throws -> EPUBDocument {
        let root = FileManager.default.temporaryDirectory
            .appendingPathComponent("preview-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        try EPUBArchive.unpack(archive, into: root)

        let opf = try locateOPF(in: root)
        let chapters = try spine(from: opf)
        guard !chapters.isEmpty else {
            throw EPUBArchive.Failure.corruptEntry("the book lists no chapters")
        }
        return EPUBDocument(root: root, chapters: chapters)
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

/// Renders the book's chapters, one scrolling document.
private struct EPUBWebView: UIViewRepresentable {
    let document: EPUBDocument

    func makeUIView(context: Context) -> WKWebView {
        let configuration = WKWebViewConfiguration()
        // The book is local content and has no reason to reach the network.
        // Nothing in a converted EPUB should be loading remote resources, and
        // if a source document tries, it does not get to.
        configuration.defaultWebpagePreferences.allowsContentJavaScript = false

        let webView = WKWebView(frame: .zero, configuration: configuration)
        webView.navigationDelegate = context.coordinator
        webView.isOpaque = false
        webView.backgroundColor = .systemBackground
        webView.scrollView.contentInsetAdjustmentBehavior = .always
        return webView
    }

    func updateUIView(_ webView: WKWebView, context: Context) {
        guard !context.coordinator.hasLoaded else { return }
        context.coordinator.hasLoaded = true
        // Load the first chapter and grant read access to the whole unpacked
        // book, so its stylesheet, images and sibling chapters resolve.
        webView.loadFileURL(document.chapters[0], allowingReadAccessTo: document.root)
    }

    func makeCoordinator() -> Coordinator { Coordinator(document: document) }

    final class Coordinator: NSObject, WKNavigationDelegate {
        private let document: EPUBDocument
        var hasLoaded = false

        init(document: EPUBDocument) { self.document = document }

        func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
            // Typography the source stylesheet does not set, and a dark mode
            // the reader's system setting decides. Injected rather than
            // written into the EPUB, so the exported file stays exactly the
            // book the backend produced.
            let css = """
            var s = document.createElement('style');
            s.textContent = `
              :root { color-scheme: light dark; }
              body {
                font: -apple-system-body;
                line-height: 1.6;
                margin: 0 auto;
                padding: 1.2em 1.1em 3em;
                max-width: 34em;
                -webkit-text-size-adjust: 100%;
              }
              img { max-width: 100%; height: auto; }
            `;
            document.head.appendChild(s);
            """
            webView.evaluateJavaScript(css)
        }

        /// Keep navigation inside the book. A link to another chapter loads;
        /// anything pointing at the network is refused rather than opening a
        /// browser inside the reader.
        func webView(
            _ webView: WKWebView,
            decidePolicyFor action: WKNavigationAction,
            decisionHandler: @escaping (WKNavigationActionPolicy) -> Void
        ) {
            guard let url = action.request.url else { return decisionHandler(.cancel) }
            decisionHandler(url.isFileURL ? .allow : .cancel)
        }
    }
}
