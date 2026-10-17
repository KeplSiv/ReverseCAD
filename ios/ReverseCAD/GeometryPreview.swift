import SceneKit
import SwiftUI
import UIKit
import simd

/// Service meshes are expressed in object-frame millimeters. SceneKit receives meters.
/// Neither the camera nor a parent node applies a second scale conversion.
struct MeshPreview: Codable, Equatable {
    var vertices: [[Double]]
    var triangles: [[Int]]
    var colors: [[Double]]?
    var normals: [[Double]]?
    var unit: String

    init(vertices: [[Double]], triangles: [[Int]] = [], colors: [[Double]]? = nil,
         normals: [[Double]]? = nil, unit: String = "mm") {
        self.vertices = vertices
        self.triangles = triangles
        self.colors = colors
        self.normals = normals
        self.unit = unit
    }

    private enum CodingKeys: String, CodingKey { case vertices, triangles, colors, normals, unit }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        vertices = try container.decode([[Double]].self, forKey: .vertices)
        triangles = try container.decodeIfPresent([[Int]].self, forKey: .triangles) ?? []
        colors = try container.decodeIfPresent([[Double]].self, forKey: .colors)
        normals = try container.decodeIfPresent([[Double]].self, forKey: .normals)
        unit = try container.decodeIfPresent(String.self, forKey: .unit) ?? "mm"
        guard unit == "mm" else {
            throw DecodingError.dataCorruptedError(forKey: .unit, in: container,
                                                   debugDescription: "Preview geometry must use millimeters.")
        }
    }
}

/// One finger orbits; two fingers pan; pinch zooms. Tap observed geometry to annotate.
/// onSelect reports the object-frame point in meters and a unit surface normal.
struct GeometryPreview: UIViewRepresentable {
    var scan: MeshPreview?
    var part: MeshPreview?
    var showScan: Bool = true
    var showPart: Bool = true
    var selectionMode: String = "contact"
    var contactPoints: [[Double]] = []
    var damagePoints: [[Double]] = []
    var onReject: (String) -> Void = { _ in }
    var onSelect: ([Double], [Double]) -> Void = { _, _ in }

    func makeCoordinator() -> Coordinator { Coordinator(self) }

    func makeUIView(context: Context) -> SCNView {
        let view = SCNView(frame: .zero)
        view.scene = SCNScene()
        view.backgroundColor = UIColor.secondarySystemBackground
        view.allowsCameraControl = true
        view.autoenablesDefaultLighting = true
        view.antialiasingMode = .multisampling4X
        view.preferredFramesPerSecond = 30
        view.defaultCameraController.interactionMode = .orbitTurntable
        view.defaultCameraController.inertiaEnabled = true
        view.defaultCameraController.automaticTarget = false
        view.accessibilityIdentifier = "geometryPreview"
        view.isAccessibilityElement = true
        view.accessibilityLabel = "3D geometry. Blue observed scan; orange proposed repair."
        view.accessibilityHint = "Drag to orbit, pinch to zoom, two fingers to pan. Tap the observed scan to select a contact or damage location."
        let recognizer = UITapGestureRecognizer(target: context.coordinator,
                                                action: #selector(Coordinator.selectPoint(_:)))
        recognizer.delegate = context.coordinator
        view.addGestureRecognizer(recognizer)
        context.coordinator.view = view
        context.coordinator.update(self)
        return view
    }

    func updateUIView(_ uiView: SCNView, context: Context) {
        context.coordinator.update(self)
    }

    final class Coordinator: NSObject, UIGestureRecognizerDelegate {
        private var parent: GeometryPreview
        weak var view: SCNView?
        private var lastScan: MeshPreview?
        private var lastPart: MeshPreview?
        private var scanNode: SCNNode?
        private var partNode: SCNNode?
        private var markerNode: SCNNode?
        private var savedMarkers: [SCNNode] = []
        private var lastContactPoints: [[Double]] = []
        private var lastDamagePoints: [[Double]] = []
        private var points: [SIMD3<Float>] = []
        private var normals: [SIMD3<Float>?] = []
        private var radius: Float = 0.1
        private var didFit = false

        init(_ parent: GeometryPreview) { self.parent = parent }

        func update(_ newValue: GeometryPreview) {
            parent = newValue
            guard let view, let scene = view.scene else { return }
            let scanChanged = lastScan != newValue.scan
            let partChanged = lastPart != newValue.part
            if scanChanged {
                scanNode?.removeFromParentNode()
                markerNode?.removeFromParentNode()
                markerNode = nil
                lastScan = newValue.scan
                let prepared = prepare(newValue.scan, color: .systemBlue, observed: true)
                scanNode = prepared.node
                points = prepared.points
                normals = prepared.normals
                if let scanNode { scene.rootNode.addChildNode(scanNode) }
            }
            if partChanged {
                partNode?.removeFromParentNode()
                lastPart = newValue.part
                partNode = prepare(newValue.part, color: .systemOrange, observed: false).node
                if let partNode { scene.rootNode.addChildNode(partNode) }
            }
            scanNode?.isHidden = !newValue.showScan
            partNode?.isHidden = !newValue.showPart
            // Preserve a user's orbit while annotations, toggles, or network state change.
            if scanChanged || partChanged || !didFit { fitCamera() }
            if scanChanged || lastContactPoints != newValue.contactPoints || lastDamagePoints != newValue.damagePoints {
                savedMarkers.forEach { $0.removeFromParentNode() }
                markerNode?.removeFromParentNode()
                markerNode = nil
                savedMarkers = []
                for (positions, color) in [(newValue.contactPoints, UIColor.systemYellow), (newValue.damagePoints, UIColor.systemPink)] {
                    for position in positions where position.count == 3 && position.allSatisfy(\.isFinite) {
                        let sphere = SCNSphere(radius: CGFloat(min(0.004, max(0.001, radius * 0.025))))
                        sphere.firstMaterial?.diffuse.contents = color
                        sphere.firstMaterial?.lightingModel = .constant
                        let marker = SCNNode(geometry: sphere)
                        marker.simdPosition = SIMD3(Float(position[0]), Float(position[1]), Float(position[2]))
                        marker.categoryBitMask = 4
                        scene.rootNode.addChildNode(marker)
                        savedMarkers.append(marker)
                    }
                }
                lastContactPoints = newValue.contactPoints
                lastDamagePoints = newValue.damagePoints
            }
            view.accessibilityValue = newValue.selectionMode == "damage" ? "Select a damage location" : "Select a contact surface"
        }

        private typealias Prepared = (node: SCNNode?, points: [SIMD3<Float>], normals: [SIMD3<Float>?])

        private func prepare(_ mesh: MeshPreview?, color: UIColor, observed: Bool) -> Prepared {
            guard let mesh, mesh.unit == "mm", !mesh.vertices.isEmpty else { return (nil, [], []) }
            var positions: [SIMD3<Float>] = []
            var vertexNormals: [SIMD3<Float>?] = []
            var remap = [Int](repeating: -1, count: mesh.vertices.count)
            for (index, vertex) in mesh.vertices.enumerated() {
                guard vertex.count == 3, vertex.allSatisfy({ $0.isFinite && abs($0) < 1_000_000 }) else { continue }
                remap[index] = positions.count
                // This is the sole mm -> m boundary for both observed and inferred geometry.
                positions.append(SIMD3(Float(vertex[0] / 1_000), Float(vertex[1] / 1_000), Float(vertex[2] / 1_000)))
                if let source = mesh.normals, index < source.count, source[index].count == 3,
                   source[index].allSatisfy(\.isFinite) {
                    let n = SIMD3(Float(source[index][0]), Float(source[index][1]), Float(source[index][2]))
                    vertexNormals.append(simd_length_squared(n) > 0.000001 ? simd_normalize(n) : nil)
                } else { vertexNormals.append(nil) }
            }
            guard !positions.isEmpty else { return (nil, [], []) }
            var indices: [UInt32] = []
            for face in mesh.triangles {
                guard face.count == 3, face.allSatisfy({ $0 >= 0 && $0 < remap.count && remap[$0] >= 0 }) else { continue }
                let mapped = face.map { remap[$0] }
                guard Set(mapped).count == 3 else { continue }
                indices.append(contentsOf: mapped.map(UInt32.init))
            }
            if !indices.isEmpty && vertexNormals.contains(where: { $0 == nil }) {
                var accumulated = [SIMD3<Float>](repeating: .zero, count: positions.count)
                for offset in stride(from: 0, to: indices.count, by: 3) {
                    let a = Int(indices[offset]), b = Int(indices[offset + 1]), c = Int(indices[offset + 2])
                    let faceNormal = simd_cross(positions[b] - positions[a], positions[c] - positions[a])
                    accumulated[a] += faceNormal
                    accumulated[b] += faceNormal
                    accumulated[c] += faceNormal
                }
                for index in positions.indices where vertexNormals[index] == nil {
                    if simd_length_squared(accumulated[index]) > 1e-18 {
                        vertexNormals[index] = simd_normalize(accumulated[index])
                    }
                }
            }
            var sources = [SCNGeometrySource(vertices: positions.map { SCNVector3($0.x, $0.y, $0.z) })]
            if vertexNormals.allSatisfy({ $0 != nil }) {
                sources.append(SCNGeometrySource(normals: vertexNormals.compactMap { $0 }.map { SCNVector3($0.x, $0.y, $0.z) }))
            }
            let element: SCNGeometryElement
            if indices.isEmpty {
                element = SCNGeometryElement(indices: Array(0..<UInt32(positions.count)), primitiveType: .point)
                element.pointSize = 3
                element.minimumPointScreenSpaceRadius = 1.5
                element.maximumPointScreenSpaceRadius = 4
            } else {
                element = SCNGeometryElement(indices: indices, primitiveType: .triangles)
            }
            let geometry = SCNGeometry(sources: sources, elements: [element])
            let material = SCNMaterial()
            material.diffuse.contents = color
            material.emission.contents = color.withAlphaComponent(0.12)
            material.lightingModel = indices.isEmpty ? .constant : .blinn
            material.isDoubleSided = true
            material.transparency = observed && !indices.isEmpty ? 0.75 : 1
            geometry.materials = [material]
            let node = SCNNode(geometry: geometry)
            node.name = observed ? "Observed scan" : "Inferred replacement"
            node.categoryBitMask = observed ? 1 : 2
            return (node, positions, vertexNormals)
        }

        private func fitCamera() {
            guard let view, let root = view.scene?.rootNode else { return }
            var lower = SIMD3<Float>(repeating: .greatestFiniteMagnitude)
            var upper = SIMD3<Float>(repeating: -.greatestFiniteMagnitude)
            var found = false
            for node in [scanNode, partNode].compactMap({ $0 }) {
                let (minimum, maximum) = node.boundingBox
                lower = simd_min(lower, SIMD3(minimum.x, minimum.y, minimum.z))
                upper = simd_max(upper, SIMD3(maximum.x, maximum.y, maximum.z))
                found = true
            }
            guard found else { return }
            let center = (lower + upper) * 0.5
            radius = max(0.015, simd_length(upper - lower) * 0.5)
            let camera = view.pointOfView ?? SCNNode()
            if camera.parent == nil { root.addChildNode(camera) }
            camera.camera = camera.camera ?? SCNCamera()
            camera.camera?.fieldOfView = 45
            camera.camera?.zNear = Double(max(0.0001, radius / 100))
            camera.camera?.zFar = Double(max(10, radius * 100))
            camera.simdPosition = center + simd_normalize(SIMD3<Float>(1, 0.7, 1.5)) * radius * 3.4
            let target = SCNVector3(center.x, center.y, center.z)
            camera.look(at: target)
            view.pointOfView = camera
            view.defaultCameraController.target = target
            didFit = true
        }

        @objc func selectPoint(_ recognizer: UITapGestureRecognizer) {
            guard recognizer.state == .ended, parent.showScan, let view, !points.isEmpty,
                  parent.selectionMode != "none" else { return }
            let location = recognizer.location(in: view)
            // Proposed CAD and annotation markers cannot masquerade as observed surfaces.
            let hits = view.hitTest(location, options: [.categoryBitMask: 1, .backFaceCulling: false,
                                                        .searchMode: SCNHitTestSearchMode.closest.rawValue])
            if let hit = hits.first, !(lastScan?.triangles.isEmpty ?? true) {
                let position = SIMD3<Float>(hit.worldCoordinates.x, hit.worldCoordinates.y, hit.worldCoordinates.z)
                let normal = SIMD3<Float>(hit.worldNormal.x, hit.worldNormal.y, hit.worldNormal.z)
                let hint = simd_length_squared(normal) > 0.000001 ? normal : (view.pointOfView?.simdWorldPosition ?? .zero) - position
                if parent.selectionMode != "contact" {
                    selected(position, normal: simd_length_squared(hint)>0.000001 ? simd_normalize(hint) : SIMD3(0,0,1))
                    return
                }
                guard let patch = SurfacePatchNormal.estimate(points: points, center: position, orientationHint: hint) else {
                    rejectPatch()
                    return
                }
                selected(patch.point, normal: patch.normal)
                return
            }
            // SceneKit's point primitive hit testing is device dependent. Select the nearest
            // visible cloud sample in a small screen-space disk; use depth to break ties.
            var nearest: (index: Int, distance: Float, depth: Float)?
            for (index, point) in points.enumerated() {
                let projected = view.projectPoint(SCNVector3(point.x, point.y, point.z))
                guard projected.z > 0, projected.z < 1 else { continue }
                let dx = projected.x - Float(location.x), dy = projected.y - Float(location.y)
                let distance = dx * dx + dy * dy
                guard distance < 24 * 24 else { continue }
                if nearest == nil || distance < nearest!.distance - 4 ||
                    (abs(distance - nearest!.distance) <= 4 && projected.z < nearest!.depth) {
                    nearest = (index, distance, projected.z)
                }
            }
            guard let nearest else { return }
            let position = points[nearest.index]
            let hint = normals[nearest.index] ?? ((view.pointOfView?.simdWorldPosition ?? .zero) - position)
            if parent.selectionMode != "contact" {
                selected(position, normal: simd_length_squared(hint)>0.000001 ? simd_normalize(hint) : SIMD3(0,0,1))
                return
            }
            guard let patch = SurfacePatchNormal.estimate(points: points, center: position, orientationHint: hint) else {
                rejectPatch()
                return
            }
            selected(patch.point, normal: patch.normal)
        }

        private func rejectPatch() {
            let message = "This contact patch is sparse, noisy, or crosses an edge. Select a broad surface at least 8 mm from an edge, or capture more views. Confirm critical contact geometry with measurements."
            parent.onReject(message)
            UIAccessibility.post(notification: .announcement, argument: message)
        }

        private func selected(_ position: SIMD3<Float>, normal: SIMD3<Float>) {
            guard let root = view?.scene?.rootNode else { return }
            markerNode?.removeFromParentNode()
            let marker = SCNNode()
            marker.simdPosition = position
            marker.categoryBitMask = 4
            let color: UIColor = parent.selectionMode == "damage" ? .systemPink : .systemYellow
            let size = CGFloat(min(0.004, max(0.0008, radius * 0.025)))
            let sphere = SCNSphere(radius: size)
            sphere.firstMaterial?.diffuse.contents = color
            sphere.firstMaterial?.lightingModel = .constant
            let dot = SCNNode(geometry: sphere)
            dot.categoryBitMask = 4
            marker.addChildNode(dot)
            let length = Float(size) * 5
            let stem = SCNCylinder(radius: size * 0.3, height: CGFloat(length))
            stem.firstMaterial?.diffuse.contents = color
            let arrow = SCNNode(geometry: stem)
            arrow.simdPosition = normal * length * 0.5
            arrow.simdOrientation = simd_quatf(from: SIMD3<Float>(0, 1, 0), to: normal)
            arrow.categoryBitMask = 4
            marker.addChildNode(arrow)
            root.addChildNode(marker)
            markerNode = marker
            UISelectionFeedbackGenerator().selectionChanged()
            parent.onSelect([Double(position.x), Double(position.y), Double(position.z)],
                            [Double(normal.x), Double(normal.y), Double(normal.z)])
        }

        func gestureRecognizer(_ gestureRecognizer: UIGestureRecognizer,
                               shouldRecognizeSimultaneouslyWith otherGestureRecognizer: UIGestureRecognizer) -> Bool { true }
    }
}

/// Fits only the observed local surface; the hit normal supplies orientation, never shape.
/// A bounded 8 mm patch averages tessellation jitter without flattening corners into a
/// confident attachment. The picked point is retained exactly; fitting changes only its normal.
enum SurfacePatchNormal {
    struct Estimate {
        let point: SIMD3<Float>
        let normal: SIMD3<Float>
        let rmsM: Double
        let sampleCount: Int
    }

    static func estimate(points: [SIMD3<Float>], center: SIMD3<Float>,
                         orientationHint: SIMD3<Float>, radius: Float = 0.008) -> Estimate? {
        guard center.x.isFinite, center.y.isFinite, center.z.isFinite,
              radius.isFinite, radius > 0 else { return nil }
        let neighbors = points.filter {
            $0.x.isFinite && $0.y.isFinite && $0.z.isFinite && simd_distance_squared($0, center) <= radius * radius
        }.sorted { simd_distance_squared($0, center) < simd_distance_squared($1, center) }.prefix(150)
        guard neighbors.count >= 12 else { return nil }
        let mean = neighbors.reduce(SIMD3<Float>.zero) { $0 + $1 } / Float(neighbors.count)
        var matrix = [[Double]](repeating: [Double](repeating: 0, count: 3), count: 3)
        var vectors: [[Double]] = [[1, 0, 0], [0, 1, 0], [0, 0, 1]]
        for neighbor in neighbors {
            let d = neighbor - mean
            for row in 0..<3 { for column in 0..<3 { matrix[row][column] += Double(d[row] * d[column]) } }
        }
        // Jacobi diagonalization of a symmetric 3x3 covariance matrix.
        for _ in 0..<16 {
            var p = 0, q = 1
            for row in 0..<3 { for column in (row + 1)..<3 {
                if abs(matrix[row][column]) > abs(matrix[p][q]) { p = row; q = column }
            } }
            if abs(matrix[p][q]) < 1e-14 { break }
            let angle = 0.5 * atan2(2 * matrix[p][q], matrix[q][q] - matrix[p][p])
            let c = cos(angle), s = sin(angle)
            let app = matrix[p][p], aqq = matrix[q][q], apq = matrix[p][q]
            for k in 0..<3 where k != p && k != q {
                let akp = matrix[k][p], akq = matrix[k][q]
                matrix[k][p] = c * akp - s * akq; matrix[p][k] = matrix[k][p]
                matrix[k][q] = s * akp + c * akq; matrix[q][k] = matrix[k][q]
            }
            matrix[p][p] = c * c * app - 2 * s * c * apq + s * s * aqq
            matrix[q][q] = s * s * app + 2 * s * c * apq + c * c * aqq
            matrix[p][q] = 0; matrix[q][p] = 0
            for k in 0..<3 {
                let vkp = vectors[k][p], vkq = vectors[k][q]
                vectors[k][p] = c * vkp - s * vkq
                vectors[k][q] = s * vkp + c * vkq
            }
        }

        let sorted = (0..<3).sorted { matrix[$0][$0] < matrix[$1][$1] }
        let minimum = sorted[0], middle = sorted[1], maximum = sorted[2]
        let count = Double(neighbors.count)
        let small = max(0, matrix[minimum][minimum]), medium = matrix[middle][middle], large = matrix[maximum][maximum]
        // Require a two-dimensional patch spanning at least 0.5 mm RMS in its weaker
        // tangent axis. Reject corners and excessive residuals rather than weakening fit gates.
        guard medium / count >= 0.0005 * 0.0005, large > 0,
              medium / large >= 0.03, small / medium <= 0.08,
              sqrt(small / count) <= 0.001 else { return nil }
        var normal = simd_normalize(SIMD3(Float(vectors[0][minimum]), Float(vectors[1][minimum]), Float(vectors[2][minimum])))
        if orientationHint.x.isFinite, orientationHint.y.isFinite, orientationHint.z.isFinite,
           simd_dot(normal, orientationHint) < 0 { normal = -normal }
        return Estimate(point: center, normal: normal, rmsM: sqrt(small / count), sampleCount: neighbors.count)
    }
}
