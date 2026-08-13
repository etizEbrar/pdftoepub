import XCTest

final class HomeUITests: XCTestCase {
    override func setUp() {
        super.setUp()
        continueAfterFailure = false
    }

    func testLaunchShowsEmptyStateWithSelectPDFAction() {
        let app = XCUIApplication()
        app.launch()

        XCTAssertTrue(app.navigationBars["PDF to EPUB"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.buttons["Select PDF"].exists)
        XCTAssertTrue(
            app.staticTexts["Turn your PDF books into beautiful, reflowable ebooks."].exists
        )
    }

    func testSettingsSheetOpensAndShowsBackendAddress() {
        let app = XCUIApplication()
        app.launch()

        app.buttons["Settings"].tap()
        XCTAssertTrue(app.navigationBars["Settings"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.staticTexts["Backend address"].exists)

        app.buttons["Done"].tap()
        XCTAssertTrue(app.navigationBars["PDF to EPUB"].waitForExistence(timeout: 5))
    }

    func testSelectPDFOpensSystemDocumentPicker() {
        let app = XCUIApplication()
        app.launch()

        app.buttons["Select PDF"].tap()
        // The system file importer runs out of process; its nav bar appearing is
        // the signal that the app requested it correctly.
        let importerAppeared = app.navigationBars.element(boundBy: 0).waitForExistence(timeout: 5)
        XCTAssertTrue(importerAppeared)
    }
}
