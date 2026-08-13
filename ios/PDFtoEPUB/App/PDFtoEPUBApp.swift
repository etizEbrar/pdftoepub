import SwiftUI

@main
struct PDFtoEPUBApp: App {
    @State private var settings = AppSettings()

    var body: some Scene {
        WindowGroup {
            HomeView(viewModel: ConversionViewModel(settings: settings))
                .environment(settings)
        }
    }
}
