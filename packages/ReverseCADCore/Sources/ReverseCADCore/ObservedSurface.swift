import Foundation

/// An observed surface only: triangles never bridge absent masks or depth discontinuities.
public struct ObservedSurface: Sendable {
    public var vertices: [[Double]]
    public var triangles: [[Int]]
    public init(vertices: [[Double]], triangles: [[Int]]) { self.vertices = vertices; self.triangles = triangles }
    public static func depth(frame: CaptureFrame, depth: Data, confidence: Data, mask: Data, stride: Int = 4) throws -> Self {
        let w=frame.depthWidth, h=frame.depthHeight, step=max(1,stride)
        guard w>0,h>0,depth.count==w*h*4,confidence.count==w*h,mask.count==w*h else { throw CoreError.invalid("Depth preview buffers do not match.") }
        var points=[[Double]](), indices=[Int:Int](), depths=[Int:Double]()
        for y in Swift.stride(from:0,to:h,by:step) { for x in Swift.stride(from:0,to:w,by:step) {
            let i=y*w+x
            let d=Double(depth.withUnsafeBytes{$0.loadUnaligned(fromByteOffset:i*4,as:Float.self)})
            guard mask[i] != 0,confidence[i]>=1,d.isFinite,d>0.05,d<3 else { continue }
            indices[i]=points.count;depths[i]=d
            points.append(try Geometry.unproject(u:Double(x),v:Double(y),depthMeters:d,intrinsics:frame.intrinsics,intrinsicsWidth:frame.intrinsicsWidth,intrinsicsHeight:frame.intrinsicsHeight,depthWidth:w,depthHeight:h,worldCamera:frame.worldCamera,depthCalibrationMode:frame.depthCalibrationMode ?? "pixel_center"))
        } }
        var faces=[[Int]]()
        for y in Swift.stride(from:0,to:max(0,h-step),by:step) { for x in Swift.stride(from:0,to:max(0,w-step),by:step) {
            let a=y*w+x,b=a+step,c=(y+step)*w+x,d=c+step
            // A coarse display cell must not bridge a smaller unobserved hole.
            var interior=[Double](),complete=true
            for iy in y...y+step { for ix in x...x+step {
                let i=iy*w+ix
                let z=Double(depth.withUnsafeBytes{$0.loadUnaligned(fromByteOffset:i*4,as:Float.self)})
                if mask[i]==0 || confidence[i]<1 || !z.isFinite || z<=0.05 || z>=3 {complete=false}
                else {interior.append(z)}
            } }
            guard complete,let low=interior.min(),let high=interior.max(),high-low<=max(0.008,low*0.03) else{continue}
            for keys in [[a,b,c],[b,d,c]] {
                guard keys.allSatisfy({indices[$0] != nil}),let low=keys.compactMap({depths[$0]}).min(),let high=keys.compactMap({depths[$0]}).max(),high-low<=max(0.008,low*0.03) else {continue}
                faces.append(keys.map{indices[$0]!})
            }
        } }
        return Self(vertices:points,triangles:faces)
    }
}

/// Bounded preview accumulation in one uninterrupted world coordinate frame.
public struct ObservedSurfaceAccumulator: Sendable {
    public private(set) var vertices=[[Double]]()
    public private(set) var triangles=[[Int]]()
    private var cells=[String:Int](),faces=Set<String>()
    public init() {}
    public mutating func add(_ surface: ObservedSurface) {
        var mapped=[Int:Int]()
        for (i,p) in surface.vertices.enumerated() {
            guard p.count==3,p.allSatisfy({$0.isFinite && abs($0)<1000}) else{continue}
            let key=p.map{String(Int(floor($0/0.002)))}.joined(separator:":")
            if let existing=cells[key] { mapped[i]=existing }
            else if vertices.count<30_000 { mapped[i]=vertices.count;cells[key]=vertices.count;vertices.append(p) }
        }
        for face in surface.triangles where face.count==3 && triangles.count<60_000 {
            guard face.allSatisfy({mapped[$0] != nil}) else{continue}
            let f=face.map{mapped[$0]!};guard Set(f).count==3 else{continue}
            let key=f.sorted().map(String.init).joined(separator:":")
            if faces.insert(key).inserted {triangles.append(f)}
        }
    }
}
