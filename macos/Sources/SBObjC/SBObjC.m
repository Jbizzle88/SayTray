#import "SBObjC.h"
NSString * _Nullable SBTryObjC(void (NS_NOESCAPE ^block)(void)) {
  @try { block(); return nil; }
  @catch (NSException *e) { return [NSString stringWithFormat:@"%@: %@", e.name, e.reason]; }
}
