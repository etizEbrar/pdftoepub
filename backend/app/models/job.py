from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class ConversionMode(str, Enum):
    FAST = "fast"
    BALANCED = "balanced"
    MAXIMUM_ACCURACY = "maximum_accuracy"


class JobStage(str, Enum):
    UPLOADED = "UPLOADED"
    ANALYZING = "ANALYZING"
    EXTRACTING = "EXTRACTING"
    STRUCTURE_ANALYSIS = "STRUCTURE_ANALYSIS"
    AI_REVIEW = "AI_REVIEW"
    BUILDING_EPUB = "BUILDING_EPUB"
    VALIDATING = "VALIDATING"
    QUALITY_CHECK = "QUALITY_CHECK"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


TERMINAL_STAGES = {JobStage.COMPLETED, JobStage.FAILED}

# Ordered list used to compute a monotonic overall percent from the current stage.
STAGE_ORDER = [
    JobStage.UPLOADED,
    JobStage.ANALYZING,
    JobStage.EXTRACTING,
    JobStage.STRUCTURE_ANALYSIS,
    JobStage.AI_REVIEW,
    JobStage.BUILDING_EPUB,
    JobStage.VALIDATING,
    JobStage.QUALITY_CHECK,
    JobStage.COMPLETED,
]


@dataclass
class QualityReport:
    title: str | None = None
    author: str | None = None
    page_count: int = 0
    chapter_count: int = 0
    heading_count: int = 0
    paragraph_count: int = 0
    footnote_count: int = 0
    image_count: int = 0
    table_count: int = 0
    word_count_source: int = 0
    word_count_epub: int = 0
    content_integrity_ratio: float = 0.0
    epubcheck_passed: bool = False
    epubcheck_errors: list[str] = field(default_factory=list)
    epubcheck_warnings: list[str] = field(default_factory=list)
    ai_provider_used: str = "none"
    ai_blocks_reviewed: int = 0
    quality_score: float = 0.0

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "author": self.author,
            "page_count": self.page_count,
            "chapter_count": self.chapter_count,
            "heading_count": self.heading_count,
            "paragraph_count": self.paragraph_count,
            "footnote_count": self.footnote_count,
            "image_count": self.image_count,
            "table_count": self.table_count,
            "word_count_source": self.word_count_source,
            "word_count_epub": self.word_count_epub,
            "content_integrity_ratio": self.content_integrity_ratio,
            "epubcheck_passed": self.epubcheck_passed,
            "epubcheck_errors": self.epubcheck_errors,
            "epubcheck_warnings": self.epubcheck_warnings,
            "ai_provider_used": self.ai_provider_used,
            "ai_blocks_reviewed": self.ai_blocks_reviewed,
            "quality_score": self.quality_score,
        }


@dataclass
class Job:
    job_id: str
    source_filename: str
    mode: ConversionMode
    stage: JobStage = JobStage.UPLOADED
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    current_page: int = 0
    total_pages: int = 0
    stage_detail: str = ""
    error_code: str | None = None
    error_message: str | None = None
    upload_path: str | None = None
    epub_path: str | None = None
    quality_report: QualityReport | None = None

    def percent(self) -> int:
        if self.stage == JobStage.COMPLETED:
            return 100
        if self.stage == JobStage.FAILED:
            return 0
        try:
            idx = STAGE_ORDER.index(self.stage)
        except ValueError:
            idx = 0
        base = int((idx / (len(STAGE_ORDER) - 1)) * 100)
        # Within EXTRACTING/STRUCTURE_ANALYSIS, refine using page progress.
        if self.total_pages and self.stage in (JobStage.EXTRACTING, JobStage.STRUCTURE_ANALYSIS):
            stage_span = 100 // (len(STAGE_ORDER) - 1)
            within = int((self.current_page / self.total_pages) * stage_span)
            base = min(base + within, 100)
        return max(0, min(base, 100))
