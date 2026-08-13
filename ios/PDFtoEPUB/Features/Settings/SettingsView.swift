import SwiftUI

struct SettingsView: View {
    @Environment(AppSettings.self) private var settings
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        @Bindable var settings = settings

        NavigationStack {
            Form {
                Section {
                    TextField("http://localhost:8000", text: $settings.baseURLString)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                        .keyboardType(.URL)
                } header: {
                    Text("Backend address")
                } footer: {
                    Text("Where your conversion server is running. This build ships without a hosted backend — run the included server and point the app at it.")
                }

                Section {
                    LabeledContent("AI assistance", value: "Optional, off by default")
                } footer: {
                    Text("Conversions run entirely with deterministic, local processing and never require a paid AI service. Optional AI review is configured on your own server, not in this app.")
                }

                Section {
                    LabeledContent("Your documents", value: "Deleted after conversion")
                } footer: {
                    Text("Your PDF is uploaded only to create your EPUB. Temporary files are removed from the server automatically, and documents are never used for model training.")
                }
            }
            .navigationTitle("Settings")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("Done") { dismiss() }
                }
            }
        }
    }
}
