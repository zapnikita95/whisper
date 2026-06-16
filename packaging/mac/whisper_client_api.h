#import <Foundation/Foundation.h>

@class WCAppDelegate;

void WCShowSettingsPanel(WCAppDelegate *app);
void wcLog(NSString *fmt, ...);
NSString *wcServerURL(NSDictionary *prefs);
NSString *wcBackend(NSDictionary *prefs, NSDictionary *env);
NSString *wcPasteMode(NSDictionary *prefs);
NSString *wcBackendLabel(NSString *mode);
BOOL wcHttpRequest(NSString *method, NSString *urlString, NSData *body, NSDictionary *headers,
                   NSTimeInterval timeout, NSInteger *outStatus, NSData **outBody, NSError **outErr);
