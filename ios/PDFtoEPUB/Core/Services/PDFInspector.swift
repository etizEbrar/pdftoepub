import Foundation
import PDFKit

enum PDFInspectionError: LocalizedError {
    case unreadable
    case encrypted
    case empty

    var errorDescription: String? {
        switch self {
        case .unreadable:
            return "We couldn't open this PDF. It may be damaged or in an unsupported format."
        case .encrypted:
            return "This PDF is password-protected. Remove the password and try again."
        case .empty:
            return "This PDF doesn't contain any pages."
        }
    }
}

/// Local, on-device inspection before anything is uploaded, so obviously
/// unusable files are rejected without a round trip (spec sections 6 and 55).
enum PDFInspector {
    static func inspect(url: URL) throws -> SelectedDocument {
        let needsScopedAccess = url.startAccessingSecurityScopedResource()
        defer { if needsScopedAccess { url.stopAccessingSecurityScopedResource() } }

        guard let document = PDFDocument(url: url) else {
            throw PDFInspectionError.unreadable
        }
        if document.isEncrypted && document.isLocked {
            throw PDFInspectionError.encrypted
        }
        guard document.pageCount > 0 else {
            throw PDFInspectionError.empty
        }

        let attributes = document.documentAttributes
        let fileAttributes = try? FileManager.default.attributesOfItem(atPath: url.path)
        let byteCount = (fileAttributes?[.size] as? NSNumber)?.intValue ?? 0

        return SelectedDocument(
            url: url,
            filename: url.lastPathComponent,
            byteCount: byteCount,
            pageCount: document.pageCount,
            title: (attributes?[PDFDocumentAttribute.titleAttribute] as? String)?.trimmedNonEmpty,
            author: (attributes?[PDFDocumentAttribute.authorAttribute] as? String)?.trimmedNonEmpty,
            isEncrypted: document.isEncrypted
        )
    }
}

extension String {
    var trimmedNonEmpty: String? {
        let trimmed = trimmingCharacters(in: .whitespacesAndNewlines)
        return trimmed.isEmpty ? nil : trimmed
    }
}
