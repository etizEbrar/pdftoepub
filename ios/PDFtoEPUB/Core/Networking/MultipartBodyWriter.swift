import Foundation

/// Streams the multipart body to a temp file rather than building it in memory,
/// so uploading a 500+ page PDF doesn't spike memory (spec section 39/49).
enum MultipartBodyWriter {
    static func writeBody(fileURL: URL, filename: String, mode: ConversionMode, boundary: String) throws -> URL {
        let bodyURL = FileManager.default.temporaryDirectory
            .appendingPathComponent("upload-\(UUID().uuidString).multipart")
        FileManager.default.createFile(atPath: bodyURL.path, contents: nil)

        let handle = try FileHandle(forWritingTo: bodyURL)
        defer { try? handle.close() }

        func write(_ string: String) throws {
            guard let data = string.data(using: .utf8) else { return }
            try handle.write(contentsOf: data)
        }

        try write("--\(boundary)\r\n")
        try write("Content-Disposition: form-data; name=\"mode\"\r\n\r\n")
        try write("\(mode.rawValue)\r\n")

        try write("--\(boundary)\r\n")
        try write("Content-Disposition: form-data; name=\"file\"; filename=\"\(filename)\"\r\n")
        try write("Content-Type: application/pdf\r\n\r\n")

        let source = try FileHandle(forReadingFrom: fileURL)
        defer { try? source.close() }
        while let chunk = try source.read(upToCount: 1_048_576), !chunk.isEmpty {
            try handle.write(contentsOf: chunk)
        }

        try write("\r\n--\(boundary)--\r\n")
        return bodyURL
    }
}
