import SwiftUI

struct ConversionSettingsView: View {
    let document: SelectedDocument
    @Binding var selectedMode: ConversionMode
    let onConvert: () -> Void
    let onChooseDifferent: () -> Void

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: Theme.Spacing.loose) {
                documentCard
                modePicker
            }
            .padding(Theme.Spacing.regular)
        }
        .background(Color(.systemGroupedBackground))
        .safeAreaInset(edge: .bottom) {
            VStack(spacing: Theme.Spacing.tight) {
                Button("Convert to EPUB", action: onConvert)
                    .buttonStyle(PrimaryButtonStyle())
                Button("Choose a different PDF", action: onChooseDifferent)
                    .buttonStyle(SecondaryButtonStyle())
            }
            .padding(Theme.Spacing.regular)
            .background(.bar)
        }
    }

    private var documentCard: some View {
        VStack(alignment: .leading, spacing: Theme.Spacing.tight) {
            Text(document.title ?? document.filename)
                .font(.headline)
                .lineLimit(3)

            if let author = document.author {
                Text(author)
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
            }

            HStack(spacing: Theme.Spacing.regular) {
                if let pageCount = document.pageCount {
                    Label("\(pageCount) pages", systemImage: "doc.text")
                }
                Label(document.formattedSize, systemImage: "internaldrive")
            }
            .font(.footnote)
            .foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .cardBackground()
        .accessibilityElement(children: .combine)
    }

    private var modePicker: some View {
        VStack(alignment: .leading, spacing: Theme.Spacing.tight) {
            Text("Conversion quality")
                .font(.headline)
                .padding(.horizontal, 4)

            VStack(spacing: 0) {
                ForEach(Array(ConversionMode.allCases.enumerated()), id: \.element.id) { index, mode in
                    Button {
                        selectedMode = mode
                    } label: {
                        HStack(alignment: .top, spacing: Theme.Spacing.regular) {
                            Image(systemName: selectedMode == mode ? "checkmark.circle.fill" : "circle")
                                .foregroundStyle(selectedMode == mode ? Color.accentColor : Color.secondary)
                                .font(.title3)

                            VStack(alignment: .leading, spacing: 2) {
                                Text(mode.title)
                                    .font(.body.weight(.medium))
                                    .foregroundStyle(.primary)
                                Text(mode.subtitle)
                                    .font(.footnote)
                                    .foregroundStyle(.secondary)
                                    .fixedSize(horizontal: false, vertical: true)
                            }
                            Spacer(minLength: 0)
                        }
                        .padding(Theme.Spacing.regular)
                        .contentShape(Rectangle())
                    }
                    .buttonStyle(.plain)
                    .accessibilityAddTraits(selectedMode == mode ? [.isSelected] : [])

                    if index < ConversionMode.allCases.count - 1 {
                        Divider().padding(.leading, 52)
                    }
                }
            }
            .background(Color(.secondarySystemGroupedBackground))
            .clipShape(RoundedRectangle(cornerRadius: Theme.Radius.card, style: .continuous))
        }
    }
}
