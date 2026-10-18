import Foundation
import simd
import ReverseCADCore

/// Metres internally. These faces always descend from observed depth cells;
/// neither the fusion nor any exporter closes boundaries or supplies hidden faces.
struct NativeMesh: Sendable {
    var vertices: [SIMD3<Float>]
    var faces: [[Int]]
    var preview: MeshPreview { MeshPreview(vertices: vertices.map { [Double($0.x)*1000,Double($0.y)*1000,Double($0.z)*1000] }, triangles: faces, unit: "mm") }
    func validate() throws {
        guard vertices.count >= 3, !faces.isEmpty, vertices.allSatisfy({ $0.x.isFinite && $0.y.isFinite && $0.z.isFinite }),
              faces.allSatisfy({ f in f.count == 3 && Set(f).count == 3 && f.allSatisfy { vertices.indices.contains($0) } && simd_length(simd_cross(vertices[f[1]]-vertices[f[0]],vertices[f[2]]-vertices[f[0]])) > 1e-12 }) else {
            throw ServiceFailure(message: "The observed surface has no valid triangles. Add closer, overlapping views; the capture is saved.")
        }
    }
    var boundaryEdges: Int {
        var edges = [Edge: Int]()
        for f in faces { for i in 0..<3 { edges[Edge(f[i],f[(i+1)%3]),default:0] += 1 } }
        return edges.values.filter { $0 == 1 }.count
    }
    struct Edge: Hashable { let a:Int; let b:Int; init(_ x:Int,_ y:Int) { a=min(x,y);b=max(x,y) } }
}

struct NativeSurfaceFusion {
    struct Cell: Hashable { let x:Int;let y:Int;let z:Int }
    struct Face: Hashable {let a:Int;let b:Int;let c:Int;init(_ f:[Int]) {let s=f.sorted();a=s[0];b=s[1];c=s[2]}}
    let voxel:Float
    private var index = [Cell:[Int]]()
    private var sums = [SIMD3<Float>](), weights = [Float]()
    private var normals=[SIMD3<Float>](),protected=[Bool]()
    private var faces = [[Int]](), unique = Set<Face>()
    init(voxel:Float = 0.002) { self.voxel=voxel }
    mutating func add(_ surface:NativeMesh, weight:Float = 1) throws {
        var map = [Int:Int]()
        var edges=[NativeMesh.Edge:Int](),directions=[SIMD3<Float>](repeating:.zero,count:surface.vertices.count)
        for f in surface.faces {
            let n=simd_cross(surface.vertices[f[1]]-surface.vertices[f[0]],surface.vertices[f[2]]-surface.vertices[f[0]])
            for j in 0..<3 {edges[NativeMesh.Edge(f[j],f[(j+1)%3]),default:0]+=1;directions[f[j]]+=n}
        }
        let boundary=Set(edges.filter{$0.value==1}.flatMap{[$0.key.a,$0.key.b]})
        var used=Set<Int>()
        for (i,p) in surface.vertices.enumerated() {
            let key=Cell(x:Int(floor(p.x/voxel)),y:Int(floor(p.y/voxel)),z:Int(floor(p.z/voxel)))
            let n=simd_length(directions[i])>1e-12 ? simd_normalize(directions[i]):.zero
            // Never collapse two vertices of the same observation or weld a
            // measured boundary. Even a sub-voxel hole keeps its exact edges.
            if !boundary.contains(i),let j=index[key]?.first(where:{!protected[$0] && !used.contains($0) && simd_dot(normals[$0],n)>0.8}) {
                sums[j] += p*weight;weights[j] += weight;map[i]=j;used.insert(j)
            }
            else {
                guard sums.count < 240_000 else { throw ServiceFailure(message:"This surface exceeds the phone's processing budget. Keep this scan and use a closer, smaller selection.") }
                let j=sums.count;index[key,default:[]].append(j);map[i]=j;used.insert(j);sums.append(p*weight);weights.append(weight);normals.append(n);protected.append(boundary.contains(i))
            }
        }
        for f in surface.faces {
            let mapped=f.compactMap {map[$0]}
            if mapped.count==3,Set(mapped).count==3,unique.insert(Face(mapped)).inserted {faces.append(mapped)}
        }
        guard faces.count<480_000 else {throw ServiceFailure(message:"The surface is too large to finish on this phone. Your capture remains saved.")}
    }
    func finish() throws -> NativeMesh {
        let points=zip(sums,weights).map{$0/$1}
        let valid=faces.filter {f in
            let a=points[f[0]],b=points[f[1]],c=points[f[2]]
            return simd_length(simd_cross(b-a,c-a))>1e-12
        }
        // Drop unused samples, but never bridge components or fill a boundary.
        let used=Set(valid.flatMap{$0}).sorted(),map=Dictionary(uniqueKeysWithValues:used.enumerated().map{($0.element,$0.offset)})
        let mesh=NativeMesh(vertices:used.map{points[$0]},faces:valid.map{$0.map{map[$0]!}})
        try mesh.validate();return mesh
    }
}

enum NativeMeshExport {
    static func write(_ mesh:NativeMesh, to directory:URL, stem:String, inferredRepair:Bool = false) throws -> [String] {
        try mesh.validate()
        let mm=mesh.vertices.map{$0*1000}
        var stl=Data(repeating:0,count:80)
        let kind=inferredRepair ? "inferred repair" : "measured geometry"
        let title=Data("ReverseCAD \(kind); millimetres".utf8)
        stl.replaceSubrange(0..<title.count,with:title)
        func append<T>(_ value:T,to data:inout Data) {var value=value;withUnsafeBytes(of:&value){data.append(contentsOf:$0)}}
        append(UInt32(mesh.faces.count).littleEndian,to:&stl)
        for f in mesh.faces {
            let a=mm[f[0]],b=mm[f[1]],c=mm[f[2]],n=simd_normalize(simd_cross(b-a,c-a))
            for p in [n,a,b,c] {for v in [p.x,p.y,p.z] {append(v.bitPattern.littleEndian,to:&stl)}}
            append(UInt16(0),to:&stl)
        }
        try stl.write(to:directory.appendingPathComponent(stem+".stl"),options:.atomic)
        var ply="ply\nformat binary_little_endian 1.0\ncomment ReverseCAD \(kind); millimetres; original boundaries retained\nelement vertex \(mm.count)\nproperty float x\nproperty float y\nproperty float z\nelement face \(mesh.faces.count)\nproperty list uchar int vertex_indices\nend_header\n"
        var bytes=Data(ply.utf8);ply=""
        for p in mm {for v in [p.x,p.y,p.z] {append(v.bitPattern.littleEndian,to:&bytes)}}
        for f in mesh.faces {bytes.append(3);for i in f {append(Int32(i).littleEndian,to:&bytes)}}
        try bytes.write(to:directory.appendingPathComponent(stem+".ply"),options:.atomic)
        var names=[stem+".stl",stem+".ply"]
        // Exact facets, no decimation and no claim of a closed parametric solid.
        if mesh.faces.count<=20_000 {
            try step(mesh,inferredRepair:inferredRepair).write(to:directory.appendingPathComponent(stem+".step"),atomically:true,encoding:.utf8)
            names.append(stem+".step")
        }
        return names
    }
    static func step(_ mesh:NativeMesh,inferredRepair:Bool = false) -> String {
        let kind=inferredRepair ? "Inferred repair facets" : "Observed facets; open boundaries retained"
        var lines=[String]()
        @discardableResult func entity(_ body:String)->Int {lines.append("#\(lines.count+1)=\(body);");return lines.count}
        func refs(_ ids:[Int])->String {ids.map{"#\($0)"}.joined(separator:",")}
        let app=entity("APPLICATION_CONTEXT('automotive design')")
        entity("APPLICATION_PROTOCOL_DEFINITION('international standard','automotive_design',2000,#\(app))")
        let context=entity("PRODUCT_CONTEXT('',#\(app),'mechanical')")
        let product=entity("PRODUCT('ReverseCAD','ReverseCAD faceted surface','\(kind)',(#\(context)))")
        let formation=entity("PRODUCT_DEFINITION_FORMATION('','',#\(product))")
        let definitionContext=entity("PRODUCT_DEFINITION_CONTEXT('part definition',#\(app),'design')")
        let definition=entity("PRODUCT_DEFINITION('design','',#\(formation),#\(definitionContext))")
        let shape=entity("PRODUCT_DEFINITION_SHAPE('','',#\(definition))")
        let length=entity("(LENGTH_UNIT() NAMED_UNIT(*) SI_UNIT(.MILLI.,.METRE.))")
        let angle=entity("(NAMED_UNIT(*) PLANE_ANGLE_UNIT() SI_UNIT($,.RADIAN.))")
        let solidAngle=entity("(NAMED_UNIT(*) SI_UNIT($,.STERADIAN.) SOLID_ANGLE_UNIT())")
        let uncertainty=entity("UNCERTAINTY_MEASURE_WITH_UNIT(LENGTH_MEASURE(1.E-6),#\(length),'distance_accuracy_value','export representation tolerance, not measurement accuracy')")
        let geometric=entity("(GEOMETRIC_REPRESENTATION_CONTEXT(3) GLOBAL_UNCERTAINTY_ASSIGNED_CONTEXT((#\(uncertainty))) GLOBAL_UNIT_ASSIGNED_CONTEXT((#\(length),#\(angle),#\(solidAngle))) REPRESENTATION_CONTEXT('','3D'))")
        func scalar(_ n:Double)->String {String(format:"%.16e",locale:Locale(identifier:"en_US_POSIX"),n)}
        func number(_ n:Float)->String {scalar(Double(n)*1000)}
        let points=mesh.vertices.map{entity("CARTESIAN_POINT('',(\(number($0.x)),\(number($0.y)),\(number($0.z))))")}
        let vertices=points.map{entity("VERTEX_POINT('',#\($0))")}
        let precise=mesh.vertices.map{SIMD3<Double>(Double($0.x)*1000,Double($0.y)*1000,Double($0.z)*1000)}
        var shells=[Int]()
        for f in mesh.faces {
            var edges=[Int]()
            for i in 0..<3 {
                let a=f[i],b=f[(i+1)%3],delta=precise[b]-precise[a],length=simd_length(delta),d=delta/length
                let direction=entity("DIRECTION('',(\(scalar(d.x)),\(scalar(d.y)),\(scalar(d.z))))")
                let vector=entity("VECTOR('',#\(direction),\(scalar(length)))")
                let line=entity("LINE('',#\(points[a]),#\(vector))")
                let edge=entity("EDGE_CURVE('',#\(vertices[a]),#\(vertices[b]),#\(line),.T.)")
                edges.append(entity("ORIENTED_EDGE('',*,*,#\(edge),.T.)"))
            }
            let loop=entity("EDGE_LOOP('',(\(refs(edges))))")
            let bound=entity("FACE_OUTER_BOUND('',#\(loop),.T.)")
            let a=precise[f[0]],b=precise[f[1]],c=precise[f[2]]
            let normal=simd_normalize(simd_cross(b-a,c-a)),u=simd_normalize(b-a)
            let direction=entity("DIRECTION('',(\(scalar(Double(normal.x))),\(scalar(Double(normal.y))),\(scalar(Double(normal.z)))))")
            let tangent=entity("DIRECTION('',(\(scalar(Double(u.x))),\(scalar(Double(u.y))),\(scalar(Double(u.z)))))")
            let axis=entity("AXIS2_PLACEMENT_3D('',#\(points[f[0]]),#\(direction),#\(tangent))")
            let plane=entity("PLANE('',#\(axis))")
            let face=entity("ADVANCED_FACE('',(#\(bound)),#\(plane),.T.)")
            shells.append(entity("OPEN_SHELL('',(#\(face)))"))
        }
        // Independent analytic planar faces avoid an importer sewing overlapping
        // observations or treating this intentionally open mesh as a closed solid.
        let surface=entity("SHELL_BASED_SURFACE_MODEL('\(kind)',(\(refs(shells))))")
        let representation=entity("MANIFOLD_SURFACE_SHAPE_REPRESENTATION('Faceted surface',(#\(surface)),#\(geometric))")
        entity("SHAPE_DEFINITION_REPRESENTATION(#\(shape),#\(representation))")
        return "ISO-10303-21;\nHEADER;\nFILE_DESCRIPTION(('ReverseCAD faceted surface'),'2;1');\nFILE_NAME('surface.step','',(''),(''),'ReverseCAD','ReverseCAD','');\nFILE_SCHEMA(('AUTOMOTIVE_DESIGN'));\nENDSEC;\nDATA;\n"+lines.joined(separator:"\n")+"\nENDSEC;\nEND-ISO-10303-21;\n"
    }
}
