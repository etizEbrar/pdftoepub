import SwiftUI

struct ConversionProgressView: View {
    let document: SelectedDocument
    let progress: ConversionProgress?
    let onCancel: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: Theme.Spacing.loose) {
            header
            stageChecklist
            Spacer()
        }
        .padding(Theme.Spacing.regular)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color(.systemGroupedBackground))
        .safeAreaInset(edge: .bottom) {
            Button("Cancel", action: onCancel)
                .buttonStyle(SecondaryButtonStyle())
                .padding(Theme.Spacing.regular)
                .background(.bar)
        }
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: Theme.Spacing.tight) {
            Text(document.title ?? document.filename)
                .font(.headline)
                .lineLimit(2)

            // Only ever shows a percentage the backend actually reported —
            // never a synthetic animation (spec section 40).
            if let progress {
                ProgressView(value: Double(progress.percent), total: 100)
                    .tint(Color.accentColor)

                HStack {
                    Text(progress.stageDetail.isEmpty ? progress.status.displayName : progress.stageDetail)
                    Spacer()
                    if progress.totalPages > 0 && progress.page > 0 {
                        Text("Page \(progress.page) / \(progress.totalPages)")
                            .monospacedDigit()
                    }
                }
                .font(.footnote)
                .foregroundStyle(.secondary)
            } else {
                ProgressView()
                    .progressViewStyle(.linear)
                Text("Uploading…")
                    .font(.footnote)
                    .foregroundStyle(.secondary)
            }
        }
        .cardBackground()
        .accessibilityElement(children: .combine)
        .accessibilityLabel(accessibilitySummary)
    }

    private var accessibilitySummary: String {
        guard let progress else { return "Uploading document" }
        var parts = ["\(progress.percent) percent complete", progress.status.displayName]
        if progress.totalPages > 0 && progress.page > 0 {
            parts.append("page \(progress.page) of \(progress.totalPages)")
        }
        return parts.joined(separator: ", ")
    }

    private var stageChecklist: some View {
        VStack(alignment: .leading, spacing: 0) {
            ForEach(Array(JobStage.pipelineStages.enumerated()), id: \.element) { index, stage in
                HStack(spacing: Theme.Spacing.regular) {
                    stageIcon(for: stage)
                        .frame(width: 22)
                    Text(stage.displayName)
                        .font(.subheadline)
                        .foregroundStyle(state(for: stage) == .pending ? .secondary : .primary)
                    Spacer()
                }
                .padding(.vertical, 10)
                .accessibilityElement(children: .combine)
                .accessibilityLabel("\(stage.displayName), \(state(for: stage).accessibilityDescription)")

                if index < JobStage.pipelineStages.count - 1 {
                    Divider().padding(.leading, 38)
                }
            }
        }
        .padding(.horizontal, Theme.Spacing.regular)
        .background(Color(.secondarySystemGroupedBackground))
        .clipShape(RoundedRectangle(cornerRadius: Theme.Radius.card, style: .continuous))
    }

    private enum StageState {
        case done, active, pending

        var accessibilityDescription: String {
            switch self {
            case .done: return "completed"
            case .active: return "in progress"
            case .pending: return "not started"
            }
        }
    }

    private func state(for stage: JobStage) -> StageState {
        guard let progress else { return .pending }
        if progress.status == .completed { return .done }
        if progress.status.sortIndex > stage.sortIndex { return .done }
        if progress.status.sortIndex == stage.sortIndex { return .active }
        return .pending
    }

    @ViewBuilder
    private func stageIcon(for stage: JobStage) -> some View {
        switch state(for: stage) {
        case .done:
            Image(systemName: "checkmark.circle.fill")
                .foregroundStyle(Color.accentColor)
        case .active:
            ProgressView().controlSize(.small)
        case .pending:
            Image(systemName: "circle")
                .foregroundStyle(Color.secondary.opacity(0.5))
        }
    }
}
