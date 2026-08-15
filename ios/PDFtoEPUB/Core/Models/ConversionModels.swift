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

    // Added alongside OCR/table/formula/endnote/verse/RTL support. Defaulted so
    // the app still decodes a response from an older backend.
    let endnoteCount: Int
    let verseCount: Int
    let formulaCount: Int
    let imageFallbackCount: Int
    let rtlBlockCount: Int
    let ocrPageCount: Int
    let ocrMeanConfidence: Double?
    let contentIntegritySuspicious: Bool
    let contentIntegrityNotes: [String]

    // Structural quality, reported separately from EPUB validity: a valid EPUB
    // can still be a poor ebook, and the app must not present it as perfect.
    let footnotesLinked: Int
    let endnotesLinked: Int
    let unmatchedMarkerCount: Int
    let navigationEntryCount: Int
    let structureScore: Double
    let needsReview: Bool
    let reviewReasons: [String]

    // Local text repair of extraction/OCR defects.
    let textCorrections: Int
    let textCorrectionsRejected: Int
    let textCorrectionConfidence: Double
    let suspiciousPassages: Int
    let pagesNeedingTextReview: Int

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
        case endnoteCount = "endnote_count"
        case verseCount = "verse_count"
        case formulaCount = "formula_count"
        case imageFallbackCount = "image_fallback_count"
        case rtlBlockCount = "rtl_block_count"
        case ocrPageCount = "ocr_page_count"
        case ocrMeanConfidence = "ocr_mean_confidence"
        case contentIntegritySuspicious = "content_integrity_suspicious"
        case contentIntegrityNotes = "content_integrity_notes"
        case footnotesLinked = "footnotes_linked"
        case endnotesLinked = "endnotes_linked"
        case unmatchedMarkerCount = "unmatched_marker_count"
        case navigationEntryCount = "navigation_entry_count"
        case structureScore = "structure_score"
        case needsReview = "needs_review"
        case reviewReasons = "review_reasons"
        case textCorrections = "text_corrections"
        case textCorrectionsRejected = "text_corrections_rejected"
        case textCorrectionConfidence = "text_correction_confidence"
        case suspiciousPassages = "suspicious_passages"
        case pagesNeedingTextReview = "pages_needing_text_review"
    }

}

// Defined in an extension so the compiler still synthesises the memberwise
// initializer, which tests use to build fixtures.
extension QualityReport {
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        title = try c.decodeIfPresent(String.self, forKey: .title)
        author = try c.decodeIfPresent(String.self, forKey: .author)
        pageCount = try c.decode(Int.self, forKey: .pageCount)
        chapterCount = try c.decode(Int.self, forKey: .chapterCount)
        headingCount = try c.decode(Int.self, forKey: .headingCount)
        paragraphCount = try c.decode(Int.self, forKey: .paragraphCount)
        footnoteCount = try c.decode(Int.self, forKey: .footnoteCount)
        imageCount = try c.decode(Int.self, forKey: .imageCount)
        tableCount = try c.decode(Int.self, forKey: .tableCount)
        wordCountSource = try c.decode(Int.self, forKey: .wordCountSource)
        wordCountEpub = try c.decode(Int.self, forKey: .wordCountEpub)
        contentIntegrityRatio = try c.decode(Double.self, forKey: .contentIntegrityRatio)
        epubcheckPassed = try c.decode(Bool.self, forKey: .epubcheckPassed)
        epubcheckErrors = try c.decode([String].self, forKey: .epubcheckErrors)
        epubcheckWarnings = try c.decode([String].self, forKey: .epubcheckWarnings)
        aiProviderUsed = try c.decode(String.self, forKey: .aiProviderUsed)
        aiBlocksReviewed = try c.decode(Int.self, forKey: .aiBlocksReviewed)
        qualityScore = try c.decode(Double.self, forKey: .qualityScore)
        endnoteCount = try c.decodeIfPresent(Int.self, forKey: .endnoteCount) ?? 0
        verseCount = try c.decodeIfPresent(Int.self, forKey: .verseCount) ?? 0
        formulaCount = try c.decodeIfPresent(Int.self, forKey: .formulaCount) ?? 0
        imageFallbackCount = try c.decodeIfPresent(Int.self, forKey: .imageFallbackCount) ?? 0
        rtlBlockCount = try c.decodeIfPresent(Int.self, forKey: .rtlBlockCount) ?? 0
        ocrPageCount = try c.decodeIfPresent(Int.self, forKey: .ocrPageCount) ?? 0
        ocrMeanConfidence = try c.decodeIfPresent(Double.self, forKey: .ocrMeanConfidence)
        contentIntegritySuspicious =
            try c.decodeIfPresent(Bool.self, forKey: .contentIntegritySuspicious) ?? false
        contentIntegrityNotes =
            try c.decodeIfPresent([String].self, forKey: .contentIntegrityNotes) ?? []
        footnotesLinked = try c.decodeIfPresent(Int.self, forKey: .footnotesLinked) ?? 0
        endnotesLinked = try c.decodeIfPresent(Int.self, forKey: .endnotesLinked) ?? 0
        unmatchedMarkerCount = try c.decodeIfPresent(Int.self, forKey: .unmatchedMarkerCount) ?? 0
        navigationEntryCount = try c.decodeIfPresent(Int.self, forKey: .navigationEntryCount) ?? 0
        structureScore = try c.decodeIfPresent(Double.self, forKey: .structureScore) ?? 0
        needsReview = try c.decodeIfPresent(Bool.self, forKey: .needsReview) ?? false
        reviewReasons = try c.decodeIfPresent([String].self, forKey: .reviewReasons) ?? []
        textCorrections = try c.decodeIfPresent(Int.self, forKey: .textCorrections) ?? 0
        textCorrectionsRejected = try c.decodeIfPresent(Int.self, forKey: .textCorrectionsRejected) ?? 0
        textCorrectionConfidence = try c.decodeIfPresent(Double.self, forKey: .textCorrectionConfidence) ?? 1
        suspiciousPassages = try c.decodeIfPresent(Int.self, forKey: .suspiciousPassages) ?? 0
        pagesNeedingTextReview = try c.decodeIfPresent(Int.self, forKey: .pagesNeedingTextReview) ?? 0
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
