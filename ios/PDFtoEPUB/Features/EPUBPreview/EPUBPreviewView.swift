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
    /// The spine document on screen. Chapters do not link to one another, so
    /// without a way to move between them the reader showed the first chapter
    /// and nothing after it.
    @State private var chapterIndex = 0

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
                    reader(for: document)
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
        .onDisappear {
            if case .ready(let document) = state { document.close() }
        }
    }

    @ViewBuilder
    private func reader(for document: EPUBDocument) -> some View {
        if document.chapters.count > 1 {
            VStack(spacing: 0) {
                EPUBWebView(document: document, chapterIndex: $chapterIndex)
                Divider()
                chapterBar(count: document.chapters.count)
            }
        } else {
            EPUBWebView(document: document, chapterIndex: $chapterIndex)
                .ignoresSafeArea(edges: .bottom)
        }
    }

    private func chapterBar(count: Int) -> some View {
        HStack {
            Button {
                chapterIndex -= 1
            } label: {
                Image(systemName: "chevron.backward")
                    .frame(minWidth: 44, minHeight: 44)
            }
            .disabled(chapterIndex == 0)
            .accessibilityLabel("Previous chapter")

            Spacer()
            Text("Chapter \(chapterIndex + 1) of \(count)")
                .font(.footnote)
                .foregroundStyle(.secondary)
                .monospacedDigit()
            Spacer()

            Button {
                chapterIndex += 1
            } label: {
                Image(systemName: "chevron.forward")
                    .frame(minWidth: 44, minHeight: 44)
            }
            .disabled(chapterIndex >= count - 1)
            .accessibilityLabel("Next chapter")
        }
        .padding(.horizontal, Theme.Spacing.regular)
        .background(.bar)
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

/// Renders one chapter of the book at a time.
private struct EPUBWebView: UIViewRepresentable {
    let document: EPUBDocument
    @Binding var chapterIndex: Int

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
        // Notes link across chapter files; a swipe brings the reader back to
        // the place they tapped from.
        webView.allowsBackForwardNavigationGestures = true
        return webView
    }

    func updateUIView(_ webView: WKWebView, context: Context) {
        let coordinator = context.coordinator
        // A link or a swipe can land on another chapter; keep the bar's
        // position in step with what is actually on screen.
        coordinator.onChapterShown = { index in
            if chapterIndex != index { chapterIndex = index }
        }
        guard coordinator.shownChapter != chapterIndex else { return }
        coordinator.shownChapter = chapterIndex
        // Grant read access to the whole unpacked book, so its stylesheet,
        // images and sibling chapters resolve.
        webView.loadFileURL(document.chapters[chapterIndex], allowingReadAccessTo: document.root)
    }

    func makeCoordinator() -> Coordinator { Coordinator(document: document) }

    final class Coordinator: NSObject, WKNavigationDelegate {
        private let document: EPUBDocument
        /// The chapter last loaded or navigated to; nil before the first load.
        var shownChapter: Int?
        var onChapterShown: ((Int) -> Void)?

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

            if let url = webView.url, let index = document.chapterIndex(of: url) {
                shownChapter = index
                onChapterShown?(index)
            }
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
