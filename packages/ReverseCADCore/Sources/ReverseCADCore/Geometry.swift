import Foundation

/// Column-major matrices; T_a_b maps b into a. Capture meters, CAD millimeters.
public enum Geometry {
    public static let identity: [Double] = [1,0,0,0, 0,1,0,0, 0,0,1,0, 0,0,0,1]
    public static func validateRigidTransform(_ m: [Double]) throws {
        guard m.count == 16, m.allSatisfy(\.isFinite), abs(m[3]) < 1e-6, abs(m[7]) < 1e-6, abs(m[11]) < 1e-6, abs(m[15]-1) < 1e-6 else { throw CoreError.invalid("Pose must be a finite column-major affine 4×4 matrix.") }
        for c in 0..<3 { for d in 0..<3 {
            let dot = (0..<3).reduce(0.0) { $0 + m[c*4+$1] * m[d*4+$1] }
            guard abs(dot - (c == d ? 1 : 0)) < 0.005 else { throw CoreError.invalid("Pose rotation must be orthonormal; scale is not a camera transform.") }
        } }
        let det = m[0]*(m[5]*m[10]-m[9]*m[6]) - m[4]*(m[1]*m[10]-m[9]*m[2]) + m[8]*(m[1]*m[6]-m[5]*m[2])
        guard abs(det-1) < 0.005 else { throw CoreError.invalid("Pose must preserve handedness.") }
    }
    public static func transform(_ point: [Double], by matrix: [Double]) throws -> [Double] {
        try validateRigidTransform(matrix)
        guard point.count == 3, point.allSatisfy(\.isFinite) else { throw CoreError.invalid("Point must contain three finite coordinates.") }
        return (0..<3).map { r in matrix[r]*point[0] + matrix[r+4]*point[1] + matrix[r+8]*point[2] + matrix[r+12] }
    }
    /// Resized image pixel centers use c'=(c+0.5)*scale-0.5. Apple's native ARKit depth uses c'=c*scale.
    public static func scaledIntrinsics(_ k: [Double], fromWidth: Int, fromHeight: Int, toWidth: Int, toHeight: Int, mode: String = "pixel_center") throws -> [Double] {
        guard k.count == 9, k.allSatisfy(\.isFinite), k[0] > 0, k[4] > 0, fromWidth > 0, fromHeight > 0, toWidth > 0, toHeight > 0 else { throw CoreError.invalid("Invalid intrinsics or image dimensions.") }
        let sx = Double(toWidth)/Double(fromWidth), sy = Double(toHeight)/Double(fromHeight)
        guard ["pixel_center", "native_arkit"].contains(mode) else { throw CoreError.invalid("Unknown depth calibration mapping mode.") }
        var result = k; result[0] *= sx; result[3] *= sx; result[6] = (k[6]+0.5)*sx-0.5; result[1] *= sy; result[4] *= sy; result[7] = (k[7]+0.5)*sy-0.5
        if mode == "native_arkit" { result[6] = k[6] * sx; result[7] = k[7] * sy }
        return result
    }
    public static func unproject(u: Double, v: Double, depthMeters: Double, intrinsics: [Double], intrinsicsWidth: Int, intrinsicsHeight: Int, depthWidth: Int, depthHeight: Int, worldCamera: [Double], objectWorld: [Double] = identity, depthCalibrationMode: String = "pixel_center") throws -> [Double] {
        guard depthMeters.isFinite, depthMeters > 0, u.isFinite, v.isFinite else { throw CoreError.invalid("Depth must be finite and positive.") }
        let k = try scaledIntrinsics(intrinsics, fromWidth: intrinsicsWidth, fromHeight: intrinsicsHeight, toWidth: depthWidth, toHeight: depthHeight, mode: depthCalibrationMode)
        let determinant = k[0]*k[4]-k[3]*k[1]
        guard abs(determinant) > 1e-10 else { throw CoreError.invalid("Singular camera intrinsics.") }
        let px = u-k[6], py = v-k[7]
        let x = (k[4]*px-k[3]*py)/determinant*depthMeters
        let y = (-k[1]*px+k[0]*py)/determinant*depthMeters
        // CV right/down/forward to ARKit right/up/back: S=diag(1,-1,-1).
        return try transform(transform([x,-y,-depthMeters], by: worldCamera), by: objectWorld)
    }
    public static func metersToMillimeters(_ p: [Double]) -> [Double] { p.map { $0 * 1000 } }
    public static func millimetersToMeters(_ p: [Double]) -> [Double] { p.map { $0 / 1000 } }
    /// Copy only meaningful pixels; never retain a CVPixelBuffer pointer across threads.
    public static func tightlyPackedRows(_ source: Data, width: Int, height: Int, rowBytes: Int, bytesPerPixel: Int) throws -> Data {
        guard width > 0, height > 0, width <= 16384, height <= 16384, [1,4].contains(bytesPerPixel), rowBytes >= width*bytesPerPixel, rowBytes <= 1024*1024, source.count == rowBytes*height else { throw CoreError.invalid("Source row stride or buffer length is invalid.") }
        var out = Data(capacity: width*height*bytesPerPixel)
        for row in 0..<height { out.append(source[(row*rowBytes)..<(row*rowBytes+width*bytesPerPixel)]) }
        return out
    }
}
