import Foundation

/// Free-space checks made before writing a converted book.
///
/// Without this, a conversion on a nearly full device runs to completion and
/// then fails while writing the EPUB, wasting the whole conversion and leaving a
/// partial file behind. Checking first turns that into a clear message before
/// any work is done.
enum DiskSpace {
    /// Bytes available for this app to write, or nil if the system won't say.
    ///
    /// Uses the *important* capacity: the space iOS will free up on demand for
    /// user-initiated work, which is what a conversion is.
    static func availableBytes(
        at url: URL = URL.documentsDirectory
    ) -> Int64? {
        let values = try? url.resourceValues(
            forKeys: [.volumeAvailableCapacityForImportantUsageKey]
        )
        return values?.volumeAvailableCapacityForImportantUsage
    }

    /// A conservative estimate of the room a conversion needs.
    ///
    /// The EPUB is normally a fraction of the PDF, but a scanned book keeps page
    /// images, so budget for the source size plus headroom rather than assuming
    /// the happy case.
    static func estimatedRequiredBytes(forSourceOfSize sourceBytes: Int64) -> Int64 {
        max(sourceBytes + minimumHeadroomBytes, minimumHeadroomBytes)
    }

    /// True when there is demonstrably not enough room. Returns false when the
    /// system declines to report capacity — refusing to convert on the strength
    /// of a missing reading would be worse than trying and failing.
    static func isInsufficient(forSourceOfSize sourceBytes: Int64) -> Bool {
        guard let available = availableBytes() else { return false }
        return available < estimatedRequiredBytes(forSourceOfSize: sourceBytes)
    }

    /// 50 MB of slack so the device isn't driven to literally zero.
    static let minimumHeadroomBytes: Int64 = 50 * 1024 * 1024
}
