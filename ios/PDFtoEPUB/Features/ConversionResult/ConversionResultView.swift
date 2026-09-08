import SwiftUI

/// What the reader sees when their book is ready.
///
/// Deliberately short. The engine measures a great deal about a conversion —
/// how many passages it declined to correct, how many notes it could not link —
/// and that detail belongs in the quality report the backend returns, not on
/// the screen someone reads once before opening their book. The two numbers a
/// reader can actually act on are here: how much of the book arrived, and
/// whether its footnotes are tappable.
struct ConversionResultView: View {
    let document: SelectedDocument
    let report: QualityReport
    let epubURL: URL
    let onConvertAnother: () -> Void

    @State private var isPreviewPresented = false
    @State private var isSharePresented = false

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

            // Shown only for scanned books. Machine-read text can contain
            // mistakes no checker will catch, and a reader who does not know
            // the pages were read by OCR has no reason to be sceptical of them.
            if report.ocrPageCount > 0 {
                Divider()
                statRow("Pages read by OCR", value: "\(report.ocrPageCount)")
            }

            // Always shown. It is the app's central claim — that a book is
            // converted by deterministic software and never sent to an AI
            // service — and the App Review notes tell the reviewer they will
            // find exactly this row. Removing it would make those notes untrue.
            Divider()
            statRow("AI assistance", value: aiSummary)
        }
        .background(Color(.secondarySystemGroupedBackground))
        .clipShape(RoundedRectangle(cornerRadius: Theme.Radius.card, style: .continuous))
        .overlay(alignment: .bottom) { validationBadge.offset(y: 30) }
        .padding(.bottom, 30)
    }

    private var aiSummary: String {
        report.aiProviderUsed == "none"
            ? "None (fully local)"
            : report.aiProviderUsed.capitalized
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

    /// Offer the book to the apps that can open it. If nothing on the device
    /// can — Kindle not installed, no other reader — fall back to the full
    /// share sheet so the button always does something useful.
    private func sendToKindle() {
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
