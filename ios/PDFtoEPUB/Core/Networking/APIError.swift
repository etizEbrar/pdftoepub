import Foundation

/// A backend-reported failure. `code` mirrors the backend's stable error codes
/// (see `app/core/errors.py`) so the UI can pick copy without parsing prose.
struct APIErrorResponse: Codable {
    let code: String
    let message: String
}

enum APIError: LocalizedError, Equatable {
    /// The overwhelmingly common cause of a failed connection is that the app is
    /// pointed at "localhost" while running on a physical device, where that
    /// means the phone itself rather than the computer running the server. Say
    /// so, instead of blaming the user's internet.
    static let unreachableBackendMessage = """
        Couldn't reach the conversion server. If you're running it on your \
        computer, open Settings and enter that computer's address on your \
        network — on a real iPhone, "localhost" points at the phone itself.
        """

    case invalidURL
    /// No backend address has been configured yet.
    case notConfigured
    /// The device has no working network connection at all.
    case offline
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
        case .hostNotFound:
            return """
                No server was found at that address. Check the address in \
                Settings for a typo.
                """
        case .serverUnavailable:
            return APIError.unreachableBackendMessage
        case .timedOut:
            return "The server took too long to respond. Your original PDF was not modified."
        case .server(_, let message):
            return message
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
        case .offline, .serverUnavailable, .timedOut, .unexpectedStatus:
            return true
        // A bad address or an unconfigured app will not fix itself by polling.
        case .server, .invalidURL, .notConfigured, .hostNotFound, .decoding,
             .fileTooLarge, .cancelled:
            return false
        }
    }
}
