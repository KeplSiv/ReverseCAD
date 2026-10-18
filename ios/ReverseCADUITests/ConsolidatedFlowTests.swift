import XCTest

final class ConsolidatedFlowTests: XCTestCase {
    let app=XCUIApplication()
    override func setUpWithError() throws { continueAfterFailure=false;app.launch() }
    func testSeparateFlowsAndResizableBoxWithoutCompanion() {
        XCTAssertTrue(app.buttons["flow_scan"].waitForExistence(timeout:15))
        XCTAssertTrue(app.buttons["flow_repair"].exists)
        capture("consolidated-home")
        app.buttons["flow_scan"].tap()
        XCTAssertTrue(app.textFields["scanObjectDescription"].waitForExistence(timeout:5))
        XCTAssertTrue(app.buttons["findScanObject"].isEnabled)
        capture("scan-flow")
        app.buttons["findScanObject"].tap()
        let identify=app.buttons["identifyObjectBox"]
        XCTAssertTrue(identify.waitForExistence(timeout:5))
        XCTAssertFalse(app.buttons["startObjectScan"].exists)
        let bottom=app.descendants(matching:.any).matching(identifier:"box_bottomRight").firstMatch
        let top=app.descendants(matching:.any).matching(identifier:"box_topLeft").firstMatch
        XCTAssertTrue(bottom.waitForExistence(timeout:5));XCTAssertTrue(top.exists)
        let before=bottom.frame, initialTop=top.frame
        bottom.coordinate(withNormalizedOffset:CGVector(dx:0.5,dy:0.5)).press(forDuration:0.1,thenDragTo:bottom.coordinate(withNormalizedOffset:CGVector(dx:0.5,dy:0.5)).withOffset(CGVector(dx:35,dy:35)))
        XCTAssertGreaterThan(bottom.frame.midX,before.midX+10)
        XCTAssertEqual(top.frame.midX,initialTop.midX,accuracy:3)
        let shot=XCTAttachment(screenshot:app.screenshot());shot.name="adjustable-selection";shot.lifetime = .keepAlways;add(shot)
        app.buttons["Close"].tap();app.buttons["Home"].tap()
        XCTAssertTrue(app.buttons["flow_repair"].waitForExistence(timeout:5));app.buttons["flow_repair"].tap()
        XCTAssertTrue(app.staticTexts["Repair damage"].waitForExistence(timeout:5))
        XCTAssertTrue(app.buttons["findScanObject"].isEnabled)
        capture("repair-flow")
    }
    private func capture(_ name: String) {
        let shot=XCTAttachment(screenshot:app.screenshot());shot.name=name;shot.lifetime = .keepAlways;add(shot)
    }
}
