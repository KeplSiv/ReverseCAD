#import <Foundation/Foundation.h>
#import <CoreVideo/CoreVideo.h>
NS_ASSUME_NONNULL_BEGIN
NSDictionary *SRStart(NSString *directory);
NSDictionary *SRImageEvidence(CVPixelBufferRef image, double sourceTime, double arrivalTime);
NSDictionary *SRStatus(void);
NSDictionary *SRFinish(void);
NS_ASSUME_NONNULL_END
