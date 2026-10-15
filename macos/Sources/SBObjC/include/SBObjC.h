#import <Foundation/Foundation.h>
NS_ASSUME_NONNULL_BEGIN
/// Runs block, catching any Objective-C exception. Returns nil on success, or the exception reason.
NSString * _Nullable SBTryObjC(void (NS_NOESCAPE ^block)(void));
NS_ASSUME_NONNULL_END
