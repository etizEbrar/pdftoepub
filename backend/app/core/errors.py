from __future__ import annotations


class ConversionError(Exception):
    """Base class for errors that should surface as a polished client-facing message.

    `code` is a stable machine-readable string the iOS app switches on to pick the
    right error illustration/copy; `user_message` is safe to show directly.
    """

    code: str = "conversion_failed"
    user_message: str = "We couldn't convert this document."

    def __init__(self, user_message: str | None = None, code: str | None = None):
        if user_message:
            self.user_message = user_message
        if code:
            self.code = code
        super().__init__(self.user_message)


class UnsupportedPDFError(ConversionError):
    code = "unsupported_pdf"
    user_message = "This file doesn't look like a PDF we can read."


class EncryptedPDFError(ConversionError):
    code = "encrypted_pdf"
    user_message = "This PDF is password-protected. Remove the password and try again."


class CorruptedPDFError(ConversionError):
    code = "corrupted_pdf"
    user_message = "This PDF appears to be damaged and couldn't be opened safely."


class FileTooLargeError(ConversionError):
    code = "file_too_large"
    user_message = "This PDF is larger than the current size limit."


class UnsupportedDocumentComplexityError(ConversionError):
    code = "unsupported_complexity"
    user_message = (
        "We couldn't safely reconstruct this document. Your original PDF was not modified."
    )


class EPUBValidationError(ConversionError):
    code = "epub_validation_failed"
    user_message = "The generated EPUB failed validation and was not returned."


class JobNotFoundError(ConversionError):
    code = "job_not_found"
    user_message = "This conversion job no longer exists."
