import XCTest

final class ConsolidatedFlowTests: XCTestCase {
    let app = XCUIApplication()
    override func setUpWithError() throws {
        continueAfterFailure=false
        app.launchArguments=["-cameraAccessGranted"]
        app.launch()
    }
    private func keepScreenshot(_ name: String) {
        let shot = XCTAttachment(screenshot: app.screenshot()); shot.name = name; shot.lifetime = .keepAlways; add(shot)
    }
    func testSeparateFlowsAndResizableBoxWithoutCompanion() {
        XCTAssertTrue(app.buttons["flow_scan"].waitForExistence(timeout: 15))
        XCTAssertTrue(app.buttons["flow_repair"].exists)
        XCTAssertTrue(app.navigationBars["ReverseCAD"].exists)
        XCTAssertTrue(app.textFields["scanObjectDescription"].exists)
        XCTAssertFalse(app.buttons["setupPhone"].exists)
        XCTAssertFalse(app.staticTexts["selfieSetupHint"].exists)
        XCTAssertFalse(app.buttons["identifyObjectBox"].exists)
        XCTAssertTrue(app.buttons["startObjectScan"].exists)
        XCTAssertFalse(app.buttons["Export original capture"].exists)
        XCTAssertFalse(app.buttons["Connection"].exists)
        keepScreenshot("reversecad-camera-home")
        let bottom = app.descendants(matching: .any).matching(identifier: "box_bottomRight").firstMatch
        let top = app.descendants(matching: .any).matching(identifier: "box_topLeft").firstMatch
        XCTAssertTrue(bottom.waitForExistence(timeout: 5)); XCTAssertTrue(top.exists)
        let before = bottom.frame, initialTop = top.frame
        bottom.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.5)).press(forDuration: 0.1, thenDragTo: bottom.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.5)).withOffset(CGVector(dx: 35, dy: 35)))
        XCTAssertGreaterThan(bottom.frame.midX, before.midX + 10)
        XCTAssertEqual(top.frame.midX, initialTop.midX, accuracy: 3)
        keepScreenshot("reversecad-adjustable-selection")
        app.buttons["openSavedScans"].tap()
        XCTAssertTrue(app.navigationBars["Saved scans"].waitForExistence(timeout: 5))
        keepScreenshot("reversecad-saved-scans")
        app.buttons["Done"].tap()
        app.buttons["flow_repair"].tap()
        XCTAssertFalse(app.buttons["setupPhone"].exists)
        XCTAssertTrue(app.buttons["startObjectScan"].exists)
        XCTAssertTrue(app.textFields["scanObjectDescription"].exists)
        keepScreenshot("reversecad-repair-camera")
        app.buttons["Scanning tips"].tap()
        XCTAssertTrue(app.navigationBars["A better scan"].waitForExistence(timeout: 5))
        app.buttons["Done"].tap()
        XCTAssertTrue(app.buttons["flow_scan"].exists)
        app.buttons["About ReverseCAD"].tap()
        XCTAssertTrue(app.navigationBars["About ReverseCAD"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.staticTexts["On this phone"].exists)
        XCTAssertFalse(app.textFields["serviceURL"].exists)
        XCTAssertFalse(app.secureTextFields["pairingToken"].exists)
        XCTAssertFalse(app.staticTexts.containing(NSPredicate(format: "label CONTAINS[c] %@", "Prelude")).firstMatch.exists)
        keepScreenshot("reversecad-about")
        app.buttons["Done"].tap()
    }

    func testOldFrontReferenceLaunchArgumentStillOpensRearFlow() {
        app.terminate(); app.launchArguments=["-cameraAccessGranted","-frontReferenceCheck"]; app.launch()
        XCTAssertTrue(app.buttons["startObjectScan"].waitForExistence(timeout:10))
        XCTAssertFalse(app.navigationBars["Front reference"].exists)
        XCTAssertFalse(app.buttons["setupPhone"].exists)
        XCTAssertEqual(app.scrollViews.count,0)
        keepScreenshot("reversecad-rear-only-flow")
    }

    func testAppLaunchOpensRearCameraFlow() {
        app.terminate();app.launchArguments=["-cameraAccessGranted"];app.launch()
        XCTAssertTrue(app.buttons["flow_scan"].waitForExistence(timeout:10))
        XCTAssertTrue(app.buttons["flow_repair"].exists)
        XCTAssertTrue(app.staticTexts["scanGuidance"].exists)
        XCTAssertFalse(app.navigationBars["Front reference"].exists)
        keepScreenshot("reversecad-rear-camera-launch")
    }

    func testDeniedPermissionShowsSettingsBeforeAnyCamera() {
        app.terminate();app.launchArguments=["-cameraAccessDenied"];app.launch()
        XCTAssertTrue(app.buttons["cameraPermissionSettings"].waitForExistence(timeout:5))
        XCTAssertFalse(app.otherElements["frontReferencePreview"].exists)
        XCTAssertFalse(app.buttons["flow_scan"].exists)
        keepScreenshot("reversecad-camera-permission")
    }
}
