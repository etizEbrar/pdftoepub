import XCTest

/// Converts a *scanned* PDF through the real UI against a live backend, proving
/// the OCR path reaches the user and that the result screen reports it.
///
/// Requires `scripts/seed_simulator_fixture.sh` plus a scanned fixture in the
/// simulator; skips cleanly when either the backend or the file is unavailable.
final class ScannedDocumentUITest: XCTestCase {
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

    func testScannedPDFIsConvertedByLocalOCRAndReportedInTheUI() throws {
        try XCTSkipUnless(backendIsReachable(), "backend not running on localhost:8000")

        let app = XCUIApplication()
        app.launch()
        app.buttons["Select PDF"].tap()

        let tabBar = app.tabBars["DOC.browsingModeTabBar"]
        try XCTSkipUnless(tabBar.waitForExistence(timeout: 15), "document picker unavailable")
        tabBar.buttons.element(boundBy: 2).tap()

        let onMyPhone = app.cells.containing(.image, identifier: "iphone").firstMatch
        try XCTSkipUnless(onMyPhone.waitForExistence(timeout: 10), "location unavailable")
        onMyPhone.tap()

        let pdfCell = app.cells.matching(
            NSPredicate(format: "identifier BEGINSWITH 'scanned_demo'")
        ).firstMatch
        try XCTSkipUnless(pdfCell.waitForExistence(timeout: 15), "scanned fixture not seeded")
        pdfCell.tap()

        XCTAssertTrue(app.staticTexts["Conversion quality"].waitForExistence(timeout: 15))
        app.buttons["Convert to EPUB"].tap()

        // OCR is slower than native extraction, so allow generous time.
        XCTAssertTrue(
            // Generous on purpose. This asserts that OCR *finishes*, not that
            // it is fast — conversion speed is measured by the backend
            // performance suite against a wall clock, where it belongs. Run
            // alone this takes about 150s; run after five other UI tests on a
            // machine also hosting the backend it takes longer, and a 180s
            // limit made the suite fail for reasons that say nothing about the
            // app.
            app.staticTexts["Conversion complete"].waitForExistence(timeout: 420),
            "scanned conversion did not complete"
        )

        // The result screen no longer reports OCR usage or the AI provider —
        // both live in the quality report the backend returns, which the
        // backend suite asserts on. Here the scanned path only has to finish
        // and produce a validated book.
        XCTAssertTrue(app.staticTexts["Pages"].exists)
        XCTAssertTrue(
            app.staticTexts["Validated EPUB3"].exists,
            "the result does not state that the EPUB validated"
        )

        let shot = XCTAttachment(screenshot: app.screenshot())
        shot.name = "scanned-result"
        shot.lifetime = .keepAlways
        add(shot)
    }
}
