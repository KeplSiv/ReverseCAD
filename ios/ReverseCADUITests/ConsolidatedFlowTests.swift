import XCTest

final class ConsolidatedFlowTests: XCTestCase {
    let app = XCUIApplication()
    override func setUpWithError() throws { continueAfterFailure = false; app.launch() }
    private func keepScreenshot(_ name: String) {
        let shot = XCTAttachment(screenshot: app.screenshot()); shot.name = name; shot.lifetime = .keepAlways; add(shot)
    }
    func testSeparateFlowsAndResizableBoxWithoutCompanion() {
        XCTAssertTrue(app.buttons["flow_scan"].waitForExistence(timeout: 15))
        XCTAssertTrue(app.buttons["flow_repair"].exists)
        XCTAssertTrue(app.navigationBars["ReverseCAD"].exists)
        XCTAssertTrue(app.textFields["scanObjectDescription"].exists)
        XCTAssertTrue(app.buttons["setupPhone"].waitForExistence(timeout: 5))
        XCTAssertFalse(app.buttons["identifyObjectBox"].exists)
        XCTAssertFalse(app.buttons["startObjectScan"].exists)
        XCTAssertFalse(app.buttons["Export original capture"].exists)
        XCTAssertFalse(app.buttons["Connection"].exists)
        keepScreenshot("reversecad-camera-home")
        app.buttons["setupPhone"].tap()
        XCTAssertTrue(app.navigationBars["Front reference"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.staticTexts["frontReferenceInstructions"].exists)
        XCTAssertEqual(app.scrollViews.count,0)
        XCTAssertFalse(app.buttons["Export original reference"].exists)
        keepScreenshot("reversecad-reference-setup")
        app.buttons["Close"].tap()
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
        XCTAssertTrue(app.buttons["setupPhone"].waitForExistence(timeout: 5))
        XCTAssertFalse(app.buttons["startObjectScan"].exists)
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

    func testFrontReferenceFitsWithoutScrollingAndHasTopAction() {
        app.terminate();app.launchArguments=["-frontReferenceCheck"];app.launch()
        XCTAssertTrue(app.navigationBars["Front reference"].waitForExistence(timeout:10))
        let instructions=app.staticTexts["frontReferenceInstructions"]
        XCTAssertTrue(instructions.waitForExistence(timeout:5))
        XCTAssertEqual(app.scrollViews.count,0)
        let save=app.buttons["saveFrontReference"]
        let open=app.buttons["Open selfie camera"]
        XCTAssertTrue(save.exists || open.waitForExistence(timeout:5))
        let button=save.exists ? save:open
        XCTAssertLessThan(button.frame.maxY,instructions.frame.minY+2)
        XCTAssertTrue(button.isHittable)
        keepScreenshot("reversecad-front-no-scroll")
    }
}
