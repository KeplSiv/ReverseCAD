import XCTest
import AVFoundation
@testable import ReverseCAD

@MainActor final class CameraAccessTests:XCTestCase {
    func testGrantedStartsWithoutRequestingAgain() async {
        var requests=0
        let access=CameraAccess(authorization:{.authorized},request:{requests+=1;return true})
        XCTAssertEqual(access.state,.granted)
        await access.refresh()
        XCTAssertEqual(requests,0)
        XCTAssertEqual(access.state,.granted)
    }
    func testFirstRequestAndDenial() async {
        var requests=0
        let access=CameraAccess(authorization:{.notDetermined},request:{requests+=1;return false})
        XCTAssertEqual(access.state,.requesting)
        await access.refresh()
        XCTAssertEqual(requests,1)
        XCTAssertEqual(access.state,.denied)
    }
    func testOnlyOnePromptWhileRequestIsPending() async {
        var requests=0
        var response:CheckedContinuation<Bool,Never>?
        let access=CameraAccess(authorization:{.notDetermined},request:{
            requests+=1
            return await withCheckedContinuation {response=$0}
        })
        let first=Task {await access.refresh()}
        while response == nil {await Task.yield()}
        await access.refresh()
        XCTAssertEqual(requests,1)
        response?.resume(returning:true)
        await first.value
        XCTAssertEqual(access.state,.granted)
    }
    func testSettingsChangeAndRestrictionDoNotReprompt() async {
        var status=AVAuthorizationStatus.denied
        var requests=0
        let access=CameraAccess(authorization:{status},request:{requests+=1;return true})
        await access.refresh()
        XCTAssertEqual(access.state,.denied)
        status = .authorized
        await access.refresh()
        XCTAssertEqual(access.state,.granted)
        status = .restricted
        await access.refresh()
        XCTAssertEqual(access.state,.restricted)
        XCTAssertEqual(requests,0)
    }
}
