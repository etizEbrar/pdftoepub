import Foundation

enum ConversionMode: String, Codable, CaseIterable, Identifiable {
    case fast
    case balanced
    case maximumAccuracy = "maximum_accuracy"

    var id: String { rawValue }

    var title: String {
        switch self {
        case .fast: return "Fast"
        case .balanced: return "Balanced"
        case .maximumAccuracy: return "Maximum Accuracy"
        }
    }

    var subtitle: String {
        switch self {
        case .fast:
            return "Quickest conversion using deterministic processing only."
        case .balanced:
            return "A balance of speed and structural analysis."
        case .maximumAccuracy:
            return "Deepest layout, footnote, and structure analysis. Recommended."
        }
    }
}

enum JobStage: String, Codable {
    case uploaded = "UPLOADED"
    case analyzing = "ANALYZING"
    case extracting = "EXTRACTING"
    case structureAnalysis = "STRUCTURE_ANALYSIS"
    case aiReview = "AI_REVIEW"
    case buildingEPUB = "BUILDING_EPUB"
    case validating = "VALIDATING"
    case qualityCheck = "QUALITY_CHECK"
    case completed = "COMPLETED"
    case failed = "FAILED"

    var isTerminal: Bool { self == .completed || self == .failed }

    var displayName: String {
        switch self {
        case .uploaded: return "Uploaded"
        case .analyzing: return "Analyzing PDF"
        case .extracting: return "Extracting text"
        case .structureAnalysis: return "Reconstructing layout"
        case .aiReview: return "Reviewing structure"
        case .buildingEPUB: return "Building EPUB"
        case .validating: return "Validating EPUB"
        case .qualityCheck: return "Checking quality"
        case .completed: return "Completed"
        case .failed: return "Failed"
        }
    }

    /// The ordered stages shown as a checklist in the progress UI.
    static var pipelineStages: [JobStage] {
        [.analyzing, .extracting, .structureAnalysis, .aiReview, .buildingEPUB, .validating, .qualityCheck]
    }

    var sortIndex: Int {
        switch self {
        case .uploaded: return 0
        case .analyzing: return 1
        case .extracting: return 2
        case .structureAnalysis: return 3
        case .aiReview: return 4
        case .buildingEPUB: return 5
        case .validating: return 6
        case .qualityCheck: return 7
        case .completed: return 8
        case .failed: return 9
        }
    }
}

struct ConversionCreatedResponse: Codable {
    let id: String
    let status: JobStage
}

struct ConversionSummary: Codable {
    let id: String
    let status: JobStage
    let mode: ConversionMode
    let sourceFilename: String
    let errorCode: String?
    let errorMessage: String?

    enum CodingKeys: String, CodingKey {
        case id, status, mode
        case sourceFilename = "source_filename"
        case errorCode = "error_code"
        case errorMessage = "error_message"
    }
}

struct ConversionProgress: Codable {
    let id: String
    let status: JobStage
    let stageDetail: String
    let page: Int
    let totalPages: Int
    let percent: Int

    enum CodingKeys: String, CodingKey {
        case id, status, page, percent
        case stageDetail = "stage_detail"
        case totalPages = "total_pages"
    }
}

struct QualityReport: Codable, Equatable {
    let title: String?
    let author: String?
    let pageCount: Int
    let chapterCount: Int
    let headingCount: Int
    let paragraphCount: Int
    let footnoteCount: Int
    let imageCount: Int
    let tableCount: Int
    let wordCountSource: Int
    let wordCountEpub: Int
    let contentIntegrityRatio: Double
    let epubcheckPassed: Bool
    let epubcheckErrors: [String]
    let epubcheckWarnings: [String]
    let aiProviderUsed: String
    let aiBlocksReviewed: Int
    let qualityScore: Double

    enum CodingKeys: String, CodingKey {
        case title, author
        case pageCount = "page_count"
        case chapterCount = "chapter_count"
        case headingCount = "heading_count"
        case paragraphCount = "paragraph_count"
        case footnoteCount = "footnote_count"
        case imageCount = "image_count"
        case tableCount = "table_count"
        case wordCountSource = "word_count_source"
        case wordCountEpub = "word_count_epub"
        case contentIntegrityRatio = "content_integrity_ratio"
        case epubcheckPassed = "epubcheck_passed"
        case epubcheckErrors = "epubcheck_errors"
        case epubcheckWarnings = "epubcheck_warnings"
        case aiProviderUsed = "ai_provider_used"
        case aiBlocksReviewed = "ai_blocks_reviewed"
        case qualityScore = "quality_score"
    }
}

struct ConversionResult: Codable {
    let id: String
    let status: JobStage
    let qualityReport: QualityReport?
    let downloadURL: String?

    enum CodingKeys: String, CodingKey {
        case id, status
        case qualityReport = "quality_report"
        case downloadURL = "download_url"
    }
}

/// A locally-inspected PDF the user picked, before any upload happens.
struct SelectedDocument: Equatable {
    let url: URL
    let filename: String
    let byteCount: Int
    let pageCount: Int?
    let title: String?
    let author: String?
    let isEncrypted: Bool

    var formattedSize: String {
        ByteCountFormatter.string(fromByteCount: Int64(byteCount), countStyle: .file)
    }
}
