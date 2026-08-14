import XCTest

/// Drives the whole user journey against a **live backend** using a PDF placed
/// in the app's Documents folder (visible in Files thanks to UIFileSharingEnabled).
///
/// Skipped automatically unless the backend is reachable, so the suite stays
/// green on machines that aren't running the server.
final class ConversionFlowUITests: XCTestCase {
    override func setUp() {
        super.setUp()
        continueAfterFailure = false
    }

    private func backendIsReachable() -> Bool {
        guard let url = URL(string: "http://localhost:8000/health") else { return false }
        var request = URLRequest(url: url)
        request.timeoutInterval = 3
        let semaphore = DispatchSemaphore(value: 0)
        var reachable = false
        URLSession.shared.dataTask(with: request) { _, response, _ in
            reachable = (response as? HTTPURLResponse)?.statusCode == 200
            semaphore.signal()
        }.resume()
        _ = semaphore.wait(timeout: .now() + 5)
        return reachable
    }

    func testConvertsAPDFEndToEndAndShowsRealQualityReport() throws {
        try XCTSkipUnless(backendIsReachable(), "backend not running on localhost:8000")

        let app = XCUIApplication()
        app.launch()

        app.buttons["Select PDF"].tap()

        // The document picker is out-of-process and localized, so navigate by
        // structure rather than by label: the browsing-mode tab bar's third tab
        // is always "Browse", and search finds the file without walking folders.
        let tabBar = app.tabBars["DOC.browsingModeTabBar"]
        XCTAssertTrue(tabBar.waitForExistence(timeout: 15), "document picker did not appear")
        let browseTab = tabBar.buttons.element(boundBy: 2)
        XCTAssertTrue(browseTab.waitForExistence(timeout: 5), "browse tab not found")
        browseTab.tap()

        // "On My iPhone" — identified by its icon so this doesn't depend on the
        // simulator's language.
        let onMyPhone = app.cells.containing(.image, identifier: "iphone").firstMatch
        XCTAssertTrue(onMyPhone.waitForExistence(timeout: 10), "'On My iPhone' location not found")
        onMyPhone.tap()

        let pdfCell = app.cells.matching(
            NSPredicate(format: "identifier BEGINSWITH 'simple_book'")
        ).firstMatch
        XCTAssertTrue(pdfCell.waitForExistence(timeout: 15), "test PDF not found in the document picker")
        pdfCell.tap()

        // Conversion settings screen
        XCTAssertTrue(app.staticTexts["Conversion quality"].waitForExistence(timeout: 15))
        XCTAssertTrue(app.staticTexts["Maximum Accuracy"].exists)

        app.buttons["Convert to EPUB"].tap()

        // Result screen — real numbers from the real backend.
        let completed = app.staticTexts["Conversion complete"]
        XCTAssertTrue(completed.waitForExistence(timeout: 120), "conversion did not complete")

        XCTAssertTrue(app.buttons["Preview EPUB"].exists)
        XCTAssertTrue(app.staticTexts["Pages"].exists)
        XCTAssertTrue(app.staticTexts["Chapters"].exists)
        XCTAssertTrue(app.staticTexts["EPUB3 validation"].exists)

        // The validation row must actually report a pass, not merely exist.
        XCTAssertTrue(app.staticTexts["Pass"].exists, "EPUBCheck validation did not pass")

        // AI must have stayed off for a normal conversion.
        XCTAssertTrue(app.staticTexts["None (fully local)"].exists, "conversion unexpectedly used an AI provider")
    }
}
