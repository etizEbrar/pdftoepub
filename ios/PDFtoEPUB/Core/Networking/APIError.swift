import Foundation

/// A backend-reported failure. `code` mirrors the backend's stable error codes
/// (see `app/core/errors.py`) so the UI can pick copy without parsing prose.
struct APIErrorResponse: Codable {
    let code: String
    let message: String
}

enum APIError: LocalizedError, Equatable {
    /// What to say when nothing answered, which depends on where the app looked.
    ///
    /// This was one message, written when the only server was one the user ran
    /// on their own computer, so it explained that "localhost" is the phone
    /// itself. Once the app shipped with a server of its own, that became the
    /// explanation App Store users got for a server they never configured.
    static func unreachableMessage(
        for kind: BackendAddressKind,
        inSimulator: Bool = BackendEnvironment.isRunningInSimulator
    ) -> String {
        switch kind {
        case .builtIn:
            return """
                Couldn't connect to the conversion server. Check your internet \
                connection and try again. If it keeps failing, try another \
                network or turn off any VPN or content blocker.
                """
        case .loopback where !inSimulator:
            return """
                On an iPhone, "localhost" means the phone itself, not your \
                computer. To use a server running on your computer, enter the \
                computer's address on your network instead.
                """
        case .localNetwork:
            return """
                Couldn't reach the server on your network. Make sure it's \
                running and that this iPhone is on the same Wi-Fi.
                """
        case .loopback, .other:
            // In the Simulator loopback is the Mac, so this is simply a server
            // that isn't running.
            return """
                Nothing answered at that address. Make sure the conversion \
                server is running, then try again.
                """
        }
    }

    case invalidURL
    /// No backend address has been configured yet.
    case notConfigured
    /// The device has no working network connection at all.
    case offline
    /// The connection dropped part-way. The device is online — the server, or
    /// something between, closed it — so `offline`'s advice would be wrong.
    case connectionLost
    /// The address resolves to nothing — usually a typo in the host name.
    case hostNotFound
    /// The host is there but nothing is listening — server is down or the
    /// port is wrong.
    case serverUnavailable
    case timedOut
    case server(code: String, message: String)
    case unexpectedStatus(Int)
    case decoding
    case fileTooLarge(limitMB: Int)
    case cancelled

    var errorDescription: String? { userMessage }

    /// Copy shown directly to the user. Always reassures that the original PDF
    /// is untouched where a conversion failed, per spec section 47.
    var userMessage: String {
        switch self {
        case .invalidURL:
            return "The backend address in Settings isn't a valid URL."
        case .notConfigured:
            return """
                No conversion server is set up yet. Open Settings and enter the \
                address of the server you're running.
                """
        case .offline:
            return "This device isn't connected to a network. Your original PDF was not modified."
        case .connectionLost:
            return """
                The connection to the server dropped before it finished. Try \
                again. Your original PDF was not modified.
                """
        case .hostNotFound:
            return """
                No server was found at that address. Check the address in \
                Settings for a typo.
                """
        case .serverUnavailable:
            // Without an address to go on, assume the app's own server, which
            // is what nearly everyone is using.
            return APIError.unreachableMessage(for: .builtIn)
        case .timedOut:
            return "The server took too long to respond. Your original PDF was not modified."
        case .server(_, let message):
            return message
        // Render answers 502/503 while the service restarts or deploys.
        case .unexpectedStatus(let status) where (500...599).contains(status):
            return """
                The conversion server is having trouble right now. Try again in \
                a few minutes. Your original PDF was not modified.
                """
        // A URLError code rather than an HTTP status: the request failed on
        // this side, so "the server returned" would be untrue.
        case .unexpectedStatus(let status) where status < 0:
            return """
                Something went wrong while reaching the conversion server. Try \
                again. Your original PDF was not modified.
                """
        case .unexpectedStatus(let status):
            return "The server returned an unexpected response (\(status)). Your original PDF was not modified."
        case .decoding:
            return "We couldn't read the server's response. Your original PDF was not modified."
        case .fileTooLarge(let limitMB):
            return "This PDF is larger than the \(limitMB)MB limit."
        case .cancelled:
            return "The conversion was cancelled."
        }
    }

    /// Transport-level hiccups worth silently re-polling through, as opposed to
    /// a definitive answer from the server. A job the backend reports as FAILED
    /// is *not* transient — it is a final answer and must surface immediately.
    var isTransient: Bool {
        switch self {
        case .offline, .connectionLost, .serverUnavailable, .timedOut, .unexpectedStatus:
            return true
        // A bad address or an unconfigured app will not fix itself by polling.
        case .server, .invalidURL, .notConfigured, .hostNotFound, .decoding,
             .fileTooLarge, .cancelled:
            return false
        }
    }
}
