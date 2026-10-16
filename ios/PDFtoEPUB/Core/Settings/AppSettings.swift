import Foundation
import SwiftUI

/// User-configurable app settings.
///
/// The backend address is configurable because this build ships without a
/// hosted backend — the user points it at their own. See `BackendEnvironment`
/// for how the default is chosen and why a Release build refuses private
/// addresses.
@Observable
final class AppSettings {
    /// Empty when the build has no backend configured and the user has not yet
    /// supplied one, which the UI treats as "needs setup" rather than an error.
    var baseURLString: String {
        didSet { persistBaseURL() }
    }

    var preferredMode: ConversionMode {
        didSet { UserDefaults.standard.set(preferredMode.rawValue, forKey: Keys.preferredMode) }
    }

    init() {
        let stored = UserDefaults.standard.string(forKey: Keys.baseURL)
        let usable = stored.flatMap { Self.isUsableHere($0) ? $0 : nil }
        if stored != nil, usable == nil {
            UserDefaults.standard.removeObject(forKey: Keys.baseURL)
        }
        self.baseURLString = usable ?? BackendEnvironment.defaultBaseURLString ?? ""
        let storedMode = UserDefaults.standard.string(forKey: Keys.preferredMode) ?? ""
        self.preferredMode = ConversionMode(rawValue: storedMode) ?? .maximumAccuracy
    }

    /// Stores the address only when it differs from the build's own.
    ///
    /// The default used to be written back like anything else — by "Use the
    /// app's own server", and by every test that put the original address back
    /// when it finished. In a debug build that default is localhost, so a debug
    /// build left localhost on disk as though the user had typed it. An App
    /// Store build installed over it would read that back and prefer it to its
    /// own server, failing every conversion with "Can't reach the server" — and
    /// 1.0, whose Settings had no address field, left no way to change it.
    /// Storing nothing for the default means each build brings its own.
    private func persistBaseURL() {
        let trimmed = baseURLString.trimmingCharacters(in: .whitespacesAndNewlines)
        if let builtIn = BackendEnvironment.defaultBaseURLString, trimmed == builtIn {
            UserDefaults.standard.removeObject(forKey: Keys.baseURL)
        } else {
            UserDefaults.standard.set(baseURLString, forKey: Keys.baseURL)
        }
    }

    /// Whether a stored address can work where the app is running.
    ///
    /// On a phone, loopback is the phone itself, where no conversion server can
    /// run, so a stored one can only be left over from a development build (see
    /// `persistBaseURL`). Dropping it lets installs that already carry one
    /// recover without anyone having to find the cause.
    static func isUsableHere(
        _ address: String,
        inSimulator: Bool = BackendEnvironment.isRunningInSimulator
    ) -> Bool {
        guard !inSimulator,
              let url = URL(string: address.trimmingCharacters(in: .whitespacesAndNewlines))
        else { return true }
        return !BackendEnvironment.isLoopback(url)
    }

    var baseURL: URL? {
        let trimmed = baseURLString.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return nil }
        return URL(string: trimmed)
    }

    /// Nil when the address is usable, otherwise why it is not.
    var addressIssue: BackendAddressIssue? {
        BackendEnvironment.validate(baseURLString)
    }

    /// True before the user has told the app where its backend is.
    var needsBackendSetup: Bool {
        baseURL == nil
    }

    /// True when the user has pointed the app somewhere other than the address
    /// the build ships with. Drives the "use the app's own server" escape hatch.
    var isOverridingBuiltInAddress: Bool {
        guard let builtIn = BackendEnvironment.defaultBaseURLString else { return false }
        return baseURLString.trimmingCharacters(in: .whitespacesAndNewlines) != builtIn
    }

    /// Puts the built-in address back, for when an experiment with a tunnel or
    /// a LAN server leaves the app pointing at something that is gone.
    func resetToBuiltInAddress() {
        baseURLString = BackendEnvironment.defaultBaseURLString ?? ""
    }

    private enum Keys {
        static let baseURL = "backend.baseURL"
        static let preferredMode = "conversion.preferredMode"
    }
}
