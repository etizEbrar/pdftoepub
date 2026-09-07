import XCTest

/// Captures screenshots of each stage as test attachments — the App Store
/// listing needs them, and they catch visual regressions no assertion would.
///
/// Every precondition below fails rather than skips. Skipping produced a green
/// run that quietly emitted one screenshot instead of five, which is worse than
/// a red one: the missing frames are only noticed at submission time.
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
        XCTAssertTrue(
            tabBar.waitForExistence(timeout: 15),
            "the document picker did not appear"
        )
        tabBar.buttons.element(boundBy: 2).tap()

        let onMyPhone = app.cells.containing(.image, identifier: "iphone").firstMatch
        XCTAssertTrue(
            onMyPhone.waitForExistence(timeout: 10),
            "the \"On My iPhone\" location did not appear in the picker"
        )
        onMyPhone.tap()

        // "On My iPhone" lists *folders*, one per app, so the file is a level
        // down inside this app's own container. Files remembers the last
        // directory you browsed, so on a simulator that has been here before
        // the PDF is already on screen and there is nothing to descend into —
        // hence trying the file first and only then the folder.
        let pdfCell = app.cells.matching(
            NSPredicate(format: "identifier BEGINSWITH 'simple_book'")
        ).firstMatch
        if !pdfCell.waitForExistence(timeout: 5) {
            let appFolder = app.cells.matching(
                NSPredicate(format: "identifier CONTAINS 'PDF to EPUB'")
            ).firstMatch
            XCTAssertTrue(
                appFolder.waitForExistence(timeout: 15),
                "neither the PDF nor the app's folder appeared under On My iPhone"
            )
            appFolder.tap()
        }
        XCTAssertTrue(
            pdfCell.waitForExistence(timeout: 40),
            """
            simple_book.pdf is not in the app's Documents folder.

            Running the tests reinstalls the app, which wipes its container, so
            the fixture has to be placed after the install and the run done with
            test-without-building. scripts/capture_screenshots.sh does that.
            """
        )
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
