import XCTest

/// Real touch drags exercise the coordinate space while the handles themselves move.
final class SelectionBoxGestureTests: XCTestCase {
    private let app = XCUIApplication()

    override func setUpWithError() throws {
        continueAfterFailure = false
        app.launch()
        XCTAssertTrue(handle("bottomRight").waitForExistence(timeout: 15))
    }

    private func handle(_ name: String) -> XCUIElement {
        app.descendants(matching: .any).matching(identifier: "box_" + name).firstMatch
    }

    private func center(_ element: XCUIElement) -> CGPoint {
        CGPoint(x: element.frame.midX, y: element.frame.midY)
    }

    private func drag(_ name: String, by delta: CGVector) {
        let start = center(handle(name))
        let origin = app.coordinate(withNormalizedOffset: .zero)
        let from = origin.withOffset(CGVector(dx: start.x, dy: start.y))
        let to = origin.withOffset(CGVector(dx: start.x + delta.dx, dy: start.y + delta.dy))
        from.press(forDuration: 0.1, thenDragTo: to, withVelocity: .slow, thenHoldForDuration: 0.3)
    }

    private func assertPoint(_ actual: CGPoint, equals expected: CGPoint, file: StaticString = #filePath, line: UInt = #line) {
        XCTAssertEqual(actual.x, expected.x, accuracy: 3, file: file, line: line)
        XCTAssertEqual(actual.y, expected.y, accuracy: 3, file: file, line: line)
    }

    func testResizeFollowsFingerAndKeepsOppositeCornerFixed() {
        let start = center(handle("bottomRight")), opposite = center(handle("topLeft"))
        drag("bottomRight", by: CGVector(dx: 60, dy: 40))
        assertPoint(center(handle("bottomRight")), equals: CGPoint(x: start.x + 60, y: start.y + 40))
        assertPoint(center(handle("topLeft")), equals: opposite)
        // A second drag must start at the latest size, without a snap to the first origin.
        drag("bottomRight", by: CGVector(dx: -35, dy: -25))
        assertPoint(center(handle("bottomRight")), equals: CGPoint(x: start.x + 25, y: start.y + 15))
        assertPoint(center(handle("topLeft")), equals: opposite)
    }

    func testMoveFollowsFingerWithoutChangingSize() {
        let top = center(handle("topLeft")), bottom = center(handle("bottomRight"))
        drag("move", by: CGVector(dx: 55, dy: -45))
        assertPoint(center(handle("topLeft")), equals: CGPoint(x: top.x + 55, y: top.y - 45))
        assertPoint(center(handle("bottomRight")), equals: CGPoint(x: bottom.x + 55, y: bottom.y - 45))
        drag("move", by: CGVector(dx: -30, dy: 25))
        assertPoint(center(handle("topLeft")), equals: CGPoint(x: top.x + 25, y: top.y - 20))
        assertPoint(center(handle("bottomRight")), equals: CGPoint(x: bottom.x + 25, y: bottom.y - 20))
    }

    func testEveryCornerKeepsItsOppositeAnchor() {
        let cases: [(String, String, CGVector)] = [
            ("topLeft", "bottomRight", CGVector(dx: -38, dy: -26)),
            ("topRight", "bottomLeft", CGVector(dx: 38, dy: -26)),
            ("bottomLeft", "topRight", CGVector(dx: -38, dy: 26)),
            ("bottomRight", "topLeft", CGVector(dx: 38, dy: 26))
        ]
        for (corner, anchor, delta) in cases {
            let before = center(handle(corner)), fixed = center(handle(anchor))
            drag(corner, by: delta)
            assertPoint(center(handle(corner)), equals: CGPoint(x: before.x + delta.dx, y: before.y + delta.dy))
            assertPoint(center(handle(anchor)), equals: fixed)
        }
    }

    func testMinimumSizeAndNextDragUseCurrentBounds() {
        let top = center(handle("topLeft")), bottom = center(handle("bottomRight"))
        // The initial box is one third of the viewport; minimum size is 8%.
        let minimum = CGPoint(x: top.x + (bottom.x-top.x)*0.24, y: top.y + (bottom.y-top.y)*0.24)
        drag("bottomRight", by: CGVector(dx: top.x-bottom.x-20, dy: top.y-bottom.y-20))
        assertPoint(center(handle("topLeft")), equals: top)
        assertPoint(center(handle("bottomRight")), equals: minimum)
        drag("bottomRight", by: CGVector(dx: 45, dy: 35))
        assertPoint(center(handle("bottomRight")), equals: CGPoint(x: minimum.x+45, y: minimum.y+35))
    }

    func testMoveClampsAtPreviewEdgeAndReversesSmoothly() {
        let top = center(handle("topLeft")), bottom = center(handle("bottomRight"))
        let width = bottom.x-top.x, viewportRight = top.x+2*width
        drag("move", by: CGVector(dx: width+30, dy: 0))
        assertPoint(center(handle("topLeft")), equals: CGPoint(x: viewportRight-width, y: top.y))
        drag("move", by: CGVector(dx: -35, dy: 15))
        assertPoint(center(handle("topLeft")), equals: CGPoint(x: viewportRight-width-35, y: top.y+15))
    }
}
