import XCTest

/// Captures screenshots of each stage as test attachments — useful for
/// reviewing the real UI without a device, and for spotting visual regressions.
final class ScreenshotCaptureTest: XCTestCase {
    private func attach(_ app: XCUIApplication, _ name: String) {
        let shot = XCTAttachment(screenshot: app.screenshot())
        shot.name = name
        shot.lifetime = .keepAlways
        add(shot)
    }

    func testCaptureConversionJourney() throws {
        let app = XCUIApplication()
        app.launch()
        attach(app, "01-home")

        app.buttons["Select PDF"].tap()
        let tabBar = app.tabBars["DOC.browsingModeTabBar"]
        try XCTSkipUnless(tabBar.waitForExistence(timeout: 15), "picker unavailable")
        tabBar.buttons.element(boundBy: 2).tap()

        let onMyPhone = app.cells.containing(.image, identifier: "iphone").firstMatch
        try XCTSkipUnless(onMyPhone.waitForExistence(timeout: 10), "location unavailable")
        onMyPhone.tap()

        let pdfCell = app.cells.matching(
            NSPredicate(format: "identifier BEGINSWITH 'simple_book'")
        ).firstMatch
        try XCTSkipUnless(pdfCell.waitForExistence(timeout: 15), "test PDF unavailable")
        pdfCell.tap()

        XCTAssertTrue(app.staticTexts["Conversion quality"].waitForExistence(timeout: 15))
        attach(app, "02-conversion-settings")

        app.buttons["Convert to EPUB"].tap()
        attach(app, "03-progress")

        XCTAssertTrue(app.staticTexts["Conversion complete"].waitForExistence(timeout: 120))
        attach(app, "04-result")

        app.buttons["Preview EPUB"].tap()
        sleep(4)
        attach(app, "05-epub-preview")
    }
}
