import XCTest
@testable import PDFtoEPUB

/// Guards the rule that a shipped build must never point at a machine only the
/// developer has. These are the checks that stop a localhost default from
/// reaching the App Store.
final class BackendEnvironmentTests: XCTestCase {

    // MARK: - Private address detection

    func testLoopbackAddressesAreRecognisedAsPrivate() {
        for host in ["http://localhost:8000", "http://127.0.0.1:8000", "http://[::1]:8000"] {
            let url = URL(string: host)!
            XCTAssertTrue(BackendEnvironment.isPrivateAddress(url), "\(host) must count as private")
        }
    }

    func testRFC1918RangesAreRecognisedAsPrivate() {
        let privateHosts = [
            "http://192.168.1.10:8000",
            "http://10.0.0.5:8000",
            "http://172.16.0.1:8000",
            "http://172.31.255.254:8000",
            "http://mac-mini.local:8000"
        ]
        for host in privateHosts {
            XCTAssertTrue(
                BackendEnvironment.isPrivateAddress(URL(string: host)!),
                "\(host) must count as private"
            )
        }
    }

    /// 172.15 and 172.32 sit outside the reserved block; treating them as
    /// private would wrongly reject a legitimate public server.
    func testAddressesOutsideThePrivateRangesAreNotPrivate() {
        let publicHosts = [
            "https://convert.example.com",
            "http://172.15.0.1:8000",
            "http://172.32.0.1:8000",
            "http://203.0.113.10:8000"
        ]
        for host in publicHosts {
            XCTAssertFalse(
                BackendEnvironment.isPrivateAddress(URL(string: host)!),
                "\(host) must not count as private"
            )
        }
    }

    // MARK: - Validation

    func testEmptyAddressReportsSetupRatherThanError() {
        XCTAssertEqual(BackendEnvironment.validate(""), .empty)
        XCTAssertEqual(BackendEnvironment.validate("   "), .empty)
    }

    func testMalformedAddressesAreRejected() {
        XCTAssertEqual(BackendEnvironment.validate("not a url"), .malformed)
        XCTAssertEqual(BackendEnvironment.validate("192.168.1.10:8000"), .malformed,
                       "a bare host:port has no scheme and must not be accepted silently")
    }

    func testNonHTTPSchemesAreRejected() {
        XCTAssertEqual(BackendEnvironment.validate("ftp://example.com"), .unsupportedScheme)
    }

    func testValidHTTPSAddressIsAccepted() {
        XCTAssertNil(BackendEnvironment.validate("https://convert.example.com"))
    }

    /// The app's model is that the user runs the server, usually on their own
    /// network. Entering a LAN address must work in every configuration —
    /// including the shipped one.
    func testPrivateHTTPAddressesAreAcceptedInEveryConfiguration() {
        XCTAssertNil(BackendEnvironment.validate("http://192.168.1.10:8000"))
        XCTAssertNil(BackendEnvironment.validate("http://localhost:8000"))
        XCTAssertNil(BackendEnvironment.validate("http://mac-mini.local:8000"))
    }

    /// Sending someone's book across the internet unencrypted is not acceptable,
    /// even though the same scheme is fine on their own LAN.
    func testPlainHTTPToAPublicHostIsRejected() {
        XCTAssertEqual(BackendEnvironment.validate("http://convert.example.com"), .insecureScheme)
        XCTAssertNil(BackendEnvironment.validate("https://convert.example.com"))
    }

    /// The shipped Info.plist carries an empty PRODUCTION_BACKEND_URL because no
    /// backend is deployed. Whatever it holds, the built-in default must never
    /// be an address only the developer can reach.
    func testTheBuiltInDefaultIsNeverAPrivateAddressInRelease() {
        #if DEBUG
        XCTAssertEqual(BackendEnvironment.defaultBaseURLString, "http://localhost:8000")
        XCTAssertFalse(BackendEnvironment.requiresUserSuppliedAddress)
        #else
        if let fallback = BackendEnvironment.defaultBaseURLString {
            let url = URL(string: fallback)
            XCTAssertNotNil(url)
            XCTAssertFalse(
                BackendEnvironment.isPrivateAddress(url!),
                "a Release build must not ship a private address as its default"
            )
        }
        #endif
    }

    // MARK: - Settings integration

    func testEveryIssueHasNonEmptyUserFacingCopy() {
        let issues: [BackendAddressIssue] = [
            .empty, .malformed, .unsupportedScheme, .insecureScheme
        ]
        let messages = issues.map(\.message)
        XCTAssertEqual(Set(messages).count, issues.count, "each issue needs its own explanation")
        XCTAssertFalse(messages.contains(where: \.isEmpty))
    }

    func testSettingsReportsSetupNeededWhenAddressIsBlank() {
        let settings = AppSettings()
        let original = settings.baseURLString
        defer { settings.baseURLString = original }

        settings.baseURLString = ""
        XCTAssertTrue(settings.needsBackendSetup)
        XCTAssertNil(settings.baseURL)
        XCTAssertEqual(settings.addressIssue, .empty)
    }

    func testSettingsAcceptsAValidAddress() {
        let settings = AppSettings()
        let original = settings.baseURLString
        defer { settings.baseURLString = original }

        settings.baseURLString = "https://convert.example.com"
        XCTAssertFalse(settings.needsBackendSetup)
        XCTAssertNil(settings.addressIssue)
        XCTAssertEqual(settings.baseURL?.host, "convert.example.com")
    }
}

/// The privacy manifest declares that this app reads disk space, so that has to
/// be a true statement about the shipped binary.
final class DiskSpaceTests: XCTestCase {
    func testTheDeviceReportsAvailableCapacity() {
        let available = DiskSpace.availableBytes()
        XCTAssertNotNil(available, "the volume should report important-usage capacity")
        XCTAssertGreaterThan(available ?? 0, 0)
    }

    func testRequiredSpaceAlwaysLeavesHeadroom() {
        let required = DiskSpace.estimatedRequiredBytes(forSourceOfSize: 0)
        XCTAssertGreaterThanOrEqual(required, DiskSpace.minimumHeadroomBytes)
    }

    func testRequiredSpaceGrowsWithTheSourceDocument() {
        let small = DiskSpace.estimatedRequiredBytes(forSourceOfSize: 1_000_000)
        let large = DiskSpace.estimatedRequiredBytes(forSourceOfSize: 200_000_000)
        XCTAssertGreaterThan(large, small)
    }

    /// A normal book on a working device must not be blocked.
    func testATypicalBookIsNotReportedAsTooLargeForTheDisk() {
        XCTAssertFalse(DiskSpace.isInsufficient(forSourceOfSize: 5_000_000))
    }

    /// An absurd request must be refused, proving the check is live rather than
    /// a function that always returns false.
    func testAnImpossiblyLargeDocumentIsRefused() {
        let available = DiskSpace.availableBytes() ?? 0
        XCTAssertTrue(
            DiskSpace.isInsufficient(forSourceOfSize: available + 1),
            "a document larger than the free space must be refused"
        )
    }
}

/// Guards the dev/production split once a real backend exists.
///
/// Filling in PRODUCTION_BACKEND_URL used to change Debug behaviour too, because
/// the configured URL was consulted before the Debug default. Every local run
/// and every test would then have driven the live Render service.
final class BackendEnvironmentSeparationTests: XCTestCase {

    func testTheProductionURLIsConfiguredAndUsable() {
        let configured = Bundle(for: type(of: self))
            .object(forInfoDictionaryKey: "PRODUCTION_BACKEND_URL") as? String
        // The test bundle has its own plist; read the app's through the class
        // it ships with instead.
        let appConfigured = Bundle(for: AppSettings.self)
            .object(forInfoDictionaryKey: "PRODUCTION_BACKEND_URL") as? String
        let value = (appConfigured ?? configured ?? "")
            .trimmingCharacters(in: .whitespacesAndNewlines)

        guard !value.isEmpty else {
            return  // no backend configured in this build; nothing to assert
        }
        XCTAssertNil(
            BackendEnvironment.validate(value),
            "the configured production URL is not one the app would accept"
        )
        let url = URL(string: value)
        XCTAssertNotNil(url)
        XCTAssertEqual(url?.scheme, "https", "a shipped backend must be https")
        XCTAssertFalse(
            BackendEnvironment.isPrivateAddress(url!),
            "a shipped backend must not be a private address"
        )
    }

    #if DEBUG
    func testDebugStillDefaultsToLocalhostEvenWithAProductionURLConfigured() {
        XCTAssertEqual(
            BackendEnvironment.defaultBaseURLString, "http://localhost:8000",
            "a debug build is pointing at the production backend"
        )
    }
    #endif
}

extension BackendEnvironmentSeparationTests {
    #if DEBUG
    /// The Settings screen hides the address field when the build manages the
    /// backend. In development it must stay visible and editable, or there is no
    /// way to point a debug build at a local server.
    func testDevelopmentAlwaysLetsTheAddressBeChanged() {
        XCTAssertFalse(
            BackendEnvironment.isManagedByBuild,
            "a debug build is hiding the backend address field"
        )
        XCTAssertFalse(BackendEnvironment.requiresUserSuppliedAddress)
    }
    #endif
}
