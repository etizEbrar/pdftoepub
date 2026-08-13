import Foundation
import SwiftUI

/// User-configurable app settings. The backend address is configurable because
/// this build ships without a hosted backend — the user points it at their own.
@Observable
final class AppSettings {
    static let defaultBaseURLString = "http://localhost:8000"

    var baseURLString: String {
        didSet { UserDefaults.standard.set(baseURLString, forKey: Keys.baseURL) }
    }

    var preferredMode: ConversionMode {
        didSet { UserDefaults.standard.set(preferredMode.rawValue, forKey: Keys.preferredMode) }
    }

    init() {
        self.baseURLString = UserDefaults.standard.string(forKey: Keys.baseURL) ?? Self.defaultBaseURLString
        let storedMode = UserDefaults.standard.string(forKey: Keys.preferredMode) ?? ""
        self.preferredMode = ConversionMode(rawValue: storedMode) ?? .maximumAccuracy
    }

    var baseURL: URL? {
        URL(string: baseURLString.trimmingCharacters(in: .whitespacesAndNewlines))
    }

    private enum Keys {
        static let baseURL = "backend.baseURL"
        static let preferredMode = "conversion.preferredMode"
    }
}
