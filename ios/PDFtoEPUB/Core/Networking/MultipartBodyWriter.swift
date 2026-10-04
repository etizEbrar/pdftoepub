import Foundation

/// Streams the multipart body to a temp file rather than building it in memory,
/// so uploading a 500+ page PDF doesn't spike memory (spec section 39/49).
enum MultipartBodyWriter {
    static func writeBody(
        fileURL: URL,
        filename: String,
        mode: ConversionMode,
        boundary: String,
        clientOCR: URL? = nil
    ) throws -> URL {
        let bodyURL = FileManager.default.temporaryDirectory
            .appendingPathComponent("upload-\(UUID().uuidString).multipart")
        FileManager.default.createFile(atPath: bodyURL.path, contents: nil)

        let handle = try FileHandle(forWritingTo: bodyURL)
        defer { try? handle.close() }

        func write(_ string: String) throws {
            guard let data = string.data(using: .utf8) else { return }
            try handle.write(contentsOf: data)
        }

        func copy(contentsOf source: URL) throws {
            let reader = try FileHandle(forReadingFrom: source)
            defer { try? reader.close() }
            while let chunk = try reader.read(upToCount: 1_048_576), !chunk.isEmpty {
                try handle.write(contentsOf: chunk)
            }
        }

        try write("--\(boundary)\r\n")
        try write("Content-Disposition: form-data; name=\"mode\"\r\n\r\n")
        try write("\(mode.rawValue)\r\n")

        try write("--\(boundary)\r\n")
        try write("Content-Disposition: form-data; name=\"file\"; filename=\"\(filename)\"\r\n")
        try write("Content-Type: application/pdf\r\n\r\n")
        try copy(contentsOf: fileURL)
        try write("\r\n")

        // The text this device recognised, streamed from disk for the same
        // reason the PDF is: a long scanned book's words and boxes are tens of
        // megabytes, and holding that in memory beside the upload is what the
        // streaming was introduced to avoid.
        if let clientOCR {
            try write("--\(boundary)\r\n")
            try write(
                "Content-Disposition: form-data; name=\"ocr\"; filename=\"client-ocr.json\"\r\n"
            )
            try write("Content-Type: application/json\r\n\r\n")
            try copy(contentsOf: clientOCR)
            try write("\r\n")
        }

        try write("--\(boundary)--\r\n")
        return bodyURL
    }
}
