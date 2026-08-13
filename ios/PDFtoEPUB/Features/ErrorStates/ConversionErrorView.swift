import SwiftUI

struct ConversionErrorView: View {
    let failure: ConversionViewModel.ConversionFailure
    let onRetry: () -> Void
    let onChooseDifferent: () -> Void

    var body: some View {
        VStack(spacing: Theme.Spacing.loose) {
            Spacer()

            Image(systemName: iconName)
                .font(.system(size: 48, weight: .light))
                .foregroundStyle(.secondary)
                .accessibilityHidden(true)

            VStack(spacing: Theme.Spacing.tight) {
                Text(headline)
                    .font(.title3.weight(.semibold))
                    .multilineTextAlignment(.center)

                Text(failure.message)
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
                    .multilineTextAlignment(.center)
                    .fixedSize(horizontal: false, vertical: true)

                Text("Your original PDF was not modified.")
                    .font(.footnote)
                    .foregroundStyle(.secondary)
                    .padding(.top, 4)
            }
            .padding(.horizontal, Theme.Spacing.loose)

            Spacer()

            VStack(spacing: Theme.Spacing.tight) {
                if failure.isRetryable {
                    Button("Try again", action: onRetry)
                        .buttonStyle(PrimaryButtonStyle())
                }
                Button("Choose a different PDF", action: onChooseDifferent)
                    .buttonStyle(failure.isRetryable ? AnyButtonStyle(SecondaryButtonStyle()) : AnyButtonStyle(PrimaryButtonStyle()))
            }
            .padding(.horizontal, Theme.Spacing.regular)
            .padding(.bottom, Theme.Spacing.section)
        }
        .frame(maxWidth: .infinity)
        .background(Color(.systemGroupedBackground))
        .accessibilityElement(children: .contain)
    }

    /// Maps the backend's stable error codes (app/core/errors.py) to copy.
    private var headline: String {
        switch failure.code {
        case "encrypted_pdf": return "This PDF is locked"
        case "corrupted_pdf", "unsupported_pdf", "invalid_pdf": return "We can't read this PDF"
        case "file_too_large": return "This PDF is too large"
        case "unsupported_complexity": return "We couldn't safely reconstruct this document"
        case "epub_validation_failed": return "The EPUB didn't pass validation"
        case "network", "invalid_url": return "Connection problem"
        default: return "Conversion failed"
        }
    }

    private var iconName: String {
        switch failure.code {
        case "encrypted_pdf": return "lock.doc"
        case "file_too_large": return "doc.badge.ellipsis"
        case "network", "invalid_url": return "wifi.exclamationmark"
        case "epub_validation_failed": return "exclamationmark.triangle"
        default: return "doc.questionmark"
        }
    }
}

/// Lets the secondary action switch between primary/secondary styling depending
/// on whether a retry button is also present.
private struct AnyButtonStyle: ButtonStyle {
    private let makeBodyClosure: (Configuration) -> AnyView

    init<S: ButtonStyle>(_ style: S) {
        makeBodyClosure = { configuration in
            AnyView(style.makeBody(configuration: configuration))
        }
    }

    func makeBody(configuration: Configuration) -> some View {
        makeBodyClosure(configuration)
    }
}
