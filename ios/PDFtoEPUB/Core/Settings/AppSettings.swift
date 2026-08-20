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
        didSet { UserDefaults.standard.set(baseURLString, forKey: Keys.baseURL) }
    }

    var preferredMode: ConversionMode {
        didSet { UserDefaults.standard.set(preferredMode.rawValue, forKey: Keys.preferredMode) }
    }

    init() {
        let stored = UserDefaults.standard.string(forKey: Keys.baseURL)
        self.baseURLString = stored ?? BackendEnvironment.defaultBaseURLString ?? ""
        let storedMode = UserDefaults.standard.string(forKey: Keys.preferredMode) ?? ""
        self.preferredMode = ConversionMode(rawValue: storedMode) ?? .maximumAccuracy
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

    private enum Keys {
        static let baseURL = "backend.baseURL"
        static let preferredMode = "conversion.preferredMode"
    }
}
