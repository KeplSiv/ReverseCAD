import XCTest

final class WorkflowTests:XCTestCase {
    let app=XCUIApplication()
    override func setUpWithError() throws {
        continueAfterFailure=false
        let repo=URL(fileURLWithPath:#filePath).deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
        let tokenPath=repo.appendingPathComponent("var/service/pairing-token")
        let token=(try? String(contentsOf:tokenPath,encoding:.utf8).trimmingCharacters(in:.whitespacesAndNewlines)) ?? ProcessInfo.processInfo.environment["REVERSECAD_TEST_TOKEN"] ?? ""
        if token.isEmpty {throw NSError(domain:"ReverseCADIntegration",code:1,userInfo:[NSLocalizedDescriptionKey:"Start scripts/start_service.sh; a real paired service token is required for this non-mocked integration test."])}
        app.launchEnvironment["REVERSECAD_TEST_TOKEN"]=token
        app.launchEnvironment["REVERSECAD_TEST_URL"]="http://127.0.0.1:8767"
        app.launch()
    }
    func scrollTo(_ element:XCUIElement,up:Bool=true) {
        for _ in 0..<18 {
            if element.exists && element.isHittable{return}
            let start=app.coordinate(withNormalizedOffset:CGVector(dx:0.02,dy:up ? 0.85:0.32))
            let end=app.coordinate(withNormalizedOffset:CGVector(dx:0.02,dy:up ? 0.32:0.85))
            start.press(forDuration:0.05,thenDragTo:end)
        }
    }
    func screenshot(_ name:String) {let a=XCTAttachment(screenshot:app.screenshot());a.name=name;a.lifetime = .keepAlways;add(a)}
    func waitForSuccess(_ element:XCUIElement,timeout:TimeInterval,file:StaticString=#filePath,line:UInt=#line) {
        let done=XCTNSPredicateExpectation(predicate:NSPredicate { _,_ in (element.exists && !self.app.buttons["cancelJob"].exists) || self.app.alerts["Action needs attention"].exists },object:nil)
        let result=XCTWaiter.wait(for:[done],timeout:timeout)
        if app.alerts["Action needs attention"].exists {
            screenshot("unexpected-service-or-validation-error")
            XCTFail("Workflow failed: "+app.alerts["Action needs attention"].staticTexts.allElementsBoundByIndex.map(\.label).joined(separator:" · "),file:file,line:line)
            return
        }
        XCTAssertEqual(result,.completed,"Timed out waiting for \(element.identifier). \(app.debugDescription)",file:file,line:line)
        XCTAssertTrue(element.exists,file:file,line:line)
    }
    func text(_ field:XCUIElement,_ value:String) {scrollTo(field);field.tap();field.press(forDuration:1.1);if app.menuItems["Select All"].waitForExistence(timeout:1){app.menuItems["Select All"].tap()} else {field.typeText(String(repeating:XCUIKeyboardKey.delete.rawValue,count:30))};field.typeText(value);if app.buttons["keyboardDone"].exists {app.buttons["keyboardDone"].tap()}}
    func testReplayToRealServiceCADExportAndPersistence() throws {
        app.buttons["sampleProject"].tap()
        let replay=app.buttons["loadReplay"];scrollTo(replay);replay.tap()
        let saved=app.otherElements["scanSaved"]
        XCTAssertTrue(app.buttons["processScan"].waitForExistence(timeout:30))
        scrollTo(app.buttons["exportScan"]);app.buttons["exportScan"].tap()
        XCTAssertTrue(app.buttons["Close"].waitForExistence(timeout:15) || app.buttons["Save to Files"].exists)
        screenshot("00-native-scan-package-export")
        if app.buttons["Close"].exists {app.buttons["Close"].tap()} else {app.swipeDown()}
        scrollTo(app.buttons["processScan"]);app.buttons["processScan"].tap()
        if app.buttons["cancelJob"].waitForExistence(timeout:5) {
            app.buttons["cancelJob"].tap()
            XCTAssertTrue(app.buttons["processScan"].waitForExistence(timeout:20))
            for _ in 0..<30 {if app.buttons["processScan"].isEnabled {break};Thread.sleep(forTimeInterval:0.3)}
            scrollTo(app.buttons["processScan"]);app.buttons["processScan"].tap()
        }
        waitForSuccess(app.staticTexts["Scan reconstructed"],timeout:180)
        screenshot("01-reconstructed-synthetic-scan")
        app.buttons["Evidence"].tap()
        let preview=app.descendants(matching:.any).matching(NSPredicate(format:"identifier IN %@",["scanPreview","geometryPreview"])).firstMatch
        XCTAssertTrue(preview.waitForExistence(timeout:15))
        scrollTo(preview)
        for position in [CGVector(dx:0.39,dy:0.39),CGVector(dx:0.64,dy:0.45)] {
            preview.coordinate(withNormalizedOffset:position).tap()
        }
        XCTAssertTrue(app.staticTexts["annotationCount"].label.hasPrefix("2 contacts"),"Two spatially separate observed surface taps must create two contacts.")
        screenshot("01b-two-observed-contact-patches")
        let manual=app.textFields["manualValue"];scrollTo(manual);text(manual,"80")
        scrollTo(app.buttons["saveMeasurement"]);app.buttons["saveMeasurement"].tap()
        scrollTo(app.buttons["saveEvidence"]);app.buttons["saveEvidence"].tap()
        app.buttons["Design"].tap()
        let suggest=app.buttons["suggestCandidates"];scrollTo(suggest);suggest.tap()
        waitForSuccess(app.buttons["Apply candidate"].firstMatch,timeout:30)
        scrollTo(app.buttons["Apply candidate"].firstMatch);screenshot("01c-evidence-linked-candidates");app.buttons["Apply candidate"].firstMatch.tap()
        scrollTo(app.textFields["param_hole_diameter"]);text(app.textFields["param_hole_diameter"],"0")
        let ack=app.switches["acknowledgeFit"];scrollTo(ack);ack.tap()
        let generate=app.buttons["generateRepair"];scrollTo(generate);XCTAssertTrue(generate.isEnabled);generate.tap()
        waitForSuccess(app.staticTexts["CAD checks passed"],timeout:180)
        app.buttons["Results"].tap()
        XCTAssertTrue(app.staticTexts["Repair revision 1"].waitForExistence(timeout:10))
        screenshot("02-cad-comparison-validation")
        let export=app.buttons["exportCAD"];scrollTo(export);XCTAssertTrue(export.isEnabled);export.tap()
        XCTAssertTrue(app.otherElements["ActivityListView"].waitForExistence(timeout:10) || app.buttons["Copy"].exists || app.buttons["Save to Files"].exists,app.debugDescription)
        screenshot("03-native-export-sheet")
        if app.buttons["Close"].exists {app.buttons["Close"].tap()} else {app.swipeDown()}
        app.terminate();app.launch()
        let sample=app.buttons.matching(NSPredicate(format:"label CONTAINS 'Synthetic sample' AND label CONTAINS 'Bridge handle'")).firstMatch
        XCTAssertTrue(sample.waitForExistence(timeout:10));sample.tap()
        app.buttons["Results"].tap()
        XCTAssertTrue(app.staticTexts["Repair revision 1"].waitForExistence(timeout:10))
        app.buttons["Design"].tap()
        scrollTo(app.textFields["param_standoff"]);text(app.textFields["param_standoff"],"34")
        scrollTo(app.buttons["generateRepair"]);app.buttons["generateRepair"].tap()
        waitForSuccess(app.staticTexts["CAD checks passed"],timeout:180)
        app.buttons["Results"].tap()
        XCTAssertTrue(app.staticTexts["Repair revision 2"].waitForExistence(timeout:10))
        screenshot("04-edited-revision-preserved-scan")
        let note="Synthetic software UI test note; no print performed"
        let feedback=app.descendants(matching:.any)["fitFeedback"]
        scrollTo(feedback);text(feedback,note)
        scrollTo(app.buttons["saveFeedback"]);app.buttons["saveFeedback"].tap()
        XCTAssertTrue(app.staticTexts["Saved locally"].waitForExistence(timeout:5))
        app.terminate();app.launch()
        let reopened=app.buttons.matching(NSPredicate(format:"label CONTAINS 'Synthetic sample' AND label CONTAINS 'Bridge handle'")).firstMatch
        XCTAssertTrue(reopened.waitForExistence(timeout:10));reopened.tap();app.buttons["Results"].tap()
        let persisted=app.descendants(matching:.any)["fitFeedback"];scrollTo(persisted)
        XCTAssertEqual(persisted.value as? String,note)
        XCTAssertTrue(app.buttons["Not tested"].exists || app.staticTexts.matching(NSPredicate(format:"label CONTAINS 'Physical fit: not tested'")).firstMatch.exists)
        screenshot("06-feedback-persisted-no-physical-claim")
        _=saved
    }
    func testConnectionFailureRecovery() throws {
        app.buttons["serviceSettings"].tap()
        let field=app.textFields["serviceURL"]
        text(field,"http://127.0.0.1:1")
        app.buttons["checkConnection"].tap()
        XCTAssertTrue(app.alerts["Action needs attention"].waitForExistence(timeout:60))
        app.alerts.buttons["OK"].tap()
        text(field,"http://127.0.0.1:8767")
        app.buttons["checkConnection"].tap()
        XCTAssertTrue(app.staticTexts.matching(NSPredicate(format:"label BEGINSWITH 'Connected'")).firstMatch.waitForExistence(timeout:30))
        screenshot("05-service-reconnected")
    }
}
