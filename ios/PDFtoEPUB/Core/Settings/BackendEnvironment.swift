import Foundation

/// Where the conversion backend lives, and whether the user may change it.
///
/// Debug builds default to a machine on the local network so the app can be
/// developed against a backend running on the developer's Mac. A Release build
/// must never do that: an App Store binary that points at `localhost` or a
/// private `192.168.x.x` address is broken for every user who is not the
/// developer, and Apple rejects builds whose core function cannot work on a
/// reviewer's device.
///
/// The production address is read from `PRODUCTION_BACKEND_URL` in the build
/// settings, which flows into Info.plist. It is deliberately empty in the
/// checked-in configuration: no hosted backend exists yet, and inventing a URL
/// would produce a build that fails mysteriously rather than one that says so.
enum BackendEnvironment {
    /// The address a fresh install should use, or nil when none is configured.
    static var defaultBaseURLString: String? {
        #if DEBUG
        // Development stays local even once a production backend exists.
        // Checking the configured URL first meant that the moment one was
        // filled in, every debug run and every test began driving the live
        // service — the opposite of what a dev build should do. The address is
        // still editable in Settings, so testing against production remains one
        // field away.
        return "http://localhost:8000"
        #else
        // Release with no production backend: the app must ask rather than
        // silently point at a machine the user does not have.
        return configuredProductionURL
        #endif
    }

    /// True when the build has a hosted backend and the address is not the
    /// user's concern. Settings hides the field in that case.
    static var isManagedByBuild: Bool {
        configuredProductionURL != nil
    }

    /// True when this build cannot convert anything until the user supplies an
    /// address. Drives the first-run explanation in the UI.
    static var requiresUserSuppliedAddress: Bool {
        #if DEBUG
        return false
        #else
        return configuredProductionURL == nil
        #endif
    }

    private static var configuredProductionURL: String? {
        guard
            let raw = Bundle.main.object(forInfoDictionaryKey: "PRODUCTION_BACKEND_URL") as? String
        else { return nil }
        let trimmed = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty, let url = URL(string: trimmed), url.scheme != nil else {
            return nil
        }
        // A private or loopback address is a development convenience that must
        // never survive into a shipped build.
        guard !isPrivateAddress(url) else { return nil }
        return trimmed
    }

    /// Loopback and RFC 1918 hosts, which cannot work for a general audience.
    static func isPrivateAddress(_ url: URL) -> Bool {
        guard let host = url.host?.lowercased() else { return false }
        if host == "localhost" || host == "127.0.0.1" || host == "::1" { return true }
        if host.hasSuffix(".local") { return true }
        if host.hasPrefix("192.168.") || host.hasPrefix("10.") { return true }
        // 172.16.0.0 – 172.31.255.255
        if host.hasPrefix("172.") {
            let parts = host.split(separator: ".")
            if parts.count > 1, let second = Int(parts[1]), (16...31).contains(second) {
                return true
            }
        }
        return false
    }

    /// Whether a user-entered address is usable in this build.
    ///
    /// A private address is *allowed* here even in Release: this app's model is
    /// that the user runs the conversion server themselves, very often on a
    /// machine on their own network, and ATS is configured to permit exactly
    /// that. What is forbidden is *defaulting* to one — see
    /// `configuredProductionURL`, which refuses to ship a private address as the
    /// built-in address.
    ///
    /// Plain HTTP to a *public* host is a different matter: the user's document
    /// would cross the internet in the clear, so that is rejected.
    static func validate(_ urlString: String) -> BackendAddressIssue? {
        let trimmed = urlString.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return .empty }
        guard let url = URL(string: trimmed), let scheme = url.scheme?.lowercased(),
              url.host != nil
        else { return .malformed }
        guard scheme == "http" || scheme == "https" else { return .unsupportedScheme }

        if scheme == "http", !isPrivateAddress(url) { return .insecureScheme }
        return nil
    }
}

enum BackendAddressIssue: Equatable {
    case empty
    case malformed
    case unsupportedScheme
    case insecureScheme

    var message: String {
        switch self {
        case .empty:
            return "Enter the address of your conversion server."
        case .malformed:
            return "That doesn't look like a valid address. Include http:// or https://."
        case .unsupportedScheme:
            return "The address must start with http:// or https://."
        case .insecureScheme:
            return """
                Use https:// for a server on the internet, so your documents \
                aren't sent in the clear.
                """
        }
    }
}
