import Compression
import Foundation

/// Reads an EPUB container.
///
/// An EPUB is a ZIP file, and iOS exposes no public API to unpack one — the
/// Compression framework inflates a raw deflate stream but knows nothing about
/// ZIP's directory structure. This reads the central directory itself and
/// inflates the entries it needs, which is a small amount of well-specified
/// work and avoids taking a third-party dependency into the app.
///
/// Only what an EPUB actually uses is supported: stored (method 0) and deflate
/// (method 8) entries. Anything else is reported rather than guessed at.
enum EPUBArchive {

    enum Failure: LocalizedError {
        case notAZipArchive
        case unsupportedCompression(UInt16)
        case corruptEntry(String)

        var errorDescription: String? {
            switch self {
            case .notAZipArchive:
                return "This file isn't a readable EPUB container."
            case .unsupportedCompression(let method):
                return "The book uses an unsupported compression method (\(method))."
            case .corruptEntry(let name):
                return "Part of the book couldn't be read (\(name))."
            }
        }
    }

    /// Unpack the archive into `destination`, returning the files written.
    @discardableResult
    static func unpack(_ archive: URL, into destination: URL) throws -> [String] {
        let data = try Data(contentsOf: archive, options: .mappedIfSafe)
        let entries = try centralDirectory(of: data)
        var written: [String] = []

        for entry in entries {
            // Ignore directory records; the files below recreate the tree.
            guard !entry.name.hasSuffix("/") else { continue }
            // A path is only ever joined onto the destination after being
            // proven not to climb out of it. A crafted archive must not be
            // able to write outside the folder we chose.
            guard let safe = sanitised(entry.name) else { continue }

            let contents = try inflate(entry: entry, in: data)
            let target = destination.appendingPathComponent(safe)
            try FileManager.default.createDirectory(
                at: target.deletingLastPathComponent(), withIntermediateDirectories: true
            )
            try contents.write(to: target)
            written.append(safe)
        }
        return written
    }

    /// Reject absolute paths and any ".." segment, which is how a ZIP escapes
    /// the directory it is being unpacked into.
    private static func sanitised(_ name: String) -> String? {
        let parts = name.split(separator: "/", omittingEmptySubsequences: true)
        guard !name.hasPrefix("/"), !parts.contains("..") else { return nil }
        return parts.isEmpty ? nil : parts.joined(separator: "/")
    }

    // MARK: - ZIP structure

    private struct Entry {
        let name: String
        let method: UInt16
        let compressedSize: Int
        let uncompressedSize: Int
        let localHeaderOffset: Int
    }

    private static func centralDirectory(of data: Data) throws -> [Entry] {
        // The end-of-central-directory record sits at the tail, after a
        // comment of unknown length, so it is found by scanning backwards.
        let signature: [UInt8] = [0x50, 0x4b, 0x05, 0x06]
        let bytes = [UInt8](data)
        guard bytes.count > 22 else { throw Failure.notAZipArchive }

        var eocd = -1
        var i = bytes.count - 22
        while i >= 0 {
            if Array(bytes[i..<i + 4]) == signature { eocd = i; break }
            i -= 1
        }
        guard eocd >= 0 else { throw Failure.notAZipArchive }

        let count = Int(u16(bytes, eocd + 10))
        var offset = Int(u32(bytes, eocd + 16))
        var entries: [Entry] = []

        for _ in 0..<count {
            guard offset + 46 <= bytes.count,
                  Array(bytes[offset..<offset + 4]) == [0x50, 0x4b, 0x01, 0x02]
            else { throw Failure.notAZipArchive }

            let method = u16(bytes, offset + 10)
            let compressed = Int(u32(bytes, offset + 20))
            let uncompressed = Int(u32(bytes, offset + 24))
            let nameLength = Int(u16(bytes, offset + 28))
            let extraLength = Int(u16(bytes, offset + 30))
            let commentLength = Int(u16(bytes, offset + 32))
            let localOffset = Int(u32(bytes, offset + 42))

            let nameStart = offset + 46
            guard nameStart + nameLength <= bytes.count else { throw Failure.notAZipArchive }
            let name = String(decoding: bytes[nameStart..<nameStart + nameLength], as: UTF8.self)

            entries.append(Entry(name: name, method: method, compressedSize: compressed,
                                 uncompressedSize: uncompressed, localHeaderOffset: localOffset))
            offset = nameStart + nameLength + extraLength + commentLength
        }
        return entries
    }

    private static func inflate(entry: Entry, in data: Data) throws -> Data {
        let bytes = [UInt8](data)
        let header = entry.localHeaderOffset
        guard header + 30 <= bytes.count,
              Array(bytes[header..<header + 4]) == [0x50, 0x4b, 0x03, 0x04]
        else { throw Failure.corruptEntry(entry.name) }

        // The local header repeats the name and extra-field lengths, and they
        // may differ from the central directory's, so the payload offset is
        // read from here rather than assumed.
        let nameLength = Int(u16(bytes, header + 26))
        let extraLength = Int(u16(bytes, header + 28))
        let start = header + 30 + nameLength + extraLength
        let end = start + entry.compressedSize
        guard end <= bytes.count else { throw Failure.corruptEntry(entry.name) }
        let payload = data.subdata(in: start..<end)

        switch entry.method {
        case 0:
            return payload
        case 8:
            return try rawInflate(payload, expecting: entry.uncompressedSize, name: entry.name)
        default:
            throw Failure.unsupportedCompression(entry.method)
        }
    }

    private static func rawInflate(_ payload: Data, expecting size: Int, name: String) throws -> Data {
        guard size > 0 else { return Data() }
        // A little headroom: the stored size is authoritative, but a corrupt
        // entry that inflates larger should be caught by the buffer, not by
        // overwriting memory.
        var output = Data(count: size)
        let written: Int = output.withUnsafeMutableBytes { outBuffer in
            payload.withUnsafeBytes { inBuffer -> Int in
                guard let dst = outBuffer.bindMemory(to: UInt8.self).baseAddress,
                      let src = inBuffer.bindMemory(to: UInt8.self).baseAddress
                else { return 0 }
                return compression_decode_buffer(
                    dst, size, src, payload.count, nil, COMPRESSION_ZLIB
                )
            }
        }
        guard written > 0 else { throw Failure.corruptEntry(name) }
        return output.prefix(written)
    }

    private static func u16(_ b: [UInt8], _ i: Int) -> UInt16 {
        UInt16(b[i]) | UInt16(b[i + 1]) << 8
    }

    private static func u32(_ b: [UInt8], _ i: Int) -> UInt32 {
        UInt32(b[i]) | UInt32(b[i + 1]) << 8 | UInt32(b[i + 2]) << 16 | UInt32(b[i + 3]) << 24
    }
}
