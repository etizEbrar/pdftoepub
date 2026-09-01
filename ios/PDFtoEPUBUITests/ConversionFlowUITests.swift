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

    /// Where the backend is, for this run.
    ///
    /// Defaults to localhost so the simulator suite behaves as before. Set
    /// `UITEST_BACKEND_URL` to point a *device* run at a machine on the network
    /// — on real hardware "localhost" is the phone itself, so without this the
    /// test can only ever skip.
    private var backendURLString: String {
        // Read from the test bundle's Info.plist rather than the environment:
        // a device run executes inside a runner app on the phone, and build
        // settings reach it reliably where an exported shell variable does not.
        // Set with INFOPLIST_KEY_UITestBackendURL=... on the xcodebuild command.
        if let configured = Bundle(for: Self.self)
            .object(forInfoDictionaryKey: "UITestBackendURL") as? String,
            Self.isRealValue(configured)
        {
            return configured
        }
        if let fromEnv = ProcessInfo.processInfo.environment["UITEST_BACKEND_URL"],
           !fromEnv.isEmpty
        {
            return fromEnv
        }
        return "http://localhost:8000"
    }

    /// True when this run was pointed at a specific backend, which is what tells
    /// the test it must configure the app rather than trust a built-in default.
    private var backendWasSuppliedForThisRun: Bool {
        let bundled = Bundle(for: Self.self)
            .object(forInfoDictionaryKey: "UITestBackendURL") as? String
        return Self.isRealValue(bundled ?? "")
            || Self.isRealValue(ProcessInfo.processInfo.environment["UITEST_BACKEND_URL"] ?? "")
    }

    /// When the environment variable is unset the build leaves the placeholder
    /// text in place rather than an empty string. Treating that as an address
    /// would turn every simulator run into a silent skip.
    private static func isRealValue(_ value: String) -> Bool {
        let trimmed = value.trimmingCharacters(in: .whitespaces)
        guard !trimmed.isEmpty else { return false }
        return !trimmed.contains("${") && !trimmed.contains("$(")
    }

    private func backendIsReachable() -> Bool {
        guard let url = URL(string: backendURLString + "/health") else { return false }
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

    /// Enters the backend address through Settings when the app doesn't already
    /// have a working one. No-op when the build already points somewhere usable.
    private func configureBackendIfNeeded(_ app: XCUIApplication) {
        guard backendWasSuppliedForThisRun else { return }

        app.buttons["Settings"].tap()
        let field = app.textFields["settings.backendAddress"]
        XCTAssertTrue(field.waitForExistence(timeout: 10), "backend address field not found")

        field.tap()
        // Clear whatever is there, then type the address for this run.
        if let existing = field.value as? String, !existing.isEmpty {
            field.press(forDuration: 1.0)
            if app.menuItems["Select All"].waitForExistence(timeout: 2) {
                app.menuItems["Select All"].tap()
            }
        }
        field.typeText(backendURLString)

        app.buttons["settings.testConnection"].tap()
        XCTAssertTrue(
            app.staticTexts["Connected (none)"].waitForExistence(timeout: 20)
                || app.staticTexts["Connected"].waitForExistence(timeout: 2),
            "the app could not reach \(backendURLString) from this device"
        )
        app.buttons["Done"].tap()
    }

    func testConvertsAPDFEndToEndAndShowsRealQualityReport() throws {
        try XCTSkipUnless(backendIsReachable(), "backend not reachable at \(backendURLString)")

        let app = XCUIApplication()
        app.launch()

        // A device run starts with no configured server (Release ships without
        // one), so set it through the real Settings screen — the same path a
        // user takes — before attempting a conversion.
        configureBackendIfNeeded(app)

        app.buttons["Select PDF"].tap()

        // The document picker is out-of-process and localized, so navigate by
        // structure rather than by label: the browsing-mode tab bar's third tab
        // is always "Browse", and search finds the file without walking folders.
        let tabBar = app.tabBars["DOC.browsingModeTabBar"]
        XCTAssertTrue(
            tabBar.waitForExistence(timeout: 15),
            """
            The document picker did not appear.

            This test needs a PDF the picker can reach. Reinstalling the app \
            wipes its container, so place one and run again:

              CONT=$(xcrun simctl get_app_container booted com.pdftoepub.app data)
              cp backend/tests/fixtures/simple_book.pdf "$CONT/Documents/"

            A backend must also be running on http://localhost:8000, or this \
            test skips rather than failing.
            """
        )
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
