import SwiftUI

/// What the reader sees when their book is ready.
///
/// Deliberately short. The engine measures a great deal about a conversion —
/// how many passages it declined to correct, how many notes it could not link,
/// how many pages were read by OCR, that no AI was involved — and all of it
/// belongs in the quality report the backend returns, not on the screen
/// someone reads once before opening their book. What remains is what a
/// reader can act on: how big the book is, and whether its footnotes tap.
struct ConversionResultView: View {
    let document: SelectedDocument
    let report: QualityReport
    let epubURL: URL
    let onConvertAnother: () -> Void

    @State private var isPreviewPresented = false
    @State private var isSharePresented = false
    @State private var isKindleMissingAlertPresented = false

    private var bookTitle: String {
        report.title ?? document.title ?? document.filename
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: Theme.Spacing.loose) {
                headerCard
                summaryCard
            }
            .padding(Theme.Spacing.regular)
        }
        .background(Color(.systemGroupedBackground))
        .safeAreaInset(edge: .bottom) { actions }
        .fullScreenCover(isPresented: $isPreviewPresented) {
            EPUBPreviewView(url: epubURL) { isPreviewPresented = false }
                .ignoresSafeArea()
        }
        .sheet(isPresented: $isSharePresented) {
            EPUBShareSheet(url: epubURL, title: bookTitle) { isSharePresented = false }
        }
        .alert("Kindle isn't installed", isPresented: $isKindleMissingAlertPresented) {
            Button("Get Kindle") { KindleHandoff.openAppStore() }
            Button("Share another way") { isSharePresented = true }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text("Install the Kindle app to add this book to your library, or share it another way.")
        }
    }

    // MARK: - Header

    private var headerCard: some View {
        VStack(alignment: .leading, spacing: Theme.Spacing.tight) {
            Label("Conversion complete", systemImage: "checkmark.seal.fill")
                .font(.subheadline.weight(.semibold))
                .foregroundStyle(Color.accentColor)

            Text(bookTitle)
                .font(.title2.weight(.semibold))
                .lineLimit(3)
                .fixedSize(horizontal: false, vertical: true)

            if let author = report.author, !author.isEmpty {
                Text(author)
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .cardBackground()
        .accessibilityElement(children: .combine)
    }

    // MARK: - Summary

    /// Pages, chapters and words describe the book. The footnote row appears
    /// only when the book has notes and only says how many are tappable —
    /// which a reader discovers anyway the first time they tap one, so it is
    /// better said here than left as a surprise.
    private var summaryCard: some View {
        VStack(spacing: 0) {
            statRow("Pages", value: "\(report.pageCount)")
            Divider()
            statRow("Chapters", value: "\(report.chapterCount)")
            Divider()
            statRow("Words", value: report.wordCountEpub.formatted(.number))

            if report.footnoteCount > 0 {
                Divider()
                statRow(
                    "Tappable footnotes",
                    value: "\(report.footnotesLinked) of \(report.footnoteCount)"
                )
            }

        }
        .background(Color(.secondarySystemGroupedBackground))
        .clipShape(RoundedRectangle(cornerRadius: Theme.Radius.card, style: .continuous))
        .overlay(alignment: .bottom) { validationBadge.offset(y: 30) }
        .padding(.bottom, 30)
    }

    /// A quiet mark that the file is a valid EPUB3, which is worth knowing and
    /// takes one line rather than a card.
    @ViewBuilder
    private var validationBadge: some View {
        if report.epubcheckPassed {
            Label("Validated EPUB3", systemImage: "checkmark.circle")
                .font(.caption)
                .foregroundStyle(.secondary)
        }
    }

    // MARK: - Actions

    private var actions: some View {
        VStack(spacing: Theme.Spacing.tight) {
            Button {
                sendToKindle()
            } label: {
                Label("Send to Kindle", systemImage: "books.vertical.fill")
            }
            .buttonStyle(PrimaryButtonStyle())
            .accessibilityIdentifier("result.sendToKindle")
            .accessibilityHint(Text(KindleHandoff.handoffExplanation))

            Button("Preview EPUB") { isPreviewPresented = true }
                .buttonStyle(SecondaryButtonStyle())
                .accessibilityIdentifier("result.preview")

            Button { isSharePresented = true } label: {
                Label("Share or Export", systemImage: "square.and.arrow.up")
                    .font(.body.weight(.medium))
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, Theme.Spacing.regular)
                    .overlay(
                        RoundedRectangle(cornerRadius: Theme.Radius.button, style: .continuous)
                            .strokeBorder(Color.secondary.opacity(0.35), lineWidth: 1)
                    )
                    .foregroundStyle(Color.primary)
            }
            .accessibilityIdentifier("result.share")

            Button("Convert another PDF", action: onConvertAnother)
                .buttonStyle(.plain)
                .font(.footnote)
                .foregroundStyle(Color.accentColor)
                .padding(.top, 2)
                .accessibilityIdentifier("result.convertAnother")
        }
        .padding(Theme.Spacing.regular)
        .background(.bar)
    }

    /// Hand the book to Kindle.
    ///
    /// iOS offers no way to launch another app with a file except through a
    /// system menu, and no way to hide other apps from that menu. So when Kindle
    /// is present this shows the Open In menu — the narrowest the system
    /// provides, listing only apps that can open an EPUB. When Kindle is absent,
    /// showing that same menu would present a list of unrelated apps and no way
    /// to get the one the button names; an explicit offer to install it is the
    /// honest response.
    private func sendToKindle() {
        guard KindleHandoff.isKindleInstalled else {
            isKindleMissingAlertPresented = true
            return
        }
        if !KindleHandoff.presentOpenIn(url: epubURL, title: bookTitle) {
            isSharePresented = true
        }
    }

    // MARK: - Rows

    private func statRow(_ label: String, value: String) -> some View {
        HStack {
            Text(label)
                .font(.subheadline)
            Spacer()
            Text(value)
                .font(.subheadline.weight(.medium))
                .foregroundStyle(.secondary)
                .monospacedDigit()
        }
        .padding(.horizontal, Theme.Spacing.regular)
        .padding(.vertical, 14)
        .accessibilityElement(children: .combine)
    }
}
