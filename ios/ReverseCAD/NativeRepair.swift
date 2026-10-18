import Foundation
import simd

/// Ports the conservative rectangular-part route: observed planar surface,
/// four supported straight edges, boundary-connected missing area, measured
/// thickness. This never modifies the scanned mesh or fills an interior hole.
enum NativeRepair {
    struct Result {var report:[String:Any];var preview:NativeMesh?;var files:[String];var printable:Bool;var reason:String}
    static func build(mesh:NativeMesh,thicknessMM:Double?,directory:URL)throws->Result {
        func unsupported(_ why:String)->Result {Result(report:["status":"unsupported","patches":[],"reason":why],preview:nil,files:[],printable:false,reason:why)}
        let points=mesh.vertices
        guard points.count>=80 else{return unsupported("More observations of the damaged surface are needed. The measured model is saved.")}
        var normal=SIMD3<Float>(0,0,1),origin=points[0],best=[Int](),seed:UInt64=412
        for _ in 0..<120 {
            var ids=Set<Int>();while ids.count<3 {seed=seed &* 6364136223846793005 &+ 1;ids.insert(Int((seed>>32)%UInt64(points.count)))}
            let a=ids.sorted(),cross=simd_cross(points[a[1]]-points[a[0]],points[a[2]]-points[a[0]])
            guard simd_length(cross)>1e-8 else{continue}
            let n=simd_normalize(cross),o=points[a[0]]
            let selected=points.indices.filter{abs(simd_dot(points[$0]-o,n))<0.003}
            if selected.count>best.count {best=selected;normal=n;origin=o}
        }
        guard Double(best.count)/Double(points.count)>0.55 else{return unsupported("Automatic repair supports flat rectangular parts. This shape does not have enough measured planar surface; its scan remains exportable.")}
        var u=simd_normalize(simd_cross(normal,abs(normal.z)<0.9 ? SIMD3<Float>(0,0,1):SIMD3<Float>(0,1,0)))
        var v=simd_cross(normal,u)
        let projected=best.map{p -> SIMD2<Float> in let d=points[p]-origin;return SIMD2(simd_dot(d,u),simd_dot(d,v))}
        var angle:Float=0,area=Float.infinity,lo=SIMD2<Float>.zero,hi=lo
        for step in 0..<360 {
            let a=Float(step)*Float.pi/720,c=cos(a),s=sin(a)
            var low=SIMD2<Float>(repeating:.infinity),high=SIMD2<Float>(repeating:-.infinity)
            for p in projected {let q=SIMD2(p.x*c+p.y*s,-p.x*s+p.y*c);low=simd_min(low,q);high=simd_max(high,q)}
            let size=high-low,candidate=size.x*size.y
            if candidate<area {area=candidate;angle=a;lo=low;hi=high}
        }
        let old=u;u=old*cos(angle)+v*sin(angle);v = -old*sin(angle)+v*cos(angle)
        let extent=hi-lo
        guard min(extent.x,extent.y)>0.02,max(extent.x,extent.y)<1 else{return unsupported("The flat part is too small or too poorly resolved for a supported repair.")}
        let cell=max(0.0005,max(extent.x,extent.y)/160),w=Int(ceil(extent.x/cell)),h=Int(ceil(extent.y/cell))
        var occupied=[Bool](repeating:false,count:w*h)
        let planar=Set(best)
        func xy(_ i:Int)->SIMD2<Float> {let p=points[i]-origin;return SIMD2(simd_dot(p,u),simd_dot(p,v))-lo}
        func cross(_ a:SIMD2<Float>,_ b:SIMD2<Float>)->Float {a.x*b.y-a.y*b.x}
        for f in mesh.faces where f.allSatisfy({planar.contains($0)}) {
            let a=xy(f[0]),b=xy(f[1]),c=xy(f[2]),den=cross(b-a,c-a)
            if abs(den)<1e-12 {continue}
            let low=simd_min(a,simd_min(b,c)),high=simd_max(a,simd_max(b,c))
            let x0=max(0,min(w-1,Int(floor(low.x/cell)))),x1=max(0,min(w-1,Int(ceil(high.x/cell))))
            let y0=max(0,min(h-1,Int(floor(low.y/cell)))),y1=max(0,min(h-1,Int(ceil(high.y/cell))))
            for y in y0...y1 {for x in x0...x1 {
                let p=SIMD2((Float(x)+0.5)*cell,(Float(y)+0.5)*cell)
                let s=cross(p-a,c-a)/den,t=cross(b-a,p-a)/den
                if s>=0,t>=0,s+t<=1 {occupied[y*w+x]=true}
            }}
        }
        let fraction=Float(occupied.filter{$0}.count)/Float(w*h)
        guard fraction>0.55 else{return unsupported("Too much of the planar outline is unobserved. Add a straight-on view of the whole damaged surface.")}
        let band=max(2,Int(min(extent.x,extent.y)*0.015/cell))
        let support:[Float]=[
            Float((0..<h).filter{y in (0..<min(w,band)).contains{occupied[y*w+$0]}}.count)/Float(h),
            Float((0..<h).filter{y in (max(0,w-band)..<w).contains{occupied[y*w+$0]}}.count)/Float(h),
            Float((0..<w).filter{x in (0..<min(h,band)).contains{occupied[$0*w+x]}}.count)/Float(w),
            Float((0..<w).filter{x in (max(0,h-band)..<h).contains{occupied[$0*w+x]}}.count)/Float(w)]
        guard support.min()!>=0.2,support.filter({$0>0.35}).count>=3 else{return unsupported("Show surviving portions of all four original straight edges. The app cannot infer a rectangular repair from this outline safely.")}
        var seen=Set<Int>(),regions=[[Int]]()
        func neighbors(_ i:Int)->[Int] {let x=i%w,y=i/w;return [(x>0 ? i-1:nil),(x<w-1 ? i+1:nil),(y>0 ? i-w:nil),(y<h-1 ? i+w:nil)].compactMap{$0}}
        for i in occupied.indices where !occupied[i] && !seen.contains(i) {
            var queue=[i],position=0,boundary=false;seen.insert(i)
            while position<queue.count {
                let j=queue[position];position+=1
                if j%w==0 || j%w==w-1 || j/w==0 || j/w==h-1 {boundary=true}
                for n in neighbors(j) where !occupied[n] && seen.insert(n).inserted {queue.append(n)}
            }
            let ratio=Float(queue.count)/Float(w*h)
            if boundary,ratio>=0.003,ratio<0.35,queue.count>=12 {regions.append(queue)}
        }
        guard !regions.isEmpty else{return unsupported("No supported missing edge region was found. Interior holes and unseen surfaces are preserved in the scan.")}
        let thickness=thicknessMM.flatMap{$0.isFinite && $0>0 && $0<=100 ? Float($0/1000):nil}
        var combined=NativeMesh(vertices:[],faces:[]),files=[String](),patches=[[String:Any]]()
        for (index,region) in regions.enumerated() {
            try Task.checkCancellation()
            let set=Set(region)
            struct Key:Hashable {let x:Int;let y:Int;let z:Int}
            var vertices=[SIMD3<Float>](),faces=[[Int]](),lookup=[Key:Int]()
            func vertex(_ x:Int,_ y:Int,_ z:Int)->Int {
                let key=Key(x:x,y:y,z:z);if let i=lookup[key] {return i}
                let p=origin+u*(lo.x+min(extent.x,Float(x)*cell))+v*(lo.y+min(extent.y,Float(y)*cell))-normal*(Float(z)*(thickness ?? 0))
                let i=vertices.count;lookup[key]=i;vertices.append(p);return i
            }
            func quad(_ a:Int,_ b:Int,_ c:Int,_ d:Int) {faces += [[a,b,c],[a,c,d]]}
            for i in region {
                let x=i%w,y=i/w
                let a=vertex(x,y,0),b=vertex(x+1,y,0),c=vertex(x+1,y+1,0),d=vertex(x,y+1,0)
                quad(a,b,c,d)
                if thickness != nil {
                    let e=vertex(x,y,1),f=vertex(x+1,y,1),g=vertex(x+1,y+1,1),h1=vertex(x,y+1,1)
                    quad(h1,g,f,e)
                    if x==0 || !set.contains(i-1) {quad(a,d,h1,e)}
                    if x==w-1 || !set.contains(i+1) {quad(c,b,f,g)}
                    if y==0 || !set.contains(i-w) {quad(b,a,e,f)}
                    if y==h-1 || !set.contains(i+w) {quad(d,c,g,h1)}
                }
            }
            let part=NativeMesh(vertices:vertices,faces:faces);try part.validate()
            let offset=combined.vertices.count;combined.vertices+=vertices;combined.faces+=faces.map{$0.map{$0+offset}}
            if thickness != nil {
                guard part.boundaryEdges==0 else{throw ServiceFailure(message:"The proposed repair did not close correctly. The measured model remains intact.")}
                files += try NativeMeshExport.write(part,to:directory,stem:"repair_\(index+1)",inferredRepair:true)
            }
            patches.append(["id":index+1,"area_mm2":Double(region.count)*Double(cell*cell)*1_000_000,"geometry_source":"inferred missing boundary of user-confirmed rectangular part","grid_resolution_mm":Double(cell)*1000])
        }
        let reason="Possible missing edge regions on a flat rectangular part. Confirm these are damage, not unobserved or intentional cutouts. The orange repair is inferred; blue geometry remains measured."
        let report:[String:Any]=["status":thickness == nil ? "needs_thickness":"proposal_needs_review","patches":patches,"piece_count":patches.count,"exports":files,"thickness_mm":thicknessMM as Any? ?? NSNull(),"thickness_source":"user_measurement","edge_support":support,"reason":reason,"physical_fit":"not_tested","step_kind":"faceted surface","interior_holes":"never patched"]
        try cameraJSONWrite(report,directory.appendingPathComponent("planar_repair.json"))
        return Result(report:report,preview:combined,files:files,printable:thickness != nil,reason:reason)
    }
}
