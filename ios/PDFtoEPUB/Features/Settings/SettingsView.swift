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
                    // The address was hidden whenever the build shipped one,
                    // on the reasoning that there was nothing to get wrong.
                    // When that server is asleep, slow or broken there is then
                    // nothing the user can do either — no way to point the app
                    // at a tunnel, a LAN machine, or a second deployment. The
                    // field is always editable now; the built-in address is
                    // just its default, and one tap restores it.
                    TextField("https://example.com", text: $settings.baseURLString)
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

                    if settings.isOverridingBuiltInAddress {
                        Button("Use the app's own server") {
                            settings.resetToBuiltInAddress()
                            connectionState = .untested
                        }
                        .accessibilityIdentifier("settings.resetAddress")
                    }
                } header: {
                    Text("Backend address")
                } footer: {
                    Text(addressGuidance)
                }

                Section {
                    // The live value, not a claim. The server reports which
                    // provider it is actually using, and "Test connection"
                    // above is what fetches it — so this row can never drift
                    // from what the service is really doing, which is what the
                    // privacy policy points readers at.
                    LabeledContent("Structural review", value: aiProviderDescription)
                } footer: {
                    Text("Your scan is read on this iPhone and the conversion runs on deterministic software. Where a fragment is too ambiguous to place — common on scanned pages — the server can ask Claude to classify just that fragment and its neighbours, never your document. Tap Test connection to see which provider this server is using.")
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

    /// What the server last said it was using, rather than what we assume.
    private var aiProviderDescription: String {
        switch connectionState {
        case .reachable(let provider) where provider == "none":
            return "Not in use"
        case .reachable(let provider) where provider == "anthropic":
            return "Claude, for ambiguous fragments"
        case .reachable(let provider):
            return provider
        case .untested, .checking, .unreachable:
            return "Tap Test connection"
        }
    }

    private var addressGuidance: String {
        let builtIn = BackendEnvironment.defaultBaseURLString
        if let builtIn, !settings.isOverridingBuiltInAddress {
            return "Conversions run on the app's own server (\(builtIn)). Change this only if you are running your own, or pointing the app at a tunnel."
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
        // A free-tier host sleeps after a quiet period and takes most of a
        // minute to come back. At the old 8 seconds this reported a healthy
        // server as unreachable whenever it had simply gone to sleep, which is
        // most of the time it is asked.
        request.timeoutInterval = 60

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
