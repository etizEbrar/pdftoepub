import SwiftUI

struct SettingsView: View {
    @Environment(AppSettings.self) private var settings
    @Environment(\.dismiss) private var dismiss

    @State private var connectionState: ConnectionState = .untested

    enum ConnectionState: Equatable {
        case untested
        case checking
        case reachable(provider: String)
        case unreachable(String)
    }

    var body: some View {
        @Bindable var settings = settings

        NavigationStack {
            Form {
                Section {
                    if BackendEnvironment.isManagedByBuild {
                        // A hosted backend ships with the build; there is
                        // nothing here for the user to get wrong.
                        LabeledContent("Server", value: "Managed by the app")
                    } else {
                        TextField("http://192.168.1.10:8000", text: $settings.baseURLString)
                            .textInputAutocapitalization(.never)
                            .autocorrectionDisabled()
                            .keyboardType(.URL)
                            .accessibilityIdentifier("settings.backendAddress")
                            .onChange(of: settings.baseURLString) { _, _ in
                                connectionState = .untested
                            }

                        if let issue = settings.addressIssue, !settings.baseURLString.isEmpty {
                            Label(issue.message, systemImage: "exclamationmark.triangle.fill")
                                .font(.footnote)
                                .foregroundStyle(.orange)
                        }

                        Button {
                            Task { await testConnection() }
                        } label: {
                            HStack {
                                Text("Test connection")
                                Spacer()
                                connectionIndicator
                            }
                        }
                        .accessibilityIdentifier("settings.testConnection")
                        .disabled(connectionState == .checking || settings.addressIssue != nil)
                    }
                } header: {
                    Text("Backend address")
                } footer: {
                    Text(addressGuidance)
                }

                Section {
                    LabeledContent("AI assistance", value: "Optional, off by default")
                } footer: {
                    Text("Conversions run entirely with deterministic, local processing — including OCR, tables, formulas and right-to-left text — and never require a paid AI service. Optional AI review is configured on your own server, not in this app.")
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

    private var addressGuidance: String {
        if BackendEnvironment.isManagedByBuild {
            return "Conversions run on the app's own server. There is nothing to configure."
        }
        #if targetEnvironment(simulator)
        return "Where your conversion server is running. In the Simulator, http://localhost:8000 works."
        #else
        return "Where your conversion server is running. On a real iPhone, use your computer's address on the network (for example http://192.168.1.10:8000) — \"localhost\" would point at this phone. Both devices must be on the same Wi-Fi."
        #endif
    }

    @ViewBuilder
    private var connectionIndicator: some View {
        switch connectionState {
        case .untested:
            EmptyView()
        case .checking:
            ProgressView().controlSize(.small)
        case .reachable(let provider):
            Label(provider == "none" ? "Connected" : "Connected (\(provider))", systemImage: "checkmark.circle.fill")
                .font(.footnote)
                .foregroundStyle(.green)
                .labelStyle(.titleAndIcon)
        case .unreachable(let message):
            Label(message, systemImage: "xmark.circle.fill")
                .font(.footnote)
                .foregroundStyle(.red)
                .labelStyle(.titleAndIcon)
        }
    }

    private func testConnection() async {
        guard let baseURL = settings.baseURL, settings.addressIssue == nil else {
            connectionState = .unreachable("Enter a valid address first")
            return
        }
        connectionState = .checking
        var request = URLRequest(url: baseURL.appendingPathComponent("health"))
        request.timeoutInterval = 8

        do {
            let (data, response) = try await URLSession.shared.data(for: request)
            guard let http = response as? HTTPURLResponse else {
                connectionState = .unreachable("Unexpected response")
                return
            }
            guard http.statusCode == 200 else {
                // Something answered, so the address is right — it just isn't
                // this app's backend, or the backend is unhealthy.
                connectionState = .unreachable("Answered with HTTP \(http.statusCode)")
                return
            }
            guard let health = try? JSONDecoder().decode(HealthResponse.self, from: data) else {
                connectionState = .unreachable("Not a conversion server")
                return
            }
            connectionState = .reachable(provider: health.aiProvider)
        } catch {
            connectionState = .unreachable(Self.describe(error))
        }
    }

    /// Names the actual failure so the user knows which thing to fix.
    private static func describe(_ error: Error) -> String {
        let nsError = error as NSError
        guard nsError.domain == NSURLErrorDomain else { return "Not reachable" }
        switch nsError.code {
        case NSURLErrorCannotFindHost, NSURLErrorDNSLookupFailed:
            return "No such host"
        case NSURLErrorCannotConnectToHost:
            return "Nothing listening on that port"
        case NSURLErrorTimedOut:
            return "Timed out"
        case NSURLErrorNotConnectedToInternet, NSURLErrorNetworkConnectionLost:
            return "No network connection"
        case NSURLErrorAppTransportSecurityRequiresSecureConnection:
            return "Needs https"
        case NSURLErrorSecureConnectionFailed, NSURLErrorServerCertificateUntrusted:
            return "Secure connection failed"
        default:
            return "Not reachable"
        }
    }
}

private struct HealthResponse: Decodable {
    let status: String
    let aiProvider: String

    enum CodingKeys: String, CodingKey {
        case status
        case aiProvider = "ai_provider"
    }
}
