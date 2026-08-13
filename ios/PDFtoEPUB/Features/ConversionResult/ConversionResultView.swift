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
            if report.imageCount > 0 {
                Divider()
                statRow("Images", value: "\(report.imageCount)")
            }
            if report.tableCount > 0 {
                Divider()
                statRow("Tables", value: "\(report.tableCount)")
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
            statRow("Content integrity", value: percent(report.contentIntegrityRatio))
            Divider()
            statRow("Quality score", value: String(format: "%.1f", report.qualityScore))
            Divider()
            statRow("AI assistance", value: report.aiProviderUsed == "none" ? "None (fully local)" : report.aiProviderUsed.capitalized)
        }
        .background(Color(.secondarySystemGroupedBackground))
        .clipShape(RoundedRectangle(cornerRadius: Theme.Radius.card, style: .continuous))
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
