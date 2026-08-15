import SwiftUI

struct ConversionResultView: View {
    let document: SelectedDocument
    let report: QualityReport
    let epubURL: URL
    let onConvertAnother: () -> Void

    @State private var isPreviewPresented = false

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: Theme.Spacing.loose) {
                headerCard
                integrityWarningCard
                statsCard
                validationCard
            }
            .padding(Theme.Spacing.regular)
        }
        .background(Color(.systemGroupedBackground))
        .safeAreaInset(edge: .bottom) {
            VStack(spacing: Theme.Spacing.tight) {
                Button("Preview EPUB") { isPreviewPresented = true }
                    .buttonStyle(PrimaryButtonStyle())

                ShareLink(item: epubURL) {
                    Text("Share or Save to Files")
                        .font(.body.weight(.medium))
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, Theme.Spacing.regular)
                        .background(Color.secondary.opacity(0.12))
                        .foregroundStyle(Color.primary)
                        .clipShape(RoundedRectangle(cornerRadius: Theme.Radius.button, style: .continuous))
                }

                Button("Convert another PDF", action: onConvertAnother)
                    .buttonStyle(.plain)
                    .font(.footnote)
                    .foregroundStyle(Color.accentColor)
                    .padding(.top, 4)
            }
            .padding(Theme.Spacing.regular)
            .background(.bar)
        }
        .fullScreenCover(isPresented: $isPreviewPresented) {
            EPUBPreviewView(url: epubURL) { isPreviewPresented = false }
                .ignoresSafeArea()
        }
    }

    /// A valid EPUB is not automatically a good ebook. When the backend reports
    /// structural shortfalls the header says so plainly rather than showing an
    /// unqualified success.
    private var needsReview: Bool {
        report.needsReview || report.contentIntegritySuspicious
    }

    private var headerCard: some View {
        VStack(alignment: .leading, spacing: Theme.Spacing.tight) {
            Label(
                needsReview ? "Converted — worth reviewing" : "Conversion complete",
                systemImage: needsReview ? "exclamationmark.triangle.fill" : "checkmark.seal.fill"
            )
            .font(.subheadline.weight(.semibold))
            .foregroundStyle(needsReview ? Color.orange : Color.accentColor)

            Text(report.title ?? document.filename)
                .font(.title3.weight(.semibold))
                .lineLimit(3)

            if let author = report.author {
                Text(author)
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .cardBackground()
        .accessibilityElement(children: .combine)
    }

    /// Only statistics the backend actually calculated are shown (spec section 60).
    private var statsCard: some View {
        VStack(spacing: 0) {
            statRow("Pages", value: "\(report.pageCount)")
            Divider()
            statRow("Chapters", value: "\(report.chapterCount)")
            Divider()
            statRow("Headings", value: "\(report.headingCount)")
            if report.footnoteCount > 0 {
                Divider()
                // How many notes are actually reachable matters more than how
                // many exist, so both numbers are shown together.
                statRow(
                    "Footnotes",
                    value: "\(report.footnotesLinked) linked / \(report.footnoteCount)",
                    valueColor: report.footnotesLinked < report.footnoteCount ? .orange : .secondary
                )
            }
            if report.endnoteCount > 0 {
                Divider()
                statRow(
                    "Endnotes",
                    value: "\(report.endnotesLinked) linked / \(report.endnoteCount)",
                    valueColor: report.endnotesLinked < report.endnoteCount ? .orange : .secondary
                )
            }
            if report.imageCount > 0 {
                Divider()
                statRow("Images", value: "\(report.imageCount)")
            }
            if report.tableCount > 0 {
                Divider()
                statRow("Tables", value: "\(report.tableCount)")
            }
            if report.formulaCount > 0 {
                Divider()
                statRow("Equations", value: "\(report.formulaCount)")
            }
            if report.verseCount > 0 {
                Divider()
                statRow("Verse passages", value: "\(report.verseCount)")
            }
            Divider()
            statRow("Words", value: "\(report.wordCountEpub)")
        }
        .background(Color(.secondarySystemGroupedBackground))
        .clipShape(RoundedRectangle(cornerRadius: Theme.Radius.card, style: .continuous))
    }

    private var validationCard: some View {
        VStack(spacing: 0) {
            statRow(
                "EPUB3 validation",
                value: report.epubcheckPassed ? "Pass" : "Fail",
                valueColor: report.epubcheckPassed ? .green : .red
            )
            Divider()
            statRow(
                "Content integrity",
                value: percent(report.contentIntegrityRatio),
                valueColor: report.contentIntegritySuspicious ? .orange : .secondary
            )
            if report.ocrPageCount > 0 {
                Divider()
                statRow("Pages read by OCR", value: "\(report.ocrPageCount)")
                if let confidence = report.ocrMeanConfidence {
                    Divider()
                    statRow("OCR confidence", value: String(format: "%.0f%%", confidence))
                }
            }
            if report.imageFallbackCount > 0 {
                Divider()
                statRow("Preserved as images", value: "\(report.imageFallbackCount)")
            }
            if report.rtlBlockCount > 0 {
                Divider()
                statRow("Right-to-left passages", value: "\(report.rtlBlockCount)")
            }
            if report.textCorrections > 0 {
                Divider()
                statRow("Text corrections", value: "\(report.textCorrections)")
            }
            if report.suspiciousPassages > 0 {
                Divider()
                // Detected but deliberately not altered — shown so the reader
                // knows where the scan is doubtful rather than being told all is well.
                statRow(
                    "Passages left as found",
                    value: "\(report.suspiciousPassages)",
                    valueColor: .orange
                )
            }
            Divider()
            statRow("Quality score", value: String(format: "%.1f", report.qualityScore))
            Divider()
            statRow("AI assistance", value: report.aiProviderUsed == "none" ? "None (fully local)" : report.aiProviderUsed.capitalized)
        }
        .background(Color(.secondarySystemGroupedBackground))
        .clipShape(RoundedRectangle(cornerRadius: Theme.Radius.card, style: .continuous))
    }

    /// Surfaced rather than hidden: structural shortfalls and unexpected content
    /// loss are reported, never silently presented as a clean success.
    @ViewBuilder
    private var integrityWarningCard: some View {
        if needsReview {
            VStack(alignment: .leading, spacing: Theme.Spacing.tight) {
                Label("What to check", systemImage: "info.circle.fill")
                    .font(.subheadline.weight(.semibold))
                    .foregroundStyle(.orange)
                Text("The EPUB is valid and readable, but some structure couldn't be reconstructed with confidence. Your original PDF was not modified.")
                    .font(.footnote)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
                ForEach(reviewNotes, id: \.self) { note in
                    Text("• \(note)")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .cardBackground()
            .accessibilityElement(children: .combine)
        }
    }

    private var reviewNotes: [String] {
        var notes = report.reviewReasons
        if notes.isEmpty { notes = report.contentIntegrityNotes }
        return Array(notes.prefix(4))
    }

    private func percent(_ ratio: Double) -> String {
        String(format: "%.1f%%", ratio * 100)
    }

    private func statRow(_ label: String, value: String, valueColor: Color = .secondary) -> some View {
        HStack {
            Text(label)
                .font(.subheadline)
            Spacer()
            Text(value)
                .font(.subheadline.weight(.medium))
                .foregroundStyle(valueColor)
                .monospacedDigit()
        }
        .padding(.horizontal, Theme.Spacing.regular)
        .padding(.vertical, 12)
        .accessibilityElement(children: .combine)
        .accessibilityLabel("\(label): \(value)")
    }
}
