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

    // MARK: - Where an address points

    func testLoopbackIsTheDeviceItself() {
        let loopback = [
            "http://localhost:8000", "http://127.0.0.1:8000", "http://[::1]:8000",
            "http://0.0.0.0:8000"
        ]
        for address in loopback {
            XCTAssertTrue(BackendEnvironment.isLoopback(URL(string: address)!), address)
        }
        let elsewhere = [
            "http://192.168.1.10:8000", "http://mac-mini.local:8000",
            "https://convert.example.com"
        ]
        for address in elsewhere {
            XCTAssertFalse(BackendEnvironment.isLoopback(URL(string: address)!), address)
        }
    }

    func testEachKindOfAddressIsRecognised() {
        let builtIn = "https://pdftoepub-backend.onrender.com"
        func kind(_ address: String) -> BackendAddressKind {
            BackendEnvironment.kind(of: URL(string: address)!, builtIn: builtIn)
        }
        XCTAssertEqual(kind("https://pdftoepub-backend.onrender.com"), .builtIn)
        XCTAssertEqual(kind("https://PDFtoEPUB-backend.onrender.com/"), .builtIn)
        XCTAssertEqual(kind("http://localhost:8000"), .loopback)
        XCTAssertEqual(kind("http://192.168.1.10:8000"), .localNetwork)
        XCTAssertEqual(kind("http://mac-mini.local:8000"), .localNetwork)
        XCTAssertEqual(kind("https://gone.trycloudflare.com"), .other)
    }

    /// A debug build's own address is localhost. On a phone what matters is
    /// what localhost means there, not that it is the default.
    func testLoopbackWinsEvenWhenItIsTheBuiltInAddress() {
        let localhost = "http://localhost:8000"
        XCTAssertEqual(
            BackendEnvironment.kind(of: URL(string: localhost)!, builtIn: localhost),
            .loopback
        )
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

/// Recovering from an address that has stopped existing.
///
/// A real session ended here: the app was pointed at a temporary Cloudflare
/// tunnel, the tunnel was shut down when the session that created it ended,
/// and from then on every conversion failed with "Can't reach the server"
/// while the app's own backend was up the whole time. Nothing on screen named
/// the address being tried, and the reset lived inside Settings.
final class StaleAddressRecoveryTests: XCTestCase {

    private var defaults: UserDefaults!

    override func setUp() {
        super.setUp()
        defaults = UserDefaults.standard
        defaults.removeObject(forKey: "backend.baseURL")
    }

    override func tearDown() {
        defaults.removeObject(forKey: "backend.baseURL")
        super.tearDown()
    }

    func testAFreshInstallIsNotTreatedAsAnOverride() {
        let settings = AppSettings()
        XCTAssertFalse(
            settings.isOverridingBuiltInAddress,
            "the built-in address must not offer to reset to itself"
        )
    }

    func testATunnelAddressCountsAsAnOverride() {
        let settings = AppSettings()
        settings.baseURLString = "https://conservation-organization.trycloudflare.com"
        XCTAssertTrue(settings.isOverridingBuiltInAddress)
    }

    func testResettingRestoresTheBuiltInAddress() {
        let settings = AppSettings()
        settings.baseURLString = "https://something-that-is-gone.trycloudflare.com"
        settings.resetToBuiltInAddress()

        XCTAssertEqual(settings.baseURLString, BackendEnvironment.defaultBaseURLString ?? "")
        XCTAssertFalse(settings.isOverridingBuiltInAddress)
    }

    func testTheResetSurvivesBeingReadBackFromDisk() {
        /// The override is persisted, so the reset has to be too — otherwise
        /// the dead address returns on the next launch.
        let settings = AppSettings()
        settings.baseURLString = "https://gone.trycloudflare.com"
        settings.resetToBuiltInAddress()

        let reloaded = AppSettings()
        XCTAssertEqual(reloaded.baseURLString, BackendEnvironment.defaultBaseURLString ?? "")
    }

    func testWhitespaceAroundAPastedAddressIsNotAnOverride() throws {
        /// Pasting from a terminal brings a trailing newline with it.
        let builtIn = try XCTUnwrap(
            BackendEnvironment.defaultBaseURLString,
            "this build has no built-in address"
        )
        let settings = AppSettings()
        settings.baseURLString = "  \(builtIn)\n"
        XCTAssertFalse(settings.isOverridingBuiltInAddress)
    }
}

/// Keeping one build's address from outliving it.
///
/// A debug build left localhost on disk, because putting the default back — the
/// reset, and every test's cleanup — stored it as if a user had typed it. An App
/// Store build installed over it would read that back, prefer it to its own
/// server, and fail every conversion with "Can't reach the server"; 1.0 also
/// hid the field that could have changed it.
final class DevelopmentAddressResidueTests: XCTestCase {

    private var defaults: UserDefaults!

    override func setUp() {
        super.setUp()
        defaults = UserDefaults.standard
        defaults.removeObject(forKey: "backend.baseURL")
    }

    override func tearDown() {
        defaults.removeObject(forKey: "backend.baseURL")
        super.tearDown()
    }

    /// The cleanup every settings test does.
    func testPuttingTheBuiltInAddressBackStoresNothing() throws {
        _ = try XCTUnwrap(BackendEnvironment.defaultBaseURLString, "this build has no built-in address")
        let settings = AppSettings()
        let original = settings.baseURLString
        settings.baseURLString = "https://convert.example.com"
        settings.baseURLString = original

        XCTAssertNil(
            defaults.object(forKey: "backend.baseURL"),
            "the build's own address was stored as though the user had chosen it"
        )
    }

    func testResettingStoresNothing() throws {
        _ = try XCTUnwrap(BackendEnvironment.defaultBaseURLString, "this build has no built-in address")
        let settings = AppSettings()
        settings.baseURLString = "https://gone.trycloudflare.com"
        settings.resetToBuiltInAddress()

        XCTAssertNil(defaults.object(forKey: "backend.baseURL"))
    }

    func testAnAddressTheUserChoseIsStillRemembered() {
        let settings = AppSettings()
        settings.baseURLString = "http://192.168.1.10:8000"

        XCTAssertEqual(AppSettings().baseURLString, "http://192.168.1.10:8000")
    }

    func testALoopbackAddressIsOnlyUsableInTheSimulator() {
        for address in ["http://localhost:8000", "http://127.0.0.1:8000", "http://0.0.0.0:8000"] {
            XCTAssertFalse(AppSettings.isUsableHere(address, inSimulator: false), address)
            XCTAssertTrue(AppSettings.isUsableHere(address, inSimulator: true), address)
        }
    }

    /// A LAN server or a tunnel may be exactly what the user meant, so those are
    /// kept; the error screen names them and offers the way back instead.
    func testOtherStoredAddressesAreKept() {
        let kept = [
            "http://192.168.1.10:8000", "https://x.trycloudflare.com",
            "https://convert.example.com"
        ]
        for address in kept {
            XCTAssertTrue(AppSettings.isUsableHere(address, inSimulator: false), address)
        }
    }

    #if !targetEnvironment(simulator)
    /// An install that already carries localhost recovers on its next launch.
    func testAStoredLoopbackAddressIsDroppedOnAPhone() {
        defaults.set("http://localhost:8000", forKey: "backend.baseURL")
        let settings = AppSettings()

        XCTAssertEqual(settings.baseURLString, BackendEnvironment.defaultBaseURLString ?? "")
        XCTAssertNil(defaults.object(forKey: "backend.baseURL"), "the residue was left on disk")
    }
    #endif
}
