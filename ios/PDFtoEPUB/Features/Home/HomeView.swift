import SwiftUI
import UniformTypeIdentifiers

struct HomeView: View {
    @State var viewModel: ConversionViewModel
    @State private var isImporterPresented = false
    @State private var isSettingsPresented = false

    var body: some View {
        NavigationStack {
            Group {
                switch viewModel.phase {
                case .idle:
                    emptyState
                case .documentSelected(let document):
                    ConversionSettingsView(
                        document: document,
                        selectedMode: $viewModel.selectedMode,
                        onConvert: viewModel.startConversion,
                        onChooseDifferent: { isImporterPresented = true }
                    )
                case .converting(let document):
                    ConversionProgressView(
                        document: document,
                        progress: viewModel.progress,
                        onCancel: viewModel.cancelConversion
                    )
                case .completed(let document, let report, let epubURL):
                    ConversionResultView(
                        document: document,
                        report: report,
                        epubURL: epubURL,
                        onConvertAnother: viewModel.clearSelection
                    )
                case .failed(let failure):
                    ConversionErrorView(
                        failure: failure,
                        onRetry: viewModel.retry,
                        onChooseDifferent: {
                            viewModel.clearSelection()
                            isImporterPresented = true
                        }
                    )
                }
            }
            .navigationTitle("PDF to EPUB")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button {
                        isSettingsPresented = true
                    } label: {
                        Image(systemName: "gearshape")
                    }
                    .accessibilityLabel("Settings")
                }
            }
            .sheet(isPresented: $isSettingsPresented) {
                SettingsView()
            }
            .fileImporter(
                isPresented: $isImporterPresented,
                allowedContentTypes: [.pdf],
                allowsMultipleSelection: false
            ) { result in
                switch result {
                case .success(let urls):
                    if let url = urls.first { viewModel.selectDocument(at: url) }
                case .failure:
                    break  // the system importer already told the user; nothing to add
                }
            }
        }
    }

    private var emptyState: some View {
        VStack(spacing: Theme.Spacing.loose) {
            Spacer()

            Image(systemName: "book.pages")
                .font(.system(size: 56, weight: .light))
                .foregroundStyle(Color.accentColor)
                .accessibilityHidden(true)

            VStack(spacing: Theme.Spacing.tight) {
                Text("Turn your PDF books into beautiful, reflowable ebooks.")
                    .font(.title3)
                    .multilineTextAlignment(.center)
                    .foregroundStyle(.primary)

                Text("Your PDF is processed to create your EPUB, then temporary files are deleted automatically.")
                    .font(.footnote)
                    .multilineTextAlignment(.center)
                    .foregroundStyle(.secondary)
            }
            .padding(.horizontal, Theme.Spacing.loose)

            Spacer()

            Button("Select PDF") { isImporterPresented = true }
                .buttonStyle(PrimaryButtonStyle())
                .padding(.horizontal, Theme.Spacing.loose)
                .padding(.bottom, Theme.Spacing.section)
        }
        .frame(maxWidth: .infinity)
        .background(Color(.systemGroupedBackground))
        .dropDestination(for: URL.self) { urls, _ in
            guard let url = urls.first, url.pathExtension.lowercased() == "pdf" else { return false }
            viewModel.selectDocument(at: url)
            return true
        }
    }
}
