import XCTest
@testable import ReverseCADCore

final class LiveIdentificationTests: XCTestCase {
    func testCadenceAndBackpressureWithoutCatchUpBurst() throws {
        var schedule = LiveIdentificationSchedule(); schedule.start(at: 0)
        let first = try XCTUnwrap(schedule.reserve(at: 0))
        XCTAssertNil(schedule.reserve(at: 0.099))
        XCTAssertNotNil(schedule.reserve(at: 0.1))
        XCTAssertNil(schedule.reserve(at: 0.199))
        XCTAssertNotNil(schedule.reserve(at: 0.2))
        XCTAssertNotNil(schedule.reserve(at: 0.301))
        XCTAssertNil(schedule.reserve(at: 0.5)) // Four requests still active; drop this frame.
        XCTAssertTrue(schedule.complete(first, at: 1))
        XCTAssertNotNil(schedule.reserve(at: 1))
        XCTAssertNil(schedule.reserve(at: 1)) // No catch-up queue.
    }

    func testOlderNegativeReplyCannotEraseNewerTarget() throws {
        var schedule = LiveIdentificationSchedule(); schedule.start(at: 0)
        let old = try XCTUnwrap(schedule.reserve(at: 0))
        let new = try XCTUnwrap(schedule.reserve(at: 0.2))
        XCTAssertTrue(schedule.complete(new, at: 0.4))
        XCTAssertFalse(schedule.complete(old, at: 0.5))
        XCTAssertTrue(schedule.inFlight.isEmpty)
    }

    func testExpiredAndPreviousSessionRepliesAreRejected() throws {
        var schedule = LiveIdentificationSchedule(); schedule.start(at: 0)
        let old = try XCTUnwrap(schedule.reserve(at: 0))
        XCTAssertFalse(schedule.complete(old, at: 1.201))
        let previousSession = try XCTUnwrap(schedule.reserve(at: 2))
        schedule.stop(); XCTAssertNil(schedule.reserve(at: 2.1))
        schedule.start(at: 2.2)
        XCTAssertFalse(schedule.complete(previousSession, at: 2.3))
        XCTAssertNotNil(schedule.reserve(at: 2.3))
    }

    func testFailureBackoffAndRecovery() {
        var schedule = LiveIdentificationSchedule(); schedule.start(at: 0)
        schedule.failed(at: 0)
        XCTAssertNil(schedule.reserve(at: 1.9))
        XCTAssertNotNil(schedule.reserve(at: 2))
        schedule.failed(at: 2)
        XCTAssertNil(schedule.reserve(at: 5.9))
        XCTAssertNotNil(schedule.reserve(at: 6))
        schedule.succeeded(); schedule.failed(at: 6)
        XCTAssertNotNil(schedule.reserve(at: 8))
    }

    func testTimeoutStillBacksOffButCannotReplaceANewerReply() throws {
        var schedule = LiveIdentificationSchedule(); schedule.start(at: 0)
        let old = try XCTUnwrap(schedule.reserve(at: 0))
        let new = try XCTUnwrap(schedule.reserve(at: 0.2))
        XCTAssertTrue(schedule.complete(new, at: 0.4))
        XCTAssertFalse(schedule.complete(old, at: 3, includingExpired: true))
        let timedOut = try XCTUnwrap(schedule.reserve(at: 4))
        XCTAssertTrue(schedule.complete(timedOut, at: 7, includingExpired: true))
        schedule.failed(at: 7)
        XCTAssertNil(schedule.reserve(at: 8))
    }
}
