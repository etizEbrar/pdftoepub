import Foundation

/// A backend-reported failure. `code` mirrors the backend's stable error codes
/// (see `app/core/errors.py`) so the UI can pick copy without parsing prose.
struct APIErrorResponse: Codable {
    let code: String
    let message: String
}

enum APIError: LocalizedError, Equatable {
    case invalidURL
    case notConnected
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
        case .notConnected:
            return "You appear to be offline. Check your connection and try again."
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

    var isRetryable: Bool {
        switch self {
        case .notConnected, .timedOut, .unexpectedStatus, .server:
            return true
        case .invalidURL, .decoding, .fileTooLarge, .cancelled:
            return false
        }
    }
}
