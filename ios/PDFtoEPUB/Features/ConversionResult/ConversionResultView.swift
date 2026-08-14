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

    private var headerCard: some View {
        VStack(alignment: .leading, spacing: Theme.Spacing.tight) {
            Label("Conversion complete", systemImage: "checkmark.seal.fill")
                .font(.subheadline.weight(.semibold))
                .foregroundStyle(Color.accentColor)

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
                statRow("Footnotes", value: "\(report.footnoteCount)")
            }
            if report.endnoteCount > 0 {
                Divider()
                statRow("Endnotes", value: "\(report.endnoteCount)")
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
            Divider()
            statRow("Quality score", value: String(format: "%.1f", report.qualityScore))
            Divider()
            statRow("AI assistance", value: report.aiProviderUsed == "none" ? "None (fully local)" : report.aiProviderUsed.capitalized)
        }
        .background(Color(.secondarySystemGroupedBackground))
        .clipShape(RoundedRectangle(cornerRadius: Theme.Radius.card, style: .continuous))
    }

    /// Surfaced rather than hidden: the spec requires that unexpected content
    /// loss is flagged for review, never silently reported as a clean success.
    @ViewBuilder
    private var integrityWarningCard: some View {
        if report.contentIntegritySuspicious {
            VStack(alignment: .leading, spacing: Theme.Spacing.tight) {
                Label("Needs review", systemImage: "exclamationmark.triangle.fill")
                    .font(.subheadline.weight(.semibold))
                    .foregroundStyle(.orange)
                Text("Some of the source document may not have carried over. Your original PDF was not modified.")
                    .font(.footnote)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
                ForEach(report.contentIntegrityNotes.prefix(3), id: \.self) { note in
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
