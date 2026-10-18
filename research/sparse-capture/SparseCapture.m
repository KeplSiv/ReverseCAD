// Research-only adaptation of Prelude OriginProbe/InputGate source identification.
// These hooks observe and forward unchanged samples. See reuse.json and README.
#if !DEBUG || !SPARSE_RESEARCH
#error SparseCapture must only compile in the Debug research target
#endif
#import "SparseCapture.h"
#import <AVFoundation/AVFoundation.h>
#import <ARKit/ARKit.h>
#import <objc/runtime.h>
#import <objc/message.h>
#import <CommonCrypto/CommonDigest.h>
#import <math.h>

@interface SRRecorder : NSObject
@property(nonatomic,strong) NSLock *lock;
@property(nonatomic,strong) dispatch_queue_t queue;
@property(nonatomic,strong) dispatch_semaphore_t slots;
@property(nonatomic,strong) NSString *directory;
@property(nonatomic,strong) NSFileHandle *stream, *journal, *imageJournal;
@property(nonatomic,strong) NSMutableArray *recentImages, *errors;
@property(nonatomic,strong) NSDictionary *calibration;
@property NSUInteger sequence, bytes, packets, drops, imageDrops;
@property BOOL active;
@end
@implementation SRRecorder
@end
static SRRecorder *current;
static NSMutableArray *installed;
static char sourceKey;
static double now(void) {return CMTimeGetSeconds(CMClockGetTime(CMClockGetHostTimeClock()));}
static SRRecorder *recorder(void) {@synchronized(SRRecorder.class){return current;}}
static NSString *sha(NSData *d) {
 unsigned char h[CC_SHA256_DIGEST_LENGTH];CC_SHA256(d.bytes,(CC_LONG)d.length,h);
 NSMutableString *s=[NSMutableString string];for(int i=0;i<32;i++)[s appendFormat:@"%02x",h[i]];return s;
}
static id safe(id v) {
 if(!v)return NSNull.null;
 if([v isKindOfClass:NSNumber.class])return isfinite([v doubleValue])?v:NSNull.null;
 if([v isKindOfClass:NSString.class]||v==NSNull.null)return v;
 if([v isKindOfClass:NSData.class])return @{@"base64":[v base64EncodedStringWithOptions:0],@"sha256":sha(v),@"bytes":@([v length])};
 if([v isKindOfClass:NSArray.class]){NSMutableArray*a=[NSMutableArray array];for(id x in v)[a addObject:safe(x)];return a;}
 if([v isKindOfClass:NSDictionary.class]){NSMutableDictionary*d=[NSMutableDictionary dictionary];for(id k in v)d[[k description]]=safe(v[k]);return d;}
 return [v description];
}
static void line(NSFileHandle *file,NSDictionary *row) {
 NSData *d=[NSJSONSerialization dataWithJSONObject:safe(row) options:NSJSONWritingSortedKeys error:nil];
 if(!d)[NSException raise:@"InvalidJSON" format:@"Sensor metadata cannot be encoded"];
 [file writeData:d];[file writeData:[NSData dataWithBytes:"\n" length:1]];
}
static NSArray *hashPlanes(CVPixelBufferRef image) {
 if(!image||CVPixelBufferLockBaseAddress(image,kCVPixelBufferLock_ReadOnly)!=kCVReturnSuccess)return @[];
 NSMutableArray *a=[NSMutableArray array];
 size_t count=CVPixelBufferGetPlaneCount(image);
 if(count==2)for(size_t p=0;p<count;p++){
  const uint8_t *base=CVPixelBufferGetBaseAddressOfPlane(image,p);
  size_t h=CVPixelBufferGetHeightOfPlane(image,p),w=CVPixelBufferGetWidthOfPlane(image,p)*(p?2:1),stride=CVPixelBufferGetBytesPerRowOfPlane(image,p);
  if(!base||stride<w)continue;
  CC_SHA256_CTX c;CC_SHA256_Init(&c);for(size_t y=0;y<h;y++)CC_SHA256_Update(&c,base+y*stride,(CC_LONG)w);
  unsigned char hash[32];CC_SHA256_Final(hash,&c);NSMutableString *s=[NSMutableString string];for(int i=0;i<32;i++)[s appendFormat:@"%02x",hash[i]];[a addObject:s];
 }
 CVPixelBufferUnlockBaseAddress(image,kCVPixelBufferLock_ReadOnly);return a;
}
static NSDictionary *sourceInfo(id connection) {
 NSMutableArray *ports=[NSMutableArray array];
 @try {for(AVCaptureInputPort *port in [connection inputPorts]){
  NSMutableDictionary *r=[@{@"device_type":port.sourceDeviceType?:@"unknown",@"position":port.sourceDevicePosition==AVCaptureDevicePositionBack?@"back":@"other"} mutableCopy];
  if([port.input isKindOfClass:AVCaptureDeviceInput.class]){
   AVCaptureDevice *d=((AVCaptureDeviceInput*)port.input).device;
   r[@"device_id"]=d.uniqueID;r[@"lens_position"]=@(d.lensPosition);r[@"focus_mode"]=@(d.focusMode);
   r[@"adjusting_focus"]=@(d.adjustingFocus);r[@"exposure_s"]=@(CMTimeGetSeconds(d.exposureDuration));r[@"iso"]=@(d.ISO);
   r[@"zoom_factor"]=@(d.videoZoomFactor);r[@"distortion_correction"]=@(d.geometricDistortionCorrectionEnabled);
   r[@"readback_semantics"]=@"callback-time device readback; not independently timed exposure metadata";
  }
  [ports addObject:safe(r)];
 }}@catch(NSException *e){}
 return @{@"ports":ports,@"stabilization":connection?@([connection activeVideoStabilizationMode]):NSNull.null};
}
static void imageSample(CMSampleBufferRef sample,NSDictionary *source) {
 SRRecorder *r=recorder();if(!r)return; @synchronized(r) { if(!r.active||!sample)return;
 CVPixelBufferRef image=CMSampleBufferGetImageBuffer(sample);if(!image)return;
 // Only the source-identified physical rear 1x path enters the correspondence ring.
 NSDictionary *physical=nil;for(NSDictionary *p in source[@"ports"])
  if([p[@"device_type"] isEqual:AVCaptureDeviceTypeBuiltInWideAngleCamera]&&[p[@"position"] isEqual:@"back"]){physical=p;break;}
 if(!physical)return;
 double pts=CMTimeGetSeconds(CMSampleBufferGetPresentationTimeStamp(sample));if(!isfinite(pts))return;
 NSArray *hashes=hashPlanes(image);
 NSDictionary *metadata=(__bridge NSDictionary*)CMGetAttachment(sample,CFSTR("MetadataDictionary"),NULL);
 NSMutableDictionary *selected=[NSMutableDictionary dictionary];
 for(NSString *key in @[@"PortType",@"SensorID",@"FrameCount",@"ExposureTime",@"FrameRollingShutterSkew",@"DigitalZoomFactor",@"TotalSensorCropRect",@"SensorCropRect",@"FocusActuatorMoving",@"CurrentFocusPosition",@"LensPosition"])
  if(metadata[key])selected[key]=metadata[key];
 NSDictionary *row=safe(@{@"pts":@(pts),@"arrival":@(now()),@"width":@(CVPixelBufferGetWidth(image)),@"height":@(CVPixelBufferGetHeight(image)),
  @"pixel_sha256":hashes,@"physical_camera":physical,@"source":source,@"sample_metadata":selected,
  @"sensor_crop":@"Only supplied metadata is known; no app crop or rotation"});
 [r.lock lock];
 BOOL duplicate=NO;for(NSDictionary *old in r.recentImages)if([old[@"pts"] isEqual:row[@"pts"]]){duplicate=YES;break;}
 if(!duplicate){[r.recentImages addObject:row];if(r.recentImages.count>96)[r.recentImages removeObjectAtIndex:0];}
 [r.lock unlock];
 if(duplicate)return;
 if(dispatch_semaphore_wait(r.slots,DISPATCH_TIME_NOW)!=0){[r.lock lock];r.imageDrops++;[r.lock unlock];return;}
 dispatch_async(r.queue,^{@try{line(r.imageJournal,row);}@catch(NSException *e){[r.lock lock];[r.errors addObject:e.reason?:e.name];[r.lock unlock];}dispatch_semaphore_signal(r.slots);});
}
}
static void packet(CMSampleBufferRef sample) {
 SRRecorder *r=recorder();if(!r)return; @synchronized(r) { if(!r.active||!sample)return;
 double arrival=now(),pts=CMTimeGetSeconds(CMSampleBufferGetPresentationTimeStamp(sample));
 [r.lock lock];NSUInteger sequence=++r.sequence;[r.lock unlock];
 if(dispatch_semaphore_wait(r.slots,DISPATCH_TIME_NOW)!=0){[r.lock lock];r.drops++;[r.lock unlock];return;}
 CMBlockBufferRef b=CMSampleBufferGetDataBuffer(sample);size_t n=b?CMBlockBufferGetDataLength(b):0;
 if(n<128||n>1024*1024||!isfinite(pts)){[r.lock lock];r.drops++;[r.lock unlock];dispatch_semaphore_signal(r.slots);return;}
 NSMutableData *data=[NSMutableData dataWithLength:n];
 if(CMBlockBufferCopyDataBytes(b,0,n,data.mutableBytes)!=noErr){[r.lock lock];r.drops++;[r.lock unlock];dispatch_semaphore_signal(r.slots);return;}
 NSDictionary *meta=(__bridge NSDictionary*)CMGetAttachment(sample,CFSTR("MetadataDictionary"),NULL);
 NSMutableDictionary *selected=[NSMutableDictionary dictionary];for(NSString *k in @[@"PortType",@"SensorID",@"FrameCount",@"JasperBankId",@"ExposureTime",@"TFEnabled",@"RawMetaData"])if(meta[k])selected[k]=safe(meta[k]);
 NSDictionary *metadata=[selected copy];
 dispatch_async(r.queue,^{@try{
  if(r.bytes+n>32*1024*1024){[r.lock lock];r.drops++;[r.lock unlock];return;}
  NSUInteger offset=r.bytes;[r.stream writeData:data];r.bytes+=n;
  line(r.journal,@{@"event":@"pointCloudSampleBuffer",@"sequence":@(sequence),@"pts":@(pts),@"host":@(arrival),@"seriesOffset":@(offset),@"seriesBytes":@(n),@"sha256":sha(data),@"sensorMetadata":metadata});
  [r.lock lock];r.packets++;NSUInteger count=r.packets;[r.lock unlock];
  if(count%30==0){[r.stream synchronizeFile];[r.journal synchronizeFile];}
 }@catch(NSException *e){[r.lock lock];[r.errors addObject:e.reason?:e.name];[r.lock unlock];}
 @finally{dispatch_semaphore_signal(r.slots);}});
}
}
static void extrinsics(id sensor) {
 SRRecorder *r=recorder();if(!r||!r.active)return;
 [r.lock lock];BOOL missing=r.calibration==nil;[r.lock unlock];if(!missing)return;
 @try {
  Ivar ivar=class_getInstanceVariable([sensor class],"_extrinsicsMap");id map=ivar?object_getIvar(sensor,ivar):nil;
  id value=map[AVCaptureDeviceTypeBuiltInWideAngleCamera];
  if(![value isKindOfClass:NSData.class]||[value length]!=64)return;
  const float *p=[(NSData *)value bytes];NSMutableArray *a=[NSMutableArray array];
  for(int i=0;i<16;i++){if(!isfinite(p[i]))return;[a addObject:@(i==15?1:p[i])];}
  // Observed 4x3 affine matrix is padded to four SIMD lanes. Padding is not homogeneous w.
  a[3]=@0;a[7]=@0;a[11]=@0;
  NSDictionary *cal=@{@"schema_version":@1,@"T_sparse_camera":a,@"direction":@"camera_cv_to_sparse",@"translation_unit":@"mm",
   @"layout":@"column_major",@"camera_type":AVCaptureDeviceTypeBuiltInWideAngleCamera,@"raw_extrinsic":safe(value),
   @"source":@"ARDepthSensor._extrinsicsMap; observed convention checked against saved ruler evidence",
   @"homogeneous_padding":@"raw SIMD fourth lanes replaced by 0,0,0,1",@"physical_emitter_origin_verified":@NO,
   @"independent_calibration_accuracy":NSNull.null};
  [r.lock lock];r.calibration=cal;[r.lock unlock];
 }@catch(NSException *e){}
}
static BOOL hook(NSString *className,NSString *selector,const char *encoding,id block) {
 Method m=class_getInstanceMethod(NSClassFromString(className),NSSelectorFromString(selector));
 if(!m||strcmp(method_getTypeEncoding(m),encoding)!=0)return NO;
 // Caller blocks invoke an original captured before this installation.
 method_setImplementation(m,imp_implementationWithBlock(block));[installed addObject:[className stringByAppendingFormat:@".%@",selector]];return YES;
}
static void install(void) {
 static dispatch_once_t once;dispatch_once(&once,^{
  installed=[NSMutableArray array];
  NSString *name=@"_processSampleBuffer:";SEL sel=NSSelectorFromString(name);Method m=class_getInstanceMethod(NSClassFromString(@"AVCapturePointCloudDataOutput"),sel);
  if(m){IMP old=method_getImplementation(m);hook(@"AVCapturePointCloudDataOutput",name,"v24@0:8^{opaqueCMSampleBuffer=}16",^(id obj,CMSampleBufferRef s){packet(s);((void(*)(id,SEL,CMSampleBufferRef))old)(obj,sel,s);});}
  name=@"pointCloudDataOutput:didOutputPointCloudData:timestamp:connection:";sel=NSSelectorFromString(name);m=class_getInstanceMethod(NSClassFromString(@"ARDepthSensor"),sel);
  if(m){IMP old=method_getImplementation(m);SEL selector=sel;hook(@"ARDepthSensor",name,"v64@0:8@16@24{?=qiIq}32@56",^(id obj,id output,id data,CMTime t,id connection){((void(*)(id,SEL,id,id,CMTime,id))old)(obj,selector,output,data,t,connection);extrinsics(obj);});}
  name=@"synchronizedDataForCaptureOutput:";sel=NSSelectorFromString(name);m=class_getInstanceMethod(NSClassFromString(@"AVCaptureSynchronizedDataCollection"),sel);
  if(m){IMP old=method_getImplementation(m);SEL selector=sel;hook(@"AVCaptureSynchronizedDataCollection",name,"@24@0:8@16",^id(id obj,id output){id v=((id(*)(id,SEL,id))old)(obj,selector,output);if(v){NSArray *connections=[output connections];objc_setAssociatedObject(v,&sourceKey,sourceInfo(connections.firstObject),OBJC_ASSOCIATION_RETAIN_NONATOMIC);}return v;});}
  name=@"sampleBuffer";sel=NSSelectorFromString(name);m=class_getInstanceMethod(NSClassFromString(@"AVCaptureSynchronizedSampleBufferData"),sel);
  if(m){IMP old=method_getImplementation(m);SEL selector=sel;hook(@"AVCaptureSynchronizedSampleBufferData",name,"^{opaqueCMSampleBuffer=}16@0:8",^CMSampleBufferRef(id obj){CMSampleBufferRef s=((CMSampleBufferRef(*)(id,SEL))old)(obj,selector);imageSample(s,objc_getAssociatedObject(obj,&sourceKey)?:@{});return s;});}
  for(NSString *cls in @[@"ARImageSensor",@"ARParentImageSensor"]){
   NSString *name=@"captureOutput:didOutputSampleBuffer:fromConnection:";SEL selector=NSSelectorFromString(name);Method m=class_getInstanceMethod(NSClassFromString(cls),selector);
   if(m){IMP old=method_getImplementation(m);hook(cls,name,"v40@0:8@16^{opaqueCMSampleBuffer=}24@32",^(id obj,id output,CMSampleBufferRef s,id connection){imageSample(s,sourceInfo(connection));((void(*)(id,SEL,id,CMSampleBufferRef,id))old)(obj,selector,output,s,connection);});}
  }
 });
}
NSDictionary *SRStart(NSString *directory) {
 if(recorder().active)return @{@"error":@"A research scan is already active"};
 SRRecorder *r=[SRRecorder new];r.lock=[NSLock new];r.queue=dispatch_queue_create("ReverseCAD.sparse-write",DISPATCH_QUEUE_SERIAL);
 r.slots=dispatch_semaphore_create(16);r.directory=directory;r.recentImages=[NSMutableArray array];r.errors=[NSMutableArray array];
 NSError *error=nil;[[NSFileManager defaultManager]createDirectoryAtPath:directory withIntermediateDirectories:YES attributes:nil error:&error];
 for(NSString *name in @[@"origin-packets.bin",@"origin-events.jsonl",@"image-events.jsonl"]){
  NSString *path=[directory stringByAppendingPathComponent:name];
  if([[NSFileManager defaultManager] fileExistsAtPath:path])return @{@"error":@"Capture destination already exists; originals preserved"};
  if(![[NSFileManager defaultManager]createFileAtPath:path contents:nil attributes:nil])return @{@"error":@"Unable to create sparse journal"};
 }
 r.stream=[NSFileHandle fileHandleForWritingAtPath:[directory stringByAppendingPathComponent:@"origin-packets.bin"]];
 r.journal=[NSFileHandle fileHandleForWritingAtPath:[directory stringByAppendingPathComponent:@"origin-events.jsonl"]];
 r.imageJournal=[NSFileHandle fileHandleForWritingAtPath:[directory stringByAppendingPathComponent:@"image-events.jsonl"]];
 NSDictionary *initialCal=@{@"schema_version":@1,@"T_sparse_camera":NSNull.null,@"reason":@"Capture pending"};
 [[NSJSONSerialization dataWithJSONObject:initialCal options:0 error:nil] writeToFile:[directory stringByAppendingPathComponent:@"calibration.json"] atomically:YES];
 install();r.active=YES;@synchronized(SRRecorder.class){current=r;}
 return SRStatus();
}
NSDictionary *SRStatus(void) {
 SRRecorder *r=recorder();if(!r)return @{@"available":@NO};
 [r.lock lock];NSDictionary *status=@{@"available":@(r.packets>0),@"active":@(r.active),@"packets":@(r.packets),@"packet_callbacks":@(r.sequence),
 @"packet_drops":@(r.drops),@"image_journal_drops":@(r.imageDrops),@"hooks":installed?:@[],@"errors":[r.errors copy],@"extrinsics_available":@(r.calibration!=nil)};[r.lock unlock];return status;
}
NSDictionary *SRImageEvidence(CVPixelBufferRef image,double sourceTime,double arrivalTime) {
 SRRecorder *r=recorder();NSDictionary *matched=nil;NSArray *hashes=hashPlanes(image);
 [r.lock lock];for(NSDictionary *row in r.recentImages)if(fabs([row[@"pts"] doubleValue]-sourceTime)<.000001&&
 [row[@"width"] unsignedIntegerValue]==CVPixelBufferGetWidth(image)&&[row[@"height"] unsignedIntegerValue]==CVPixelBufferGetHeight(image)){matched=row;break;}[r.lock unlock];
 BOOL verified=matched&&hashes.count==2&&[hashes isEqual:matched[@"pixel_sha256"]];
 NSMutableDictionary *physical=[(matched[@"physical_camera"]?:@{}) mutableCopy];physical[@"verified"]=@(verified);
 return safe(@{@"source_timestamp_s":@(sourceTime),@"arrival_timestamp_s":@(arrivalTime),@"clock":@"host_monotonic_seconds",
 @"pixel_format":@(CVPixelBufferGetPixelFormatType(image)),
 @"physical_camera":physical,@"pixel_sha256":hashes,@"input_image":matched?:NSNull.null,@"pose_source":@"public_ARKit_visual_inertial_estimate",
 @"RGB_control":@"unaltered; no black replacement; upstream Apple processing unknown",@"identity_check":@"source ports plus identical PTS, dimensions and active-plane hashes"});
}
NSDictionary *SRFinish(void) {
 SRRecorder *r=recorder();if(!r)return @{}; @synchronized(r) { [r.lock lock];r.active=NO;[r.lock unlock];
 dispatch_sync(r.queue,^{@try{[r.stream synchronizeFile];[r.journal synchronizeFile];[r.imageJournal synchronizeFile];}@catch(NSException *e){[r.errors addObject:e.reason?:e.name];}});
 NSDictionary *cal=r.calibration?:@{@"schema_version":@1,@"T_sparse_camera":NSNull.null,@"reason":@"No compatible sensor extrinsic observed"};
 NSData *data=[NSJSONSerialization dataWithJSONObject:safe(cal) options:NSJSONWritingPrettyPrinted error:nil];
 [data writeToFile:[r.directory stringByAppendingPathComponent:@"calibration.json"] atomically:YES];
 NSDictionary *status=SRStatus();
 [[NSJSONSerialization dataWithJSONObject:safe(status) options:NSJSONWritingPrettyPrinted error:nil] writeToFile:[r.directory stringByAppendingPathComponent:@"status.json"] atomically:YES];
 [r.stream closeFile];[r.journal closeFile];[r.imageJournal closeFile];
 return SRStatus();
}
}
