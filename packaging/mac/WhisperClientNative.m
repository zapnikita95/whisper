/*
 * WhisperClient — нативный MAS клиент: menubar, CGEventTap, Groq/сервер, вставка.
 */
#import <Cocoa/Cocoa.h>
#import <AVFoundation/AVFoundation.h>
#import <ApplicationServices/ApplicationServices.h>
#import <Carbon/Carbon.h>
#import <UserNotifications/UserNotifications.h>
#import <ServiceManagement/ServiceManagement.h>
#import <IOKit/pwr_mgt/IOPMLib.h>
#import <CoreAudio/CoreAudio.h>
#include <pwd.h>
#import <pthread.h>
#import <string.h>
#import <math.h>
#import <signal.h>
#import <unistd.h>
#import "whisper_client_api.h"
#if __has_include("ParakeetKit-Swift.h")
#import "ParakeetKit-Swift.h"
#define WC_HAS_PARAKEET 1
#elif __has_include(<ParakeetKit/ParakeetKit-Swift.h>)
#import <ParakeetKit/ParakeetKit-Swift.h>
#define WC_HAS_PARAKEET 1
#else
#define WC_HAS_PARAKEET 0
#endif

static NSString *const kDefaultServerHost = @"100.115.68.2";
static const NSInteger kDefaultServerPort = 8001;
static NSString *const kGroqURL = @"https://api.groq.com/openai/v1/audio/transcriptions";
static NSString *const kGroqModel = @"whisper-large-v3";
/* Railway origin — стабильнее Layero на больших POST; Layero оставляем как RF-опцию в prefs. */
static NSString *const kDefaultGroqProxyURL = @"https://whisper-groq-proxy-production.up.railway.app";

static const CGEventFlags kModFn = kCGEventFlagMaskSecondaryFn;
static const CGEventFlags kOtherMods =
    (kCGEventFlagMaskCommand | kCGEventFlagMaskControl | kCGEventFlagMaskAlternate | kCGEventFlagMaskShift);
static CFMachPortRef g_tap = NULL;
static BOOL g_hotkeyPressed = NO;
static BOOL g_fnBitDown = NO;
static volatile int g_tapRunning = 0;
static pthread_t g_tapThread;
static CFRunLoopRef g_tapLoop = NULL;

@interface WCAppDelegate : NSObject <NSApplicationDelegate, NSMenuDelegate, AVAudioRecorderDelegate>
@property(nonatomic, strong) NSStatusItem *statusItem;
@property(nonatomic, strong) NSMenu *statusMenu;
@property(nonatomic, strong) id activityToken;
@property(nonatomic, copy) NSString *appVersion;
@property(nonatomic, strong) AVAudioRecorder *audioRecorder;
@property(nonatomic, copy) NSString *wavPath;
@property(nonatomic, assign) pid_t pasteTargetPID;
@property(nonatomic, assign) BOOL recording;
@property(nonatomic, assign) BOOL menuRecording;
@property(nonatomic, assign) BOOL latchRecording; /* клик по иконке/меню — Fn-up не останавливает */
@property(nonatomic, assign) BOOL processing; /* afconvert/upload — UI must stay alive */
@property(nonatomic, assign) BOOL menuIsOpen;
@property(nonatomic, assign) BOOL menuNeedsRebuild;
@property(nonatomic, strong) NSTimer *maxRecordTimer;
@property(nonatomic, strong) NSTimer *meterTimer;
@property(nonatomic, strong) NSTimer *heartbeatTimer;
@property(nonatomic, strong) AVAudioPlayer *silentKeepAlivePlayer;
@property(nonatomic, assign) NSUInteger heartbeatTicks;
@property(nonatomic, assign) IOPMAssertionID napAssertion;
@property(nonatomic, strong) NSMutableDictionary *prefs;
@property(nonatomic, strong) NSDictionary *env;
@property(nonatomic, assign) NSUInteger recordPeakAbs;
@property(nonatomic, assign) NSUInteger recordSilentBuffers;
@property(nonatomic, assign) NSUInteger recordTotalBuffers;
@property(nonatomic, assign) AudioDeviceID savedInputDevice;
- (void)onHotkeyDown;
- (void)onHotkeyUp;
- (NSString *)convertRecordingToWav:(NSString *)src;
- (void)reloadPrefs;
- (void)rebuildMenu;
- (void)savePrefs;
- (void)userNotify:(NSString *)title body:(NSString *)body;
- (void)finishProcessingAfterDelay:(NSTimeInterval)sec;
- (void)openSettings:(id)sender;
- (void)editServerURL:(id)sender;
- (void)clearServer:(id)sender;
- (void)pingServer:(id)sender;
- (void)setBackendServer:(id)sender;
- (void)setBackendGroq:(id)sender;
- (void)setBackendServerGroq:(id)sender;
- (void)setBackendGroqServer:(id)sender;
- (void)setBackendFromMenu:(id)sender;
- (void)setPolishFromMenu:(id)sender;
- (void)editOpenRouterKey:(id)sender;
- (void)setPasteAuto:(id)sender;
- (void)setPasteClipboard:(id)sender;
- (void)setPasteHistory:(id)sender;
- (void)editGroqKey:(id)sender;
- (void)clearGroqKey:(id)sender;
- (void)toggleSkipHealth:(id)sender;
- (void)toggleGroqProxy:(id)sender;
- (void)editGroqProxyURL:(id)sender;
- (void)clearGroqProxy:(id)sender;
- (void)setMaxRecord120:(id)sender;
- (void)setMaxRecord300:(id)sender;
- (void)setMaxRecord600:(id)sender;
- (void)setMaxRecord0:(id)sender;
- (void)openVocab:(id)sender;
- (void)copyHistoryItem:(id)sender;
- (void)openHistoryFile:(id)sender;
- (void)menuStartRecord:(id)sender;
- (void)statusIconClicked:(id)sender;
- (void)menuStopRecord:(id)sender;
- (void)retryLastTake:(id)sender;
- (void)restartHotkey:(id)sender;
- (void)openInputMonitoring:(id)sender;
- (void)openLog:(id)sender;
- (void)openPrefsFolder:(id)sender;
- (void)quit:(id)sender;
@end

static WCAppDelegate *gApp = nil;

static void wcSignalLog(int sig) {
	/* async-signal-safe-ish: best-effort log before death (SIGTERM/SIGINT). SIGKILL cannot be caught. */
	NSString *path = [NSHomeDirectory() stringByAppendingPathComponent:@"Library/Logs/WhisperMacNative.log"];
	NSString *line = [NSString stringWithFormat:@"%@ signal %d — exiting\n", [[NSDate date] description], sig];
	NSFileHandle *fh = [NSFileHandle fileHandleForWritingAtPath:path];
	if (!fh) {
		[[NSFileManager defaultManager] createFileAtPath:path contents:nil attributes:nil];
		fh = [NSFileHandle fileHandleForWritingAtPath:path];
	}
	[fh seekToEndOfFile];
	[fh writeData:[line dataUsingEncoding:NSUTF8StringEncoding]];
	[fh closeFile];
	_exit(128 + sig);
}

static NSData *wcSilentWavData(void) {
	/* 0.25s mono 8 kHz 16-bit PCM silence — enough for AVAudioPlayer loop keep-alive. */
	const uint32_t sampleRate = 8000;
	const uint32_t numSamples = sampleRate / 4;
	const uint32_t dataBytes = numSamples * 2;
	const uint32_t riffSize = 36 + dataBytes;
	NSMutableData *d = [NSMutableData dataWithLength:44 + dataBytes];
	uint8_t *p = d.mutableBytes;
	memcpy(p + 0, "RIFF", 4);
	memcpy(p + 4, &riffSize, 4);
	memcpy(p + 8, "WAVE", 4);
	memcpy(p + 12, "fmt ", 4);
	uint32_t fmtSize = 16;
	uint16_t audioFormat = 1, channels = 1, bits = 16;
	uint32_t byteRate = sampleRate * 2;
	uint16_t blockAlign = 2;
	memcpy(p + 16, &fmtSize, 4);
	memcpy(p + 20, &audioFormat, 2);
	memcpy(p + 22, &channels, 2);
	memcpy(p + 24, &sampleRate, 4);
	memcpy(p + 28, &byteRate, 4);
	memcpy(p + 32, &blockAlign, 2);
	memcpy(p + 34, &bits, 2);
	memcpy(p + 36, "data", 4);
	memcpy(p + 40, &dataBytes, 4);
	memset(p + 44, 0, dataBytes);
	return d;
}

static BOOL wcFnKeycode(int64_t keycode) {
	return keycode == 63 || keycode == 179; /* Fn / Globe */
}

static BOOL wcFnCombo(CGEventFlags flags) {
	BOOL fnDown = (flags & kModFn) != 0;
	BOOL others = (flags & kOtherMods) != 0;
	return fnDown && !others;
}

static void wcHotkeyDown(void) {
	if (!g_hotkeyPressed) {
		g_hotkeyPressed = YES;
		dispatch_async(dispatch_get_main_queue(), ^{ [gApp onHotkeyDown]; });
	}
}

static void wcHotkeyUp(void) {
	if (g_hotkeyPressed) {
		g_hotkeyPressed = NO;
		dispatch_async(dispatch_get_main_queue(), ^{ [gApp onHotkeyUp]; });
	}
}

static CGEventRef wcTapCallback(CGEventTapProxy proxy, CGEventType type, CGEventRef event, void *refcon) {
	(void)proxy;
	(void)refcon;
	if (type == kCGEventTapDisabledByTimeout || type == kCGEventTapDisabledByUserInput) {
		if (g_tap) CGEventTapEnable(g_tap, true);
		return event;
	}
	/*
	 * Globe/Fn шлёт кучу FlagsChanged без смены самого Fn-бита.
	 * Раньше любой FlagsChanged БЕЗ Fn звал hotkeyUp → запись длилась 0.1с.
	 * Стопаемся только когда бит SecondaryFn реально упал.
	 */
	if (type == kCGEventFlagsChanged) {
		BOOL fnBit = (CGEventGetFlags(event) & kModFn) != 0;
		if (fnBit && !g_fnBitDown) {
			if (wcFnCombo(CGEventGetFlags(event))) wcHotkeyDown();
		} else if (!fnBit && g_fnBitDown) {
			wcHotkeyUp();
		}
		g_fnBitDown = fnBit;
		return event;
	}
	if (type == kCGEventKeyDown || type == kCGEventKeyUp) {
		int64_t kc = CGEventGetIntegerValueField(event, kCGKeyboardEventKeycode);
		if (wcFnKeycode(kc)) {
			if (type == kCGEventKeyDown) wcHotkeyDown();
			else wcHotkeyUp();
		}
		return event;
	}
	return event;
}

static void *wcTapThreadMain(void *arg) {
	(void)arg;
	CGEventMask mask = CGEventMaskBit(kCGEventFlagsChanged) | CGEventMaskBit(kCGEventKeyDown) |
	                   CGEventMaskBit(kCGEventKeyUp);
	g_tap = CGEventTapCreate(kCGHIDEventTap, kCGHeadInsertEventTap, kCGEventTapOptionListenOnly, mask, wcTapCallback, NULL);
	if (!g_tap) {
		wcLog(@"CGEventTapCreate failed in tap thread");
		g_tapRunning = 0;
		return NULL;
	}
	CFRunLoopSourceRef src = CFMachPortCreateRunLoopSource(kCFAllocatorDefault, g_tap, 0);
	CFRunLoopAddSource(CFRunLoopGetCurrent(), src, kCFRunLoopCommonModes);
	CGEventTapEnable(g_tap, true);
	CFRelease(src);
	wcLog(@"hotkey tap thread running (Fn/Globe PTT)");
	g_tapLoop = CFRunLoopGetCurrent();
	CFRunLoopRun();
	g_tapLoop = NULL;
	if (g_tap) {
		CGEventTapEnable(g_tap, false);
		CFMachPortInvalidate(g_tap);
		CFRelease(g_tap);
		g_tap = NULL;
	}
	return NULL;
}

void wcLog(NSString *fmt, ...) {
	va_list ap;
	va_start(ap, fmt);
	NSString *msg = [[NSString alloc] initWithFormat:fmt arguments:ap];
	va_end(ap);
	NSString *line = [NSString stringWithFormat:@"%@ %@\n", [[NSDate date] description], msg];
	NSString *path = [NSHomeDirectory() stringByAppendingPathComponent:@"Library/Logs/WhisperMacNative.log"];
	[[NSFileManager defaultManager] createDirectoryAtPath:[path stringByDeletingLastPathComponent]
	                          withIntermediateDirectories:YES attributes:nil error:nil];
	NSFileHandle *fh = [NSFileHandle fileHandleForWritingAtPath:path];
	if (!fh) {
		[[NSFileManager defaultManager] createFileAtPath:path contents:[line dataUsingEncoding:NSUTF8StringEncoding]
		                                        attributes:nil];
	} else {
		[fh seekToEndOfFile];
		[fh writeData:[line dataUsingEncoding:NSUTF8StringEncoding]];
		[fh closeFile];
	}
	fprintf(stderr, "%s", [line UTF8String]);
}

static void wcUncaughtException(NSException *ex) {
	wcLog(@"UNCAUGHT %@ — %@ %@", ex.name, ex.reason, ex.callStackSymbols);
}

static NSString *wcAudioDeviceName(AudioDeviceID dev) {
	AudioObjectPropertyAddress addr = { kAudioObjectPropertyName, kAudioObjectPropertyScopeGlobal,
		                                kAudioObjectPropertyElementMain };
	CFStringRef cf = NULL;
	UInt32 sz = sizeof(cf);
	if (AudioObjectGetPropertyData(dev, &addr, 0, NULL, &sz, &cf) != noErr || !cf) return @"?";
	NSString *s = [(__bridge_transfer NSString *)cf copy];
	return s.length ? s : @"?";
}

static UInt32 wcAudioTransport(AudioDeviceID dev) {
	AudioObjectPropertyAddress addr = { kAudioDevicePropertyTransportType, kAudioObjectPropertyScopeGlobal,
		                                kAudioObjectPropertyElementMain };
	UInt32 t = 0;
	UInt32 sz = sizeof(t);
	AudioObjectGetPropertyData(dev, &addr, 0, NULL, &sz, &t);
	return t;
}

static BOOL wcAudioHasInput(AudioDeviceID dev) {
	AudioObjectPropertyAddress addr = { kAudioDevicePropertyStreamConfiguration, kAudioDevicePropertyScopeInput,
		                                kAudioObjectPropertyElementMain };
	UInt32 sz = 0;
	if (AudioObjectGetPropertyDataSize(dev, &addr, 0, NULL, &sz) != noErr || sz == 0) return NO;
	AudioBufferList *abl = (AudioBufferList *)malloc(sz);
	if (!abl) return NO;
	BOOL ok = AudioObjectGetPropertyData(dev, &addr, 0, NULL, &sz, abl) == noErr;
	UInt32 ch = 0;
	if (ok) {
		for (UInt32 i = 0; i < abl->mNumberBuffers; i++) ch += abl->mBuffers[i].mNumberChannels;
	}
	free(abl);
	return ch > 0;
}

static AudioDeviceID wcDefaultInputDevice(void) {
	AudioObjectPropertyAddress addr = { kAudioHardwarePropertyDefaultInputDevice, kAudioObjectPropertyScopeGlobal,
		                                kAudioObjectPropertyElementMain };
	AudioDeviceID dev = 0;
	UInt32 sz = sizeof(dev);
	AudioObjectGetPropertyData(kAudioObjectSystemObject, &addr, 0, NULL, &sz, &dev);
	return dev;
}

static BOOL wcSetDefaultInputDevice(AudioDeviceID dev) {
	if (!dev) return NO;
	AudioObjectPropertyAddress addr = { kAudioHardwarePropertyDefaultInputDevice, kAudioObjectPropertyScopeGlobal,
		                                kAudioObjectPropertyElementMain };
	OSStatus st = AudioObjectSetPropertyData(kAudioObjectSystemObject, &addr, 0, NULL, sizeof(dev), &dev);
	if (st != noErr) {
		wcLog(@"set default input failed status=%d", (int)st);
		return NO;
	}
	return YES;
}

static const char *wcTransportLabel(UInt32 t) {
	switch (t) {
	case kAudioDeviceTransportTypeBuiltIn: return "builtin";
	case kAudioDeviceTransportTypeBluetooth:
	case kAudioDeviceTransportTypeBluetoothLE: return "bluetooth";
	case kAudioDeviceTransportTypeVirtual: return "virtual";
	case kAudioDeviceTransportTypeUSB: return "usb";
	case kAudioDeviceTransportTypeAggregate: return "aggregate";
	default: return "other";
	}
}

/* BT-гарнитура / BlackHole / Zoom на Mac часто пишут тишину в AVAudioRecorder. Берём встроенный мик. */
static AudioDeviceID wcPreferredDictationInput(NSString **outName) {
	AudioDeviceID current = wcDefaultInputDevice();
	AudioObjectPropertyAddress addr = { kAudioHardwarePropertyDevices, kAudioObjectPropertyScopeGlobal,
		                                kAudioObjectPropertyElementMain };
	UInt32 sz = 0;
	if (AudioObjectGetPropertyDataSize(kAudioObjectSystemObject, &addr, 0, NULL, &sz) != noErr || sz == 0)
		return current;
	AudioDeviceID *devs = (AudioDeviceID *)malloc(sz);
	if (!devs) return current;
	if (AudioObjectGetPropertyData(kAudioObjectSystemObject, &addr, 0, NULL, &sz, devs) != noErr) {
		free(devs);
		return current;
	}
	int n = (int)(sz / sizeof(AudioDeviceID));
	AudioDeviceID builtin = 0, usb = 0;
	NSString *builtinName = nil, *usbName = nil;
	for (int i = 0; i < n; i++) {
		AudioDeviceID d = devs[i];
		if (!wcAudioHasInput(d)) continue;
		NSString *name = wcAudioDeviceName(d);
		UInt32 tr = wcAudioTransport(d);
		NSString *low = name.lowercaseString;
		wcLog(@"audio in '%@' transport=%s id=%u", name, wcTransportLabel(tr), (unsigned)d);
		if ([low containsString:@"blackhole"] || [low containsString:@"zoom"] || [low containsString:@"aggregate"] ||
		    [low containsString:@"многовыход"] || [low containsString:@"агрегат"])
			continue;
		if (tr == kAudioDeviceTransportTypeVirtual) continue;
		if (tr == kAudioDeviceTransportTypeBuiltIn && !builtin) {
			builtin = d;
			builtinName = name;
		} else if (tr == kAudioDeviceTransportTypeUSB && !usb) {
			usb = d;
			usbName = name;
		}
	}
	free(devs);
	AudioDeviceID pick = builtin ? builtin : (usb ? usb : current);
	NSString *nm = builtin ? builtinName : (usb ? usbName : wcAudioDeviceName(current));
	if (outName) *outName = nm;
	return pick;
}

static NSString *wcRealHome(void) {
	struct passwd *pw = getpwuid(getuid());
	return pw && pw->pw_dir ? @(pw->pw_dir) : NSHomeDirectory();
}

static NSString *wcPrefsPath(void) {
	return [NSHomeDirectory() stringByAppendingPathComponent:@".whisper/mac_client_prefs.json"];
}

static NSString *wcLegacyPrefsPath(void) {
	return [wcRealHome() stringByAppendingPathComponent:@".whisper/mac_client_prefs.json"];
}

static NSString *wcHistoryPath(void) {
	return [NSHomeDirectory() stringByAppendingPathComponent:@".whisper/mac_transcription_history.json"];
}

static NSString *wcEnvPath(void) {
	return [NSHomeDirectory() stringByAppendingPathComponent:@"Library/Application Support/WhisperClient/.env"];
}

static NSString *wcMacOSDir(void) {
	return [[[NSBundle mainBundle] bundlePath] stringByAppendingPathComponent:@"Contents/MacOS"];
}

static void wcLoadEnvFile(NSString *path, NSMutableDictionary *into) {
	NSData *data = [NSData dataWithContentsOfFile:path];
	if (!data) return;
	NSString *raw = [[NSString alloc] initWithData:data encoding:NSUTF8StringEncoding];
	for (NSString *line in [raw componentsSeparatedByString:@"\n"]) {
		NSString *s = [line stringByTrimmingCharactersInSet:[NSCharacterSet whitespaceCharacterSet]];
		if (s.length == 0 || [s hasPrefix:@"#"]) continue;
		NSRange eq = [s rangeOfString:@"="];
		if (eq.location == NSNotFound) continue;
		NSString *k = [[s substringToIndex:eq.location] stringByTrimmingCharactersInSet:[NSCharacterSet whitespaceCharacterSet]];
		NSString *v = [[s substringFromIndex:eq.location + 1] stringByTrimmingCharactersInSet:[NSCharacterSet whitespaceCharacterSet]];
		if (v.length >= 2 && [[v substringToIndex:1] isEqual:[v substringFromIndex:v.length - 1]] &&
		    ([v hasPrefix:@"\""] || [v hasPrefix:@"'"])) {
			v = [v substringWithRange:NSMakeRange(1, v.length - 2)];
		}
		if (k.length && v.length) into[k] = v;
	}
}

static NSString *wcStringPref(NSDictionary *prefs, NSString *key) {
	id v = prefs[key];
	return [v isKindOfClass:[NSString class]] ? [(NSString *)v stringByTrimmingCharactersInSet:[NSCharacterSet whitespaceAndNewlineCharacterSet]] : @"";
}

NSString *wcServerURL(NSDictionary *prefs) {
	NSString *su = wcStringPref(prefs, @"server_url");
	if (su.length && ([su hasPrefix:@"http://"] || [su hasPrefix:@"https://"])) {
		if ([su hasSuffix:@"/"]) su = [su substringToIndex:su.length - 1];
		return su;
	}
	NSString *host = wcStringPref(prefs, @"server_host");
	NSInteger port = kDefaultServerPort;
	id sp = prefs[@"server_port"];
	if ([sp respondsToSelector:@selector(integerValue)]) port = [sp integerValue];
	if (host.length) return [NSString stringWithFormat:@"http://%@:%ld", host, (long)port];
	return [NSString stringWithFormat:@"http://%@:%ld", kDefaultServerHost, (long)kDefaultServerPort];
}

NSString *wcBackend(NSDictionary *prefs, NSDictionary *env) {
	NSString *b = wcStringPref(prefs, @"transcribe_backend");
	if (b.length) return b;
	b = env[@"WHISPER_MAC_TRANSCRIBE_BACKEND"] ?: env[@"WHISPER_TRANSCRIBE_BACKEND"];
#if WC_HAS_PARAKEET
	/* Apple Silicon: локальный Parakeet по умолчанию, Groq — запасной. */
	if (!b.length) {
		if ([WCParakeetEngine shared].isSupported) return @"parakeet_then_groq";
	}
#endif
	return b.length ? b : @"server_then_groq";
}

static NSArray<NSString *> *wcBackendOrder(NSString *mode) {
	if ([mode isEqualToString:@"parakeet"]) return @[ @"parakeet" ];
	if ([mode isEqualToString:@"parakeet_then_groq"]) return @[ @"parakeet", @"groq" ];
	if ([mode isEqualToString:@"parakeet_then_server"]) return @[ @"parakeet", @"server" ];
	if ([mode isEqualToString:@"parakeet_then_server_then_groq"]) return @[ @"parakeet", @"server", @"groq" ];
	if ([mode isEqualToString:@"server_then_parakeet"]) return @[ @"server", @"parakeet" ];
	if ([mode isEqualToString:@"groq_then_parakeet"]) return @[ @"groq", @"parakeet" ];
	if ([mode isEqualToString:@"groq"]) return @[ @"groq" ];
	if ([mode isEqualToString:@"server"]) return @[ @"server" ];
	if ([mode isEqualToString:@"groq_then_server"]) return @[ @"groq", @"server" ];
	if ([mode isEqualToString:@"server_then_groq"]) return @[ @"server", @"groq" ];
	return @[ @"server", @"groq" ];
}

NSArray<NSDictionary *> *wcBackendChoices(void) {
	return @[
		@{ @"id" : @"parakeet", @"title" : @"Parakeet (локально)" },
		@{ @"id" : @"server", @"title" : @"Мой сервер (ПК)" },
		@{ @"id" : @"groq", @"title" : @"Groq (облако)" },
		@{ @"id" : @"—", @"title" : @"—" },
		@{ @"id" : @"parakeet_then_server", @"title" : @"Parakeet → сервер" },
		@{ @"id" : @"parakeet_then_groq", @"title" : @"Parakeet → Groq" },
		@{ @"id" : @"parakeet_then_server_then_groq", @"title" : @"Parakeet → сервер → Groq" },
		@{ @"id" : @"server_then_groq", @"title" : @"Сервер → Groq" },
		@{ @"id" : @"server_then_parakeet", @"title" : @"Сервер → Parakeet" },
		@{ @"id" : @"groq_then_server", @"title" : @"Groq → сервер" },
		@{ @"id" : @"groq_then_parakeet", @"title" : @"Groq → Parakeet" },
	];
}

NSString *wcParakeetLanguage(NSDictionary *prefs, NSDictionary *env) {
	NSString *l = wcStringPref(prefs, @"parakeet_language");
	if (l.length) return l;
	l = env[@"WHISPER_PARAKEET_LANGUAGE"] ?: env[@"WHISPER_LANGUAGE"];
	return l.length ? l : @"ru";
}

static NSString *wcGroqKey(NSDictionary *prefs, NSDictionary *env) {
	NSString *k = env[@"GROQ_API_KEY"] ?: env[@"WHISPER_GROQ_API_KEY"];
	if (k.length) return k;
	return wcStringPref(prefs, @"groq_api_key");
}

NSString *wcGroqProxyURL(NSDictionary *prefs, NSDictionary *env) {
	NSString *p = wcStringPref(prefs, @"groq_proxy_url");
	if (p.length) return [p stringByTrimmingCharactersInSet:[NSCharacterSet characterSetWithCharactersInString:@"/"]];
	p = env[@"WHISPER_GROQ_PROXY_URL"] ?: @"";
	if (p.length) return [p stringByTrimmingCharactersInSet:[NSCharacterSet characterSetWithCharactersInString:@"/"]];
	return kDefaultGroqProxyURL;
}

BOOL wcGroqProxyEnabled(NSDictionary *prefs, NSDictionary *env) {
	id v = prefs[@"groq_proxy_enabled"];
	if ([v isKindOfClass:[NSNumber class]]) return [v boolValue];
	NSString *e = env[@"WHISPER_GROQ_PROXY_ENABLED"] ?: env[@"GROQ_PROXY_ENABLED"];
	if ([e isKindOfClass:[NSString class]] && e.length) {
		NSString *l = e.lowercaseString;
		if ([l isEqualToString:@"0"] || [l isEqualToString:@"false"] || [l isEqualToString:@"no"] ||
		    [l isEqualToString:@"off"])
			return NO;
		return YES;
	}
	/* По умолчанию ON: из РФ прямой api.groq.com / Railway часто таймаутится. */
	return YES;
}

static NSString *wcGroqProxySecret(NSDictionary *prefs, NSDictionary *env) {
	NSString *s = wcStringPref(prefs, @"groq_proxy_secret");
	if (s.length) return s;
	return env[@"WHISPER_GROQ_PROXY_SECRET"] ?: env[@"PROXY_SHARED_SECRET"] ?: @"";
}

static NSString *wcLastTakePath(void) {
	return [NSHomeDirectory()
	    stringByAppendingPathComponent:@"Library/Application Support/WhisperClient/last_take.wav"];
}

static BOOL wcHasLastTake(void) {
	NSDictionary *attrs = [[NSFileManager defaultManager] attributesOfItemAtPath:wcLastTakePath() error:nil];
	return attrs.fileSize >= 800;
}

NSString *wcPasteMode(NSDictionary *prefs) {
	NSString *m = wcStringPref(prefs, @"paste_mode");
	if ([m isEqualToString:@"clipboard"] || [m isEqualToString:@"history_only"]) return m;
	return @"auto";
}

NSString *wcBackendLabel(NSString *mode) {
	for (NSDictionary *c in wcBackendChoices()) {
		if ([c[@"id"] isEqualToString:mode]) return c[@"title"];
	}
	NSDictionary *legacy = @{
		@"server" : @"Мой сервер (ПК)",
		@"groq" : @"Groq (облако)",
	};
	return legacy[mode] ?: mode;
}

static NSString *wcPasteLabel(NSString *mode) {
	NSDictionary *m = @{ @"auto" : @"В поле + буфер", @"clipboard" : @"Только буфер", @"history_only" : @"Только история" };
	return m[mode] ?: mode;
}

/* Hard cap: unlimited prefs used to leave main thread stuck on huge afconvert. */
static const double kWCHardMaxRecordSec = 600.0;
static const double kWCDefaultMaxRecordSec = 300.0;
/* Случайный тап Globe/Fn — не слать в ASR (иначе Whisper вставляет галлюцинации). */
static const double kWCMinRecordSec = 0.5;
/* 16 kHz mono s16le: 0.5 с ≈ 16000 сэмплов × 2 + WAV header. */
static const NSUInteger kWCMinRecordBytes = (NSUInteger)(16000 * 2 * 0.5) + 44;

static double wcMaxRecordSeconds(NSDictionary *prefs) {
	id v = prefs[@"max_record_seconds"];
	double sec = 0;
	if ([v respondsToSelector:@selector(doubleValue)]) sec = [v doubleValue];
	if (sec <= 0) sec = kWCDefaultMaxRecordSec;
	if (sec > kWCHardMaxRecordSec) sec = kWCHardMaxRecordSec;
	return sec;
}

static BOOL wcSkipHealth(NSDictionary *prefs) {
	id v = prefs[@"skip_health_check"];
	return [v isKindOfClass:[NSNumber class]] ? [v boolValue] : NO;
}

static NSString *wcPromptLine(NSString *title, NSString *message, NSString *defaultValue) {
	[NSApp activateIgnoringOtherApps:YES];
	NSAlert *alert = [[NSAlert alloc] init];
	alert.messageText = title;
	alert.informativeText = message;
	NSTextField *field = [[NSTextField alloc] initWithFrame:NSMakeRect(0, 0, 360, 24)];
	field.stringValue = defaultValue ?: @"";
	alert.accessoryView = field;
	[alert addButtonWithTitle:@"Сохранить"];
	[alert addButtonWithTitle:@"Отмена"];
	if ([alert runModal] != NSAlertFirstButtonReturn) return nil;
	return [field.stringValue stringByTrimmingCharactersInSet:[NSCharacterSet whitespaceAndNewlineCharacterSet]];
}

static void wcOpenURL(NSString *urlStr) {
	[[NSWorkspace sharedWorkspace] openURL:[NSURL URLWithString:urlStr]];
}

static void wcOpenPath(NSString *path) {
	if (!path.length) return;
	[[NSWorkspace sharedWorkspace] openURL:[NSURL fileURLWithPath:path]];
}

static void wcOsascriptBanner(NSString *title, NSString *body) {
	/* MAS sandbox: NSTask→osascript часто = deny + kill процесса. Не вызываем. */
	(void)title;
	(void)body;
}

static NSString *wcCheckMark(BOOL on) {
	return on ? @"✓ " : @"   ";
}

@implementation WCAppDelegate

- (void)reloadPrefs {
	NSString *path = wcPrefsPath();
	NSData *data = [NSData dataWithContentsOfFile:path];
	if (!data.length) data = [NSData dataWithContentsOfFile:wcLegacyPrefsPath()];
	id obj = data ? [NSJSONSerialization JSONObjectWithData:data options:0 error:nil] : nil;
	self.prefs = [obj isKindOfClass:[NSDictionary class]] ? [obj mutableCopy] : [NSMutableDictionary dictionary];
	/* Migrations: Layero edge 503 на больших POST → Railway origin. */
	BOOL changed = NO;
	NSString *purl = wcStringPref(self.prefs, @"groq_proxy_url");
	if (purl.length) {
		NSString *l = purl.lowercaseString;
		if ([l containsString:@"anyquery-whisper-groq-proxy"] || [l containsString:@"preview.layero.ru"] ||
		    [l containsString:@"whisper-groq-proxy.layero.app"]) {
			self.prefs[@"groq_proxy_url"] = kDefaultGroqProxyURL;
			changed = YES;
			wcLog(@"migrated groq_proxy_url → %@", kDefaultGroqProxyURL);
		}
	}
	if (!self.prefs[@"groq_proxy_migrated_b53"]) {
		self.prefs[@"groq_proxy_enabled"] = @YES;
		self.prefs[@"groq_proxy_migrated_b53"] = @YES;
		changed = YES;
	}
	if (!self.prefs[@"groq_proxy_migrated_b54"]) {
		self.prefs[@"groq_proxy_enabled"] = @YES;
		self.prefs[@"groq_proxy_url"] = kDefaultGroqProxyURL;
		self.prefs[@"groq_proxy_migrated_b54"] = @YES;
		changed = YES;
		wcLog(@"migrated b54 groq proxy → %@", kDefaultGroqProxyURL);
	}
#if WC_HAS_PARAKEET
	/* b55: один раз переключить cloud-only дефолт на Parakeet → Groq (если юзер сам не менял). */
	if (!self.prefs[@"parakeet_migrated_b55"] && [WCParakeetEngine shared].isSupported) {
		NSString *bk = self.prefs[@"transcribe_backend"];
		BOOL untouched = ![bk isKindOfClass:[NSString class]] || !bk.length ||
		                 [bk isEqualToString:@"server_then_groq"] || [bk isEqualToString:@"groq_then_server"];
		if (untouched) {
			self.prefs[@"transcribe_backend"] = @"parakeet_then_groq";
			changed = YES;
			wcLog(@"migrated b55 backend → parakeet_then_groq");
		}
		if (![self.prefs[@"parakeet_language"] isKindOfClass:[NSString class]] ||
		    ![self.prefs[@"parakeet_language"] length]) {
			self.prefs[@"parakeet_language"] = @"ru";
			changed = YES;
		}
		self.prefs[@"parakeet_migrated_b55"] = @YES;
		changed = YES;
	}
#endif
	if (changed) [self savePrefs];
}

- (void)savePrefs {
	NSString *dir = [wcPrefsPath() stringByDeletingLastPathComponent];
	[[NSFileManager defaultManager] createDirectoryAtPath:dir withIntermediateDirectories:YES attributes:nil error:nil];
	NSData *data = [NSJSONSerialization dataWithJSONObject:self.prefs options:NSJSONWritingPrettyPrinted error:nil];
	if (!data) return;
	[data writeToFile:wcPrefsPath() atomically:YES];
	/* Дубль в реальный ~/.whisper — совместимость с Python-клиентом */
	NSString *legacyDir = [wcLegacyPrefsPath() stringByDeletingLastPathComponent];
	[[NSFileManager defaultManager] createDirectoryAtPath:legacyDir withIntermediateDirectories:YES attributes:nil error:nil];
	[data writeToFile:wcLegacyPrefsPath() atomically:YES];
	wcLog(@"prefs saved backend=%@ paste=%@", self.prefs[@"transcribe_backend"], self.prefs[@"paste_mode"]);
}

- (void)userNotify:(NSString *)title body:(NSString *)body {
	wcLog(@"notify: %@ — %@", title, body);
	/* Не трогаем osascript в sandbox — это роняло клиент после «готово». */
	if (@available(macOS 10.14, *)) {
		static BOOL sNotifyDenied;
		if (sNotifyDenied) return;
		UNMutableNotificationContent *c = [[UNMutableNotificationContent alloc] init];
		c.title = title ?: @"Whisper";
		c.body = body ?: @"";
		UNNotificationRequest *req = [UNNotificationRequest requestWithIdentifier:[[NSUUID UUID] UUIDString]
		                                                                    content:c
		                                                                    trigger:nil];
		[[UNUserNotificationCenter currentNotificationCenter]
		    addNotificationRequest:req
		     withCompletionHandler:^(NSError *err) {
			     if (!err) return;
			     /* Code 1 = notifications not allowed — не спамим addNotificationRequest. */
			     if ([err.domain isEqualToString:UNErrorDomain] && err.code == 1) sNotifyDenied = YES;
			     else wcLog(@"UN notify err: %@", err);
		     }];
	}
}

- (void)finishProcessingAfterDelay:(NSTimeInterval)sec {
	dispatch_after(dispatch_time(DISPATCH_TIME_NOW, (int64_t)(sec * NSEC_PER_SEC)), dispatch_get_main_queue(), ^{
		self.processing = NO;
		[self ensureStatusItem];
		if (!self.recording) self.statusItem.button.title = @"🎤";
		[self rebuildMenu];
		[self startSilentKeepAlive];
	});
}

- (void)notify:(NSString *)title body:(NSString *)body {
	[self userNotify:title body:body];
}

- (NSDictionary *)loadEnv {
	NSMutableDictionary *env = [NSMutableDictionary dictionary];
	NSString *res = [[[NSBundle mainBundle] bundlePath] stringByAppendingPathComponent:@"Contents/Resources/.env"];
	wcLoadEnvFile(res, env);
	wcLoadEnvFile(wcEnvPath(), env);
	NSString *legacy = [wcRealHome() stringByAppendingPathComponent:@"Library/Application Support/WhisperClient/.env"];
	wcLoadEnvFile(legacy, env);
	return env;
}

- (NSMenuItem *)item:(NSString *)title action:(SEL)sel key:(NSString *)key {
	NSMenuItem *it = [[NSMenuItem alloc] initWithTitle:title action:sel keyEquivalent:key ?: @""];
	it.target = self;
	return it;
}

- (NSMenuItem *)disabled:(NSString *)title {
	NSMenuItem *it = [[NSMenuItem alloc] initWithTitle:title action:NULL keyEquivalent:@""];
	it.enabled = NO;
	return it;
}

- (void)rebuildMenu {
	/* Replacing statusItem.menu while open kills clicks — defer until close. */
	if (self.menuIsOpen) {
		self.menuNeedsRebuild = YES;
		return;
	}
	self.menuNeedsRebuild = NO;
	NSMenu *menu = [[NSMenu alloc] init];
	menu.delegate = self;
	menu.autoenablesItems = NO;
	NSString *url = wcServerURL(self.prefs);
	NSString *curBackend = wcBackend(self.prefs, self.env);
	NSString *curPaste = wcPasteMode(self.prefs);
	NSString *hk = AXIsProcessTrusted() ? @"Fn OK (удерживай для записи)" : @"Fn — нет Input Monitoring";
	[menu addItem:[self disabled:[NSString stringWithFormat:@"Версия %@ (%@)", self.appVersion ?: @"?",
	                                                        [[NSBundle mainBundle] objectForInfoDictionaryKey:@"CFBundleVersion"] ?: @"?"]]];
	[menu addItem:[self disabled:@"Левый клик 🎤 — старт/стоп записи"]];
	[menu addItem:[self disabled:[NSString stringWithFormat:@"Сервер: %@", url]]];
#if WC_HAS_PARAKEET
	if ([WCParakeetEngine shared].isSupported) {
		NSString *pk = [WCParakeetEngine shared].isReady ? @"Parakeet: готов (offline)" : @"Parakeet: загрузка модели…";
		[menu addItem:[self disabled:pk]];
	}
#endif
	[menu addItem:[self disabled:[NSString stringWithFormat:@"Текст: %@", wcPasteLabel(curPaste)]]];
	[menu addItem:[self disabled:hk]];
	if (self.processing) [menu addItem:[self disabled:@"⏳ Обработка записи…"]];
	[menu addItem:[NSMenuItem separatorItem]];

	/* Быстрое переключение Parakeet / сервер ПК / Groq */
	NSMenuItem *bkRoot = [self item:[NSString stringWithFormat:@"Транскрипция: %@", wcBackendLabel(curBackend)]
	                          action:NULL
	                             key:@""];
	NSMenu *bkM = [[NSMenu alloc] init];
	bkM.autoenablesItems = NO;
	for (NSDictionary *c in wcBackendChoices()) {
		NSString *cid = c[@"id"];
		if ([cid isEqualToString:@"—"]) {
			[bkM addItem:[NSMenuItem separatorItem]];
			continue;
		}
#if !WC_HAS_PARAKEET
		if ([cid containsString:@"parakeet"]) continue;
#endif
		NSMenuItem *bi = [self item:c[@"title"] action:@selector(setBackendFromMenu:) key:@""];
		bi.representedObject = cid;
		bi.state = [cid isEqualToString:curBackend] ? NSControlStateValueOn : NSControlStateValueOff;
		[bkM addItem:bi];
	}
	bkRoot.submenu = bkM;
	[menu addItem:bkRoot];

	NSString *curPolish = wcPolishMode(self.prefs, self.env);
	NSMenuItem *plRoot = [self item:[NSString stringWithFormat:@"После текста: %@", wcPolishLabel(curPolish)]
	                          action:NULL
	                             key:@""];
	NSMenu *plM = [[NSMenu alloc] init];
	plM.autoenablesItems = NO;
	for (NSDictionary *c in wcPolishChoices()) {
		NSString *cid = c[@"id"];
		if ([cid isEqualToString:@"—"]) {
			[plM addItem:[NSMenuItem separatorItem]];
			continue;
		}
		NSMenuItem *pi = [self item:c[@"title"] action:@selector(setPolishFromMenu:) key:@""];
		pi.representedObject = cid;
		pi.state = [cid isEqualToString:curPolish] ? NSControlStateValueOn : NSControlStateValueOff;
		[plM addItem:pi];
	}
	[plM addItem:[NSMenuItem separatorItem]];
	[plM addItem:[self item:@"Ключ OpenRouter…" action:@selector(editOpenRouterKey:) key:@""]];
	plRoot.submenu = plM;
	[menu addItem:plRoot];

	[menu addItem:[self item:@"⚙️ Настройки…" action:@selector(openSettings:) key:@","]];

	NSMenuItem *hist = [self item:@"История расшифровок" action:NULL key:@""];
	NSMenu *histM = [[NSMenu alloc] init];
	NSArray *entries = [self loadHistory:12];
	if (entries.count == 0) {
		[histM addItem:[self disabled:@"(пусто)"]];
	} else {
		for (NSDictionary *e in entries) {
			NSString *t = e[@"text"];
			if (![t isKindOfClass:[NSString class]] || !t.length) continue;
			NSString *preview = t.length > 48 ? [[t substringToIndex:48] stringByAppendingString:@"…"] : t;
			NSMenuItem *hi = [self item:preview action:@selector(copyHistoryItem:) key:@""];
			hi.representedObject = t;
			[histM addItem:hi];
		}
	}
	[histM addItem:[NSMenuItem separatorItem]];
	[histM addItem:[self item:@"Открыть файл истории…" action:@selector(openHistoryFile:) key:@""]];
	hist.submenu = histM;
	[menu addItem:hist];

	[menu addItem:[NSMenuItem separatorItem]];
	if (self.menuRecording) {
		[menu addItem:[self item:@"⏹ Остановить запись" action:@selector(menuStopRecord:) key:@""]];
	} else if (self.processing) {
		[menu addItem:[self disabled:@"🎤 Запись занята…"]];
	} else {
		[menu addItem:[self item:@"🎤 Записать сейчас" action:@selector(menuStartRecord:) key:@""]];
	}
	if (wcHasLastTake() && !self.processing && !self.menuRecording) {
		NSUInteger sz = [[[NSFileManager defaultManager] attributesOfItemAtPath:wcLastTakePath() error:nil] fileSize];
		NSString *title = [NSString stringWithFormat:@"🔁 Повторить расшифровку (%.0f KB)", sz / 1024.0];
		[menu addItem:[self item:title action:@selector(retryLastTake:) key:@"r"]];
	}
	BOOL proxyOn = wcGroqProxyEnabled(self.prefs, self.env);
	NSString *proxyURL = wcGroqProxyURL(self.prefs, self.env);
	[menu addItem:[self disabled:[NSString stringWithFormat:@"Прокси: %@%@", proxyOn ? @"ON · " : @"OFF",
	                                                        proxyOn ? proxyURL : @""]]];
	[menu addItem:[self item:(proxyOn ? @"Выключить Groq-прокси" : @"Включить Groq-прокси (Layero)")
	                   action:@selector(toggleGroqProxy:)
	                      key:@""]];
	[menu addItem:[self item:@"URL Groq-прокси…" action:@selector(editGroqProxyURL:) key:@""]];
	[menu addItem:[NSMenuItem separatorItem]];
	[menu addItem:[self item:@"Перезапустить перехват клавиш" action:@selector(restartHotkey:) key:@""]];
	[menu addItem:[self item:@"Открыть Input Monitoring…" action:@selector(openInputMonitoring:) key:@""]];
	[menu addItem:[self item:@"Показать лог…" action:@selector(openLog:) key:@""]];
	[menu addItem:[NSMenuItem separatorItem]];
	[menu addItem:[self item:@"Выход" action:@selector(quit:) key:@"q"]];
	self.statusMenu = menu;
	self.statusItem.menu = nil; /* иначе левый клик только открывает меню и запись не стартует */
	[self wireStatusItemClicks];
}

- (void)wireStatusItemClicks {
	NSStatusBarButton *b = self.statusItem.button;
	if (!b) return;
	b.target = self;
	b.action = @selector(statusIconClicked:);
	[b sendActionOn:(NSEventMaskLeftMouseUp | NSEventMaskRightMouseUp)];
	b.toolTip = @"Whisper: левый клик — запись, правый — меню. Fn/Globe удерживать.";
}

- (void)statusIconClicked:(id)sender {
	(void)sender;
	NSEvent *e = [NSApp currentEvent];
	BOOL right = e && (e.type == NSEventTypeRightMouseUp || e.type == NSEventTypeRightMouseDown ||
	                   (e.modifierFlags & NSEventModifierFlagControl) != 0);
	if (right) {
		if (self.statusMenu)
			[self.statusMenu popUpMenuPositioningItem:nil atLocation:NSZeroPoint inView:self.statusItem.button];
		return;
	}
	[self toggleLatchRecord];
}

- (void)toggleLatchRecord {
	if (self.processing && !self.recording) {
		wcLog(@"latch click while processing — reset stuck flag");
		self.processing = NO;
	}
	if (self.recording) {
		wcLog(@"latch stop");
		self.latchRecording = NO;
		g_hotkeyPressed = NO;
		[self onHotkeyUp];
		return;
	}
	wcLog(@"latch start");
	self.latchRecording = YES;
	[self onHotkeyDown];
}

- (void)openSettings:(id)sender {
	(void)sender;
	WCShowSettingsPanel(self);
}

- (NSArray *)loadHistory:(NSInteger)limit {
	NSData *data = [NSData dataWithContentsOfFile:wcHistoryPath()];
	if (!data) return @[];
	id obj = [NSJSONSerialization JSONObjectWithData:data options:0 error:nil];
	if (![obj isKindOfClass:[NSArray class]]) return @[];
	NSArray *arr = (NSArray *)obj;
	if ((NSInteger)arr.count <= limit) return arr;
	return [arr subarrayWithRange:NSMakeRange(0, (NSUInteger)limit)];
}

- (void)appendHistory:(NSString *)text {
	if (!text.length) return;
	NSMutableArray *arr = [[self loadHistory:500] mutableCopy];
	[arr insertObject:@{ @"text" : text, @"ts" : @([[NSDate date] timeIntervalSince1970]) } atIndex:0];
	if (arr.count > 200) [arr removeObjectsInRange:NSMakeRange(200, arr.count - 200)];
	NSString *dir = [wcHistoryPath() stringByDeletingLastPathComponent];
	[[NSFileManager defaultManager] createDirectoryAtPath:dir withIntermediateDirectories:YES attributes:nil error:nil];
	NSData *data = [NSJSONSerialization dataWithJSONObject:arr options:NSJSONWritingPrettyPrinted error:nil];
	if (data) [data writeToFile:wcHistoryPath() atomically:YES];
}

- (void)editHostPort:(id)sender {
	(void)sender;
	NSString *host = wcStringPref(self.prefs, @"server_host");
	if (!host.length) host = kDefaultServerHost;
	NSInteger port = kDefaultServerPort;
	id sp = self.prefs[@"server_port"];
	if ([sp respondsToSelector:@selector(integerValue)]) port = [sp integerValue];
	NSString *h = wcPromptLine(@"Сервер", @"IP или hostname:", host);
	if (!h) return;
	NSString *p = wcPromptLine(@"Сервер", @"Порт:", [NSString stringWithFormat:@"%ld", (long)port]);
	if (!p) return;
	self.prefs[@"server_host"] = h;
	self.prefs[@"server_port"] = @([p integerValue]);
	[self.prefs removeObjectForKey:@"server_url"];
	[self savePrefs];
	self.env = [self loadEnv];
	[self rebuildMenu];
	[self notify:@"Whisper" body:@"Сервер сохранён."];
}

- (void)editServerURL:(id)sender {
	(void)sender;
	NSString *cur = wcStringPref(self.prefs, @"server_url");
	NSString *v = wcPromptLine(@"URL сервера", @"http://host:port без слэша в конце:", cur);
	if (!v) return;
	self.prefs[@"server_url"] = v;
	[self savePrefs];
	self.env = [self loadEnv];
	[self rebuildMenu];
}

- (void)clearServer:(id)sender {
	(void)sender;
	[self.prefs removeObjectsForKeys:@[ @"server_url", @"server_host", @"server_port" ]];
	[self savePrefs];
	self.env = [self loadEnv];
	[self rebuildMenu];
}

- (void)pingServer:(id)sender {
	(void)sender;
	[self userNotify:@"Whisper" body:@"Проверяю связь с сервером…"];
	dispatch_async(dispatch_get_global_queue(QOS_CLASS_USER_INITIATED, 0), ^{
		NSString *base = wcServerURL(self.prefs);
		NSString *url = [NSString stringWithFormat:@"%@/", base];
		NSInteger code = -1;
		NSError *netErr = nil;
		NSData *body = nil;
		wcHttpRequest(@"GET", url, nil, nil, 15, &code, &body, &netErr);
		(void)body;
		dispatch_async(dispatch_get_main_queue(), ^{
			if (code >= 200 && code < 500) {
				[self userNotify:@"Whisper — сервер OK" body:[NSString stringWithFormat:@"%@ отвечает (HTTP %ld).", base, (long)code]];
			} else if (netErr) {
				[self userNotify:@"Whisper — ошибка" body:[NSString stringWithFormat:@"%@: %@", base, netErr.localizedDescription]];
			} else {
				[self userNotify:@"Whisper — ошибка" body:[NSString stringWithFormat:@"%@: нет ответа (код %ld).", base, (long)code]];
			}
		});
	});
}

- (void)setBackend:(NSString *)mode {
	if (![mode isKindOfClass:[NSString class]] || !mode.length) return;
	self.prefs[@"transcribe_backend"] = mode;
	[self savePrefs];
	[self rebuildMenu];
	[self userNotify:@"Whisper" body:[NSString stringWithFormat:@"Транскрипция: %@", wcBackendLabel(mode)]];
#if WC_HAS_PARAKEET
	if ([mode containsString:@"parakeet"] && [WCParakeetEngine shared].isSupported &&
	    ![WCParakeetEngine shared].isReady) {
		dispatch_async(dispatch_get_global_queue(QOS_CLASS_UTILITY, 0), ^{
			NSError *err = nil;
			BOOL ok = [[WCParakeetEngine shared] ensureLoadedWithError:&err];
			wcLog(@"parakeet on-demand load %@", ok ? @"ready" : (err.localizedDescription ?: @"fail"));
			dispatch_async(dispatch_get_main_queue(), ^{ [self rebuildMenu]; });
		});
	}
#endif
}

- (void)setBackendFromMenu:(id)sender {
	NSMenuItem *it = [sender isKindOfClass:[NSMenuItem class]] ? (NSMenuItem *)sender : nil;
	NSString *mode = [it.representedObject isKindOfClass:[NSString class]] ? it.representedObject : nil;
	if (mode.length) [self setBackend:mode];
}

- (void)setPolishFromMenu:(id)sender {
	NSMenuItem *it = [sender isKindOfClass:[NSMenuItem class]] ? (NSMenuItem *)sender : nil;
	NSString *mode = [it.representedObject isKindOfClass:[NSString class]] ? it.representedObject : nil;
	if (!mode.length) return;
	self.prefs[@"polish_mode"] = mode;
	[self savePrefs];
	[self rebuildMenu];
	if (![mode isEqualToString:@"off"] && !wcOpenRouterKey(self.prefs, self.env).length) {
		[self userNotify:@"Whisper" body:@"Режим включён, но нет ключа OpenRouter (sk-or-…). Открой Настройки."];
		return;
	}
	[self userNotify:@"Whisper" body:[NSString stringWithFormat:@"После текста: %@", wcPolishLabel(mode)]];
}

- (void)editOpenRouterKey:(id)sender {
	(void)sender;
	NSString *v = wcPromptLine(@"OpenRouter", @"Ключ sk-or-… (пусто — очистить):", wcStringPref(self.prefs, @"openrouter_api_key"));
	if (v == nil) return;
	if (v.length) self.prefs[@"openrouter_api_key"] = v;
	else [self.prefs removeObjectForKey:@"openrouter_api_key"];
	[self savePrefs];
	[self rebuildMenu];
	[self userNotify:@"Whisper" body:v.length ? @"Ключ OpenRouter сохранён." : @"Ключ OpenRouter очищен."];
}

- (void)setBackendServer:(id)s { (void)s; [self setBackend:@"server"]; }
- (void)setBackendGroq:(id)s { (void)s; [self setBackend:@"groq"]; }
- (void)setBackendServerGroq:(id)s { (void)s; [self setBackend:@"server_then_groq"]; }
- (void)setBackendGroqServer:(id)s { (void)s; [self setBackend:@"groq_then_server"]; }
- (void)setBackendParakeet:(id)s { (void)s; [self setBackend:@"parakeet"]; }
- (void)setBackendParakeetGroq:(id)s { (void)s; [self setBackend:@"parakeet_then_groq"]; }

- (void)setPaste:(NSString *)mode {
	self.prefs[@"paste_mode"] = mode;
	[self savePrefs];
	[self rebuildMenu];
	[self userNotify:@"Whisper" body:[NSString stringWithFormat:@"Режим текста: %@", wcPasteLabel(mode)]];
}

- (void)setPasteAuto:(id)s { (void)s; [self setPaste:@"auto"]; }
- (void)setPasteClipboard:(id)s { (void)s; [self setPaste:@"clipboard"]; }
- (void)setPasteHistory:(id)s { (void)s; [self setPaste:@"history_only"]; }

- (void)editGroqKey:(id)sender {
	(void)sender;
	NSString *v = wcPromptLine(@"Groq API", @"Ключ gsk_… (пусто — очистить):", wcStringPref(self.prefs, @"groq_api_key"));
	if (v == nil) return;
	if (v.length) self.prefs[@"groq_api_key"] = v;
	else [self.prefs removeObjectForKey:@"groq_api_key"];
	[self savePrefs];
	[self rebuildMenu];
}

- (void)clearGroqKey:(id)sender {
	(void)sender;
	[self.prefs removeObjectForKey:@"groq_api_key"];
	[self savePrefs];
	[self rebuildMenu];
}

- (void)toggleSkipHealth:(id)sender {
	(void)sender;
	BOOL cur = wcSkipHealth(self.prefs);
	self.prefs[@"skip_health_check"] = @(!cur);
	[self savePrefs];
	[self rebuildMenu];
}

- (void)toggleGroqProxy:(id)sender {
	(void)sender;
	BOOL cur = wcGroqProxyEnabled(self.prefs, self.env);
	self.prefs[@"groq_proxy_enabled"] = @(!cur);
	[self savePrefs];
	self.env = [self loadEnv];
	[self rebuildMenu];
	[self userNotify:@"Whisper" body:!cur ? @"Groq-прокси (Layero) включён." : @"Groq-прокси выключен — прямой api.groq.com."];
}

- (void)editGroqProxyURL:(id)sender {
	(void)sender;
	NSString *cur = wcStringPref(self.prefs, @"groq_proxy_url");
	if (!cur.length) cur = wcGroqProxyURL(self.prefs, self.env);
	NSString *v = wcPromptLine(@"Groq прокси", @"Базовый URL без / в конце (Layero / Railway):", cur);
	if (v == nil) return;
	if (v.length) self.prefs[@"groq_proxy_url"] = v;
	else [self.prefs removeObjectForKey:@"groq_proxy_url"];
	self.prefs[@"groq_proxy_enabled"] = @YES;
	[self savePrefs];
	self.env = [self loadEnv];
	[self rebuildMenu];
}

- (void)clearGroqProxy:(id)sender {
	(void)sender;
	[self.prefs removeObjectsForKeys:@[ @"groq_proxy_url", @"groq_proxy_secret", @"groq_proxy_enabled" ]];
	[self savePrefs];
	self.env = [self loadEnv];
	[self rebuildMenu];
}

- (void)setMaxRecord:(double)sec {
	if (sec > 0) self.prefs[@"max_record_seconds"] = @(sec);
	else [self.prefs removeObjectForKey:@"max_record_seconds"];
	[self savePrefs];
	[self rebuildMenu];
}

- (void)setMaxRecord120:(id)s { (void)s; [self setMaxRecord:120]; }
- (void)setMaxRecord300:(id)s { (void)s; [self setMaxRecord:300]; }
- (void)setMaxRecord600:(id)s { (void)s; [self setMaxRecord:600]; }
- (void)setMaxRecord0:(id)s { (void)s; [self setMaxRecord:0]; }

- (void)openVocab:(id)sender {
	(void)sender;
	NSString *p = [NSHomeDirectory() stringByAppendingPathComponent:@".whisper/vocab.json"];
	NSString *legacy = [wcRealHome() stringByAppendingPathComponent:@".whisper/vocab.json"];
	if (![[NSFileManager defaultManager] fileExistsAtPath:p] && [[NSFileManager defaultManager] fileExistsAtPath:legacy])
		p = legacy;
	if (![[NSFileManager defaultManager] fileExistsAtPath:p]) {
		[[NSFileManager defaultManager] createDirectoryAtPath:[p stringByDeletingLastPathComponent]
		                          withIntermediateDirectories:YES attributes:nil error:nil];
		[@"{}" writeToFile:p atomically:YES encoding:NSUTF8StringEncoding error:nil];
	}
	[[NSWorkspace sharedWorkspace] openURL:[NSURL fileURLWithPath:p]];
}

- (void)copyHistoryItem:(id)sender {
	NSString *t = [(NSMenuItem *)sender representedObject];
	if (![t isKindOfClass:[NSString class]]) return;
	[[NSPasteboard generalPasteboard] clearContents];
	[[NSPasteboard generalPasteboard] setString:t forType:NSPasteboardTypeString];
	[self notify:@"Whisper" body:@"Скопировано в буфер."];
}

- (void)openHistoryFile:(id)sender {
	(void)sender;
	NSString *p = wcHistoryPath();
	if (![[NSFileManager defaultManager] fileExistsAtPath:p]) {
		NSAlert *a = [[NSAlert alloc] init];
		a.messageText = @"История пуста";
		[a runModal];
		return;
	}
	wcOpenPath(p);
}

- (void)menuStartRecord:(id)sender {
	(void)sender;
	self.menuRecording = YES;
	self.latchRecording = YES;
	[self rebuildMenu];
	[self onHotkeyDown];
}

- (void)menuStopRecord:(id)sender {
	(void)sender;
	self.menuRecording = NO;
	self.latchRecording = NO;
	g_hotkeyPressed = NO;
	[self rebuildMenu];
	[self onHotkeyUp];
}

- (void)preserveTakeForRetry:(NSString *)wavPath {
	if (!wavPath.length) return;
	NSString *dst = wcLastTakePath();
	if ([wavPath isEqualToString:dst]) return;
	NSFileManager *fm = [NSFileManager defaultManager];
	NSDictionary *attrs = [fm attributesOfItemAtPath:wavPath error:nil];
	unsigned long long bytes = attrs.fileSize;
	/* Не затираем хороший last_take случайным тапом Globe (< 0.5 с). */
	if (bytes < kWCMinRecordBytes) {
		wcLog(@"skip preserve last_take — too small (%llu, min %lu)", bytes, (unsigned long)kWCMinRecordBytes);
		return;
	}
	NSString *dir = [dst stringByDeletingLastPathComponent];
	[fm createDirectoryAtPath:dir withIntermediateDirectories:YES attributes:nil error:nil];
	[fm removeItemAtPath:dst error:nil];
	NSError *err = nil;
	if (![fm copyItemAtPath:wavPath toPath:dst error:&err]) {
		wcLog(@"preserve last_take failed: %@", err);
		return;
	}
	wcLog(@"preserved last_take bytes=%llu", bytes);
}

- (void)retryLastTake:(id)sender {
	(void)sender;
	if (self.recording || self.processing) {
		[self userNotify:@"Whisper" body:@"Сейчас занято — дождись конца записи/отправки."];
		return;
	}
	if (!wcHasLastTake()) {
		[self userNotify:@"Whisper" body:@"Нет сохранённой записи для повтора."];
		return;
	}
	NSString *path = wcLastTakePath();
	wcLog(@"retry last_take %@", path);
	self.processing = YES;
	self.statusItem.button.title = @"⏳";
	[self rebuildMenu];
	[self userNotify:@"Whisper" body:@"Повторная расшифровка последней записи…"];
	dispatch_async(dispatch_get_global_queue(QOS_CLASS_USER_INITIATED, 0), ^{
		[self transcribeAndDeliver:path deleteSource:NO];
	});
}

- (void)restartHotkey:(id)sender {
	(void)sender;
	[self stopHotkeyTap];
	if ([self startHotkeyTap]) {
		[self notify:@"Whisper" body:@"Перехват Fn перезапущен."];
	} else {
		[self notify:@"Whisper" body:@"Не удалось — выдай Input Monitoring."];
	}
	[self rebuildMenu];
}

- (void)openInputMonitoring:(id)sender {
	(void)sender;
	wcOpenURL(@"x-apple.systempreferences:com.apple.preference.security?Privacy_ListenEvent");
}

- (void)openLog:(id)sender {
	(void)sender;
	NSString *p = [NSHomeDirectory() stringByAppendingPathComponent:@"Library/Logs/WhisperMacNative.log"];
	if (![[NSFileManager defaultManager] fileExistsAtPath:p]) {
		[[NSFileManager defaultManager] createFileAtPath:p contents:[NSData data] attributes:nil];
	}
	wcOpenPath(p);
}

- (void)openPrefsFolder:(id)sender {
	(void)sender;
	NSString *dir = [wcPrefsPath() stringByDeletingLastPathComponent];
	[[NSFileManager defaultManager] createDirectoryAtPath:dir withIntermediateDirectories:YES attributes:nil error:nil];
	wcOpenPath(dir);
}

- (void)quit:(id)sender {
	(void)sender;
	wcLog(@"user quit");
	[self.heartbeatTimer invalidate];
	self.heartbeatTimer = nil;
	[self.silentKeepAlivePlayer stop];
	self.silentKeepAlivePlayer = nil;
	[self stopHotkeyTap];
	[NSApp terminate:nil];
}

- (BOOL)startHotkeyTap {
	[self ensureInputMonitoringTrust];
	[self stopHotkeyTap];
	g_tapRunning = 1;
	if (pthread_create(&g_tapThread, NULL, wcTapThreadMain, NULL) != 0) {
		wcLog(@"pthread_create tap thread failed");
		g_tapRunning = 0;
		return NO;
	}
	/* Don't usleep on main — spin runloop briefly so UI stays responsive. */
	NSDate *deadline = [NSDate dateWithTimeIntervalSinceNow:0.6];
	while (!g_tap && [[NSDate date] compare:deadline] == NSOrderedAscending) {
		[[NSRunLoop currentRunLoop] runMode:NSDefaultRunLoopMode
		                          beforeDate:[NSDate dateWithTimeIntervalSinceNow:0.05]];
	}
	if (!g_tap) {
		wcLog(@"tap not created after thread start");
		return NO;
	}
	return YES;
}

- (void)stopHotkeyTap {
	if (!g_tapRunning) {
		wcHotkeyUp();
		return;
	}
	g_tapRunning = 0;
	CFRunLoopRef loop = g_tapLoop;
	if (loop) CFRunLoopStop(loop);
	/* Timed join — never block menubar forever if tap thread is wedged. */
	NSDate *deadline = [NSDate dateWithTimeIntervalSinceNow:1.0];
	while (g_tapLoop && [[NSDate date] compare:deadline] == NSOrderedAscending) {
		[[NSRunLoop currentRunLoop] runMode:NSDefaultRunLoopMode
		                          beforeDate:[NSDate dateWithTimeIntervalSinceNow:0.05]];
	}
	if (!g_tapLoop) {
		pthread_join(g_tapThread, NULL);
	} else {
		wcLog(@"tap thread join timeout — leaving thread to exit alone");
	}
	wcHotkeyUp();
}

- (BOOL)ensureInputMonitoringTrust {
	if (AXIsProcessTrusted()) return YES;
	NSDictionary *opts = @{ (__bridge id)kAXTrustedCheckOptionPrompt : @YES };
	(void)AXIsProcessTrustedWithOptions((__bridge CFDictionaryRef)opts);
	wcLog(@"Input Monitoring not trusted — open System Settings");
	return NO;
}

- (void)installKeepAliveAgent {
	/* KeepAlive launchd job в реальный $HOME — переживает sandbox-kill LSUIElement (не-MAS). */
	NSString *home = wcRealHome();
	NSString *dir = [home stringByAppendingPathComponent:@"Library/LaunchAgents"];
	NSString *plistPath = [dir stringByAppendingPathComponent:@"com.zapnikita95.WhisperClient.keepalive.plist"];
	NSString *appPath = [[NSBundle mainBundle] bundlePath];
	if (!appPath.length || ![appPath hasSuffix:@".app"]) return;
	NSDictionary *plist = @{
		@"Label" : @"com.zapnikita95.WhisperClient.keepalive",
		@"RunAtLoad" : @YES,
		@"KeepAlive" : @{ @"SuccessfulExit" : @NO },
		@"ThrottleInterval" : @5,
		@"ProcessType" : @"Interactive",
		@"ProgramArguments" : @[ @"/usr/bin/open", @"-gj", @"-a", appPath ],
	};
	NSError *err = nil;
	[[NSFileManager defaultManager] createDirectoryAtPath:dir withIntermediateDirectories:YES attributes:nil error:nil];
	NSData *data = [NSPropertyListSerialization dataWithPropertyList:plist format:NSPropertyListXMLFormat_v1_0
	                                                         options:0 error:&err];
	if (!data) {
		wcLog(@"keepalive plist serialize fail: %@", err);
		return;
	}
	if (![data writeToFile:plistPath atomically:YES]) {
		wcLog(@"keepalive write denied (sandbox?) path=%@", plistPath);
		return;
	}
	NSString *uid = [NSString stringWithFormat:@"gui/%d", getuid()];
	NSTask *boot = [[NSTask alloc] init];
	boot.launchPath = @"/bin/launchctl";
	boot.arguments = @[ @"bootstrap", uid, plistPath ];
	boot.standardOutput = [NSPipe pipe];
	boot.standardError = [NSPipe pipe];
	@try {
		[boot launch];
		[boot waitUntilExit];
		wcLog(@"keepalive launchctl bootstrap rc=%d", boot.terminationStatus);
	} @catch (NSException *ex) {
		wcLog(@"keepalive launchctl exception: %@", ex);
	}
}

- (void)startSilentKeepAlive {
	/* Sandbox запрещает IOPM PreventAppNap → App Nap замораживает LSUIElement.
	 * Тихий loop AVAudioPlayer держит процесс в audio session — система не усыпляет. */
	if (self.silentKeepAlivePlayer.isPlaying) return;
	NSError *err = nil;
	AVAudioPlayer *p = [[AVAudioPlayer alloc] initWithData:wcSilentWavData() error:&err];
	if (!p) {
		wcLog(@"silent keep-alive player fail: %@", err);
		return;
	}
	p.numberOfLoops = -1;
	p.volume = 0.0;
	p.meteringEnabled = NO;
	if (![p prepareToPlay] || ![p play]) {
		wcLog(@"silent keep-alive play failed");
		return;
	}
	self.silentKeepAlivePlayer = p;
	wcLog(@"silent keep-alive audio loop ON");
}

- (void)renewStayAliveActivity {
	NSProcessInfo *pi = [NSProcessInfo processInfo];
	[pi disableAutomaticTermination:@"WhisperClient menubar"];
	[pi disableSuddenTermination];
	if (self.activityToken) {
		[pi endActivity:self.activityToken];
		self.activityToken = nil;
	}
	/* Не AllowingIdleSystemSleep — иначе App Nap. IdleSystemSleepDisabled не трогаем: Mac должен засыпать. */
	self.activityToken = [pi beginActivityWithOptions:(NSActivityUserInitiated | NSActivityLatencyCritical)
	                                          reason:@"WhisperClient stay-alive dictation"];
}

- (void)registerMasKeepAliveAgent {
	if (@available(macOS 13.0, *)) {
		NSError *regErr = nil;
		SMAppService *agent = [SMAppService agentServiceWithPlistName:@"com.zapnikita95.WhisperClient.keepalive.plist"];
		SMAppServiceStatus st = agent.status;
		if (st != SMAppServiceStatusEnabled) {
			BOOL ok = [agent registerAndReturnError:&regErr];
			wcLog(@"SMAppService keepalive agent ok=%d status=%ld err=%@", ok, (long)st, regErr);
			if (!ok || st == SMAppServiceStatusRequiresApproval) {
				wcLog(@"keepalive agent needs approval: System Settings → General → Login Items → Whisper Client");
			}
		} else {
			wcLog(@"SMAppService keepalive agent already enabled");
		}
	}
}

- (void)enableStayAlive {
	[self renewStayAliveActivity];
	[self startSilentKeepAlive];
	/* IOPM PreventAppNap / PreventUserIdleDisplaySleep в MAS sandbox либо NotPrivileged,
	 * либо держат дисплей вечно — не используем. Silent audio + NSActivity + KeepAlive agent. */
	if (@available(macOS 13.0, *)) {
		NSError *regErr = nil;
		SMAppService *svc = [SMAppService mainAppService];
		SMAppServiceStatus st = svc.status;
		if (st != SMAppServiceStatusEnabled) {
			BOOL ok = [svc registerAndReturnError:&regErr];
			wcLog(@"SMAppService login item ok=%d status=%ld err=%@", ok, (long)st, regErr);
		} else {
			wcLog(@"SMAppService login item already enabled");
		}
	}
	BOOL sandboxed = [[NSProcessInfo processInfo].environment objectForKey:@"APP_SANDBOX_CONTAINER_ID"] != nil;
	if (sandboxed)
		[self registerMasKeepAliveAgent];
	else
		[self installKeepAliveAgent];
}

- (void)ensureStatusItem {
	BOOL hidden = NO;
	if (@available(macOS 11.0, *)) {
		if (self.statusItem && !self.statusItem.visible) {
			self.statusItem.visible = YES;
			hidden = !self.statusItem.visible;
		}
	}
	BOOL need = !self.statusItem || !self.statusItem.button || hidden;
	if (!need) return;
	wcLog(@"statusItem recreate hidden=%d had=%d", hidden, self.statusItem != nil);
	if (self.statusItem) {
		[[NSStatusBar systemStatusBar] removeStatusItem:self.statusItem];
		self.statusItem = nil;
	}
	self.statusItem = [[NSStatusBar systemStatusBar] statusItemWithLength:NSVariableStatusItemLength];
	if (@available(macOS 11.0, *)) self.statusItem.visible = YES;
	self.statusItem.button.title = self.recording ? @"🔴" : (self.processing ? @"⏳" : @"🎤");
	self.statusItem.button.toolTip = @"Whisper: левый клик — запись, правый — меню. Fn удерживать.";
	[self rebuildMenu];
}

- (void)onDidWake:(NSNotification *)n {
	(void)n;
	wcLog(@"workspace did wake — restore status item + tap");
	dispatch_async(dispatch_get_main_queue(), ^{
		[self enableStayAlive];
		[self ensureStatusItem];
		if (!g_tap || !g_tapRunning) [self startHotkeyTap];
	});
}

- (void)applicationDidFinishLaunching:(NSNotification *)note {
	(void)note;
	gApp = self;
	NSSetUncaughtExceptionHandler(&wcUncaughtException);
	[self enableStayAlive];
	self.env = [self loadEnv];
	[self reloadPrefs];
	NSString *verPath = [[[NSBundle mainBundle] bundlePath] stringByAppendingPathComponent:@"Contents/Resources/VERSION"];
	self.appVersion = [NSString stringWithContentsOfFile:verPath encoding:NSUTF8StringEncoding error:nil];
	self.appVersion = [self.appVersion stringByTrimmingCharactersInSet:[NSCharacterSet whitespaceAndNewlineCharacterSet]];
	self.statusItem = [[NSStatusBar systemStatusBar] statusItemWithLength:NSVariableStatusItemLength];
	if (@available(macOS 11.0, *)) self.statusItem.visible = YES;
	self.statusItem.button.title = @"🎤";
	self.statusItem.button.toolTip = @"Whisper: левый клик — запись, правый — меню. Fn удерживать.";
	if (@available(macOS 10.14, *)) {
		[[UNUserNotificationCenter currentNotificationCenter]
		    requestAuthorizationWithOptions:(UNAuthorizationOptionAlert | UNAuthorizationOptionSound)
		                    completionHandler:^(BOOL granted, NSError *err) {
			                    wcLog(@"notification auth granted=%d err=%@", granted, err);
		                    }];
	}
	[self rebuildMenu];
#if WC_HAS_PARAKEET
	{
		NSString *mode = wcBackend(self.prefs, self.env);
		BOOL wantsParakeet = [mode hasPrefix:@"parakeet"];
		if (wantsParakeet && [WCParakeetEngine shared].isSupported) {
			dispatch_async(dispatch_get_global_queue(QOS_CLASS_UTILITY, 0), ^{
				NSError *err = nil;
				BOOL ok = [[WCParakeetEngine shared] ensureLoadedWithError:&err];
				wcLog(@"parakeet preload %@", ok ? @"ready" : (err.localizedDescription ?: @"fail"));
				dispatch_async(dispatch_get_main_queue(), ^{
					[self rebuildMenu];
					if (ok)
						[self userNotify:@"Whisper — Parakeet" body:@"Локальная модель готова (offline)."];
					else if (err)
						[self userNotify:@"Whisper — Parakeet"
						              body:[NSString stringWithFormat:@"Модель не загрузилась: %@", err.localizedDescription]];
				});
			});
		}
	}
#endif
	[AVCaptureDevice requestAccessForMediaType:AVMediaTypeAudio completionHandler:^(BOOL granted) {
		if (!granted) {
			dispatch_async(dispatch_get_main_queue(), ^{
				[self notify:@"Whisper" body:@"Нужен доступ к микрофону в Системных настройках."];
			});
		}
	}];
	if (![self startHotkeyTap]) {
		[self notify:@"Whisper" body:@"Хоткей Fn: Системные настройки → Конфиденциальность → Мониторинг ввода → WhisperClient."];
	}
	[[[NSWorkspace sharedWorkspace] notificationCenter] addObserver:self
	                                                       selector:@selector(onDidWake:)
	                                                           name:NSWorkspaceDidWakeNotification
	                                                         object:nil];
	[self.heartbeatTimer invalidate];
	self.heartbeatTimer = [NSTimer timerWithTimeInterval:15.0 repeats:YES block:^(NSTimer *t) {
		(void)t;
		WCAppDelegate *app = gApp;
		if (!app) return;
		app.heartbeatTicks++;
		[app renewStayAliveActivity];
		if (!app.recording && !app.silentKeepAlivePlayer.isPlaying) [app startSilentKeepAlive];
		BOOL trusted = AXIsProcessTrusted();
		BOOL enabled = g_tap ? CGEventTapIsEnabled(g_tap) : NO;
		BOOL tapOk = g_tap && g_tapRunning && enabled;
		if (!tapOk) {
			if (!g_tap || !g_tapRunning) {
				wcLog(@"watchdog: tap missing — restart trusted=%d", trusted);
				[app startHotkeyTap];
			} else if (trusted && !enabled) {
				wcLog(@"watchdog: tap disabled — re-enable");
				CGEventTapEnable(g_tap, true);
			}
			/* без Input Monitoring tap остаётся disabled — не спамим и не крутим restart */
		}
		[app ensureStatusItem];
		[app wireStatusItemClicks];
		/* Pulse every ~2 min — доказательство, что процесс не заморожен App Nap. */
		if (app.heartbeatTicks % 8 == 0) {
			wcLog(@"heartbeat pulse tap=%d audio=%d recording=%d processing=%d", tapOk ? 1 : 0,
			      app.silentKeepAlivePlayer.isPlaying ? 1 : 0, app.recording, app.processing);
		}
	}];
	[[NSRunLoop mainRunLoop] addTimer:self.heartbeatTimer forMode:NSRunLoopCommonModes];
	/* Не fire() сразу — даём tap-thread 0.5с подняться; первый тик через 15с. */
	wcLog(@"started v=%@ build=%@ server=%@ backend=%@ polish=%@ proxy=%d proxy_url=%@ input_trusted=%d", self.appVersion,
	      [[NSBundle mainBundle] objectForInfoDictionaryKey:@"CFBundleVersion"] ?: @"?", wcServerURL(self.prefs),
	      wcBackend(self.prefs, self.env), wcPolishMode(self.prefs, self.env), wcGroqProxyEnabled(self.prefs, self.env),
	      wcGroqProxyURL(self.prefs, self.env), AXIsProcessTrusted());
}

- (void)onHotkeyDown {
	if (self.recording) return;
	if (self.processing) {
		wcLog(@"ignore hotkey down — still processing previous take");
		return;
	}
	AVAuthorizationStatus mic = [AVCaptureDevice authorizationStatusForMediaType:AVMediaTypeAudio];
	if (mic == AVAuthorizationStatusDenied || mic == AVAuthorizationStatusRestricted) {
		[self userNotify:@"Whisper" body:@"Нет доступа к микрофону — Системные настройки → Конфиденциальность → Микрофон."];
		return;
	}
	if (mic == AVAuthorizationStatusNotDetermined) {
		[AVCaptureDevice requestAccessForMediaType:AVMediaTypeAudio completionHandler:^(BOOL granted) {
			if (granted) dispatch_async(dispatch_get_main_queue(), ^{ [gApp onHotkeyDown]; });
		}];
		return;
	}
	NSRunningApplication *front = [[NSWorkspace sharedWorkspace] frontmostApplication];
	self.pasteTargetPID = front ? front.processIdentifier : 0;
	/* Не мешаем AVAudioRecorder — пауза silent keep-alive на время записи. */
	[self.silentKeepAlivePlayer pause];
	[self preferBuiltInMic];
	/*
	 * AVAudioRecorder — не AVAudioEngine tap.
	 * Tap в menubar/sandbox после ~1–2 с начинал писать нули при живом микрофоне
	 * (76 с файла, речи 2 с → Groq: «Продолжение следует»).
	 */
	NSString *tmp = [NSTemporaryDirectory() stringByAppendingPathComponent:
	                 [NSString stringWithFormat:@"whisper_%@.wav", [[NSUUID UUID] UUIDString]]];
	[[NSFileManager defaultManager] removeItemAtPath:tmp error:nil];
	NSDictionary *settings = @{
		AVFormatIDKey : @(kAudioFormatLinearPCM),
		AVSampleRateKey : @16000,
		AVNumberOfChannelsKey : @1,
		AVLinearPCMBitDepthKey : @16,
		AVLinearPCMIsFloatKey : @NO,
		AVLinearPCMIsBigEndianKey : @NO,
		AVLinearPCMIsNonInterleaved : @NO
	};
	NSError *err = nil;
	AVAudioRecorder *rec = [[AVAudioRecorder alloc] initWithURL:[NSURL fileURLWithPath:tmp] settings:settings error:&err];
	if (!rec || err) {
		wcLog(@"AVAudioRecorder init fail: %@", err);
		[self restoreDictationInput];
		NSBeep();
		[self userNotify:@"Whisper" body:@"Не удалось начать запись — проверь микрофон."];
		return;
	}
	rec.delegate = self;
	rec.meteringEnabled = YES;
	if (![rec prepareToRecord] || ![rec record]) {
		wcLog(@"AVAudioRecorder record failed");
		[self restoreDictationInput];
		NSBeep();
		[self userNotify:@"Whisper" body:@"Микрофон не пишет — проверь устройство ввода и разрешения."];
		return;
	}
	self.audioRecorder = rec;
	self.wavPath = tmp;
	self.recording = YES;
	self.menuRecording = YES;
	self.recordPeakAbs = 0;
	self.statusItem.button.title = @"🔴";
	NSBeep();
	[self rebuildMenu];
	double maxS = wcMaxRecordSeconds(self.prefs);
	[self.maxRecordTimer invalidate];
	self.maxRecordTimer = [NSTimer scheduledTimerWithTimeInterval:maxS repeats:NO block:^(NSTimer *t) {
		(void)t;
		wcLog(@"max record %.0fs reached — auto stop", maxS);
		gApp.latchRecording = NO;
		g_hotkeyPressed = NO;
		[gApp onHotkeyUp];
	}];
	/* Периодический peak из metering — ловим «микрофон умер» по логу. */
	[self.meterTimer invalidate];
	self.meterTimer = [NSTimer timerWithTimeInterval:0.5 repeats:YES block:^(NSTimer *t) {
		(void)t;
		if (!gApp.recording || !gApp.audioRecorder) {
			[gApp.meterTimer invalidate];
			gApp.meterTimer = nil;
			return;
		}
		[gApp.audioRecorder updateMeters];
		float power = [gApp.audioRecorder averagePowerForChannel:0]; /* dB, 0 = full */
		float lin = powf(10.0f, power / 20.0f);
		NSUInteger peak = (NSUInteger)(lin * 32768.0f);
		if (peak > gApp.recordPeakAbs) gApp.recordPeakAbs = peak;
	}];
	[[NSRunLoop mainRunLoop] addTimer:self.meterTimer forMode:NSRunLoopCommonModes];
	wcLog(@"recording AVAudioRecorder %@ 16kHz mono max=%.0fs", tmp, maxS);
}

- (void)audioRecorderEncodeErrorDidOccur:(AVAudioRecorder *)recorder error:(NSError *)error {
	(void)recorder;
	wcLog(@"AVAudioRecorder encode error: %@", error);
}

- (NSString *)convertRecordingToWav:(NSString *)src {
	/* Prefer already-WAV path (new recorder). Never NSTask/afconvert in MAS sandbox. */
	if ([src.pathExtension.lowercaseString isEqualToString:@"wav"]) return src;
	wcLog(@"non-wav recording %@ — send as-is (no afconvert in sandbox)", src);
	return src;
}

/*
 * Обрезает тишину в PCM WAV (16-bit LE). Whisper на длинных нулях галлюцинирует
 * («Продолжение следует…»). Возвращает новый путь или src; *outSpeechSec — длина речи.
 */
static NSString *wcTrimWavSilence(NSString *path, double *outSpeechSec, double *outRawSec) {
	if (outSpeechSec) *outSpeechSec = 0;
	if (outRawSec) *outRawSec = 0;
	NSData *data = [NSData dataWithContentsOfFile:path];
	if (data.length < 44) return path;
	const uint8_t *b = data.bytes;
	if (memcmp(b, "RIFF", 4) != 0 || memcmp(b + 8, "WAVE", 4) != 0) return path;
	uint32_t sampleRate = 0;
	uint16_t channels = 0, bits = 0;
	const uint8_t *dataChunk = NULL;
	uint32_t dataSize = 0;
	size_t off = 12;
	while (off + 8 <= data.length) {
		uint32_t sz;
		memcpy(&sz, b + off + 4, 4);
		if (memcmp(b + off, "fmt ", 4) == 0 && off + 8 + sz <= data.length && sz >= 16) {
			memcpy(&channels, b + off + 10, 2);
			memcpy(&sampleRate, b + off + 12, 4);
			memcpy(&bits, b + off + 22, 2);
		} else if (memcmp(b + off, "data", 4) == 0 && off + 8 + sz <= data.length) {
			dataChunk = b + off + 8;
			dataSize = sz;
			break;
		}
		off += 8 + sz;
		if (sz & 1) off++;
	}
	if (!dataChunk || !sampleRate || channels < 1 || bits != 16) return path;
	NSUInteger nFrames = dataSize / (channels * 2);
	if (nFrames < 2) return path;
	if (outRawSec) *outRawSec = (double)nFrames / (double)sampleRate;
	const int16_t *samples = (const int16_t *)dataChunk;
	const int16_t thr = 200; /* ~тишина; речь обычно >> */
	NSInteger first = -1, last = -1;
	for (NSUInteger i = 0; i < nFrames; i++) {
		BOOL loud = NO;
		for (uint16_t c = 0; c < channels; c++) {
			if (abs(samples[i * channels + c]) > thr) {
				loud = YES;
				break;
			}
		}
		if (loud) {
			if (first < 0) first = (NSInteger)i;
			last = (NSInteger)i;
		}
	}
	if (first < 0 || last < first) {
		wcLog(@"trim: entire wav is silence frames=%lu", (unsigned long)nFrames);
		if (outSpeechSec) *outSpeechSec = 0;
		return path;
	}
	NSInteger pad = (NSInteger)(sampleRate / 10); /* 100ms */
	NSInteger a = MAX((NSInteger)0, first - pad);
	NSInteger bEnd = MIN((NSInteger)nFrames - 1, last + pad);
	NSUInteger keepFrames = (NSUInteger)(bEnd - a + 1);
	if (outSpeechSec) *outSpeechSec = (double)keepFrames / (double)sampleRate;
	/* Если почти всё и так речь — не трогаем. */
	if (keepFrames >= nFrames * 0.92) return path;
	NSUInteger keepBytes = keepFrames * channels * 2;
	NSMutableData *out = [NSMutableData dataWithCapacity:44 + keepBytes];
	uint8_t hdr[44];
	memcpy(hdr, "RIFF", 4);
	uint32_t riffSize = 36 + (uint32_t)keepBytes;
	memcpy(hdr + 4, &riffSize, 4);
	memcpy(hdr + 8, "WAVE", 4);
	memcpy(hdr + 12, "fmt ", 4);
	uint32_t fmtSize = 16;
	memcpy(hdr + 16, &fmtSize, 4);
	uint16_t audioFormat = 1;
	memcpy(hdr + 20, &audioFormat, 2);
	memcpy(hdr + 22, &channels, 2);
	memcpy(hdr + 24, &sampleRate, 4);
	uint32_t byteRate = sampleRate * channels * 2;
	memcpy(hdr + 28, &byteRate, 4);
	uint16_t blockAlign = channels * 2;
	memcpy(hdr + 32, &blockAlign, 2);
	memcpy(hdr + 34, &bits, 2);
	memcpy(hdr + 36, "data", 4);
	uint32_t ds = (uint32_t)keepBytes;
	memcpy(hdr + 40, &ds, 4);
	[out appendBytes:hdr length:44];
	[out appendBytes:samples + a * channels length:keepBytes];
	NSString *dst = [path stringByAppendingString:@"_trim.wav"];
	if (![out writeToFile:dst atomically:YES]) {
		wcLog(@"trim: write fail %@", dst);
		return path;
	}
	wcLog(@"trim silence: %.1fs → %.1fs (speech %.2f–%.2f) %@", (double)nFrames / sampleRate,
	      (double)keepFrames / sampleRate, (double)first / sampleRate, (double)last / sampleRate, dst);
	return dst;
}

- (void)preferBuiltInMic {
	AudioDeviceID cur = wcDefaultInputDevice();
	NSString *wantName = nil;
	AudioDeviceID want = wcPreferredDictationInput(&wantName);
	NSString *curName = wcAudioDeviceName(cur);
	UInt32 ctr = wcAudioTransport(cur);
	wcLog(@"mic current='%@' (%s) prefer='%@' id=%u", curName, wcTransportLabel(ctr), wantName, (unsigned)want);
	if (want && want != cur) {
		self.savedInputDevice = cur;
		if (wcSetDefaultInputDevice(want)) {
			wcLog(@"mic switched → '%@' (was '%@')", wantName, curName);
			[[NSRunLoop currentRunLoop] runMode:NSDefaultRunLoopMode
			                          beforeDate:[NSDate dateWithTimeIntervalSinceNow:0.12]];
		} else {
			self.savedInputDevice = 0;
		}
	} else {
		self.savedInputDevice = 0;
	}
}

- (void)restoreDictationInput {
	if (!self.savedInputDevice) return;
	AudioDeviceID prev = self.savedInputDevice;
	self.savedInputDevice = 0;
	if (wcSetDefaultInputDevice(prev))
		wcLog(@"mic restored → '%@'", wcAudioDeviceName(prev));
}

- (void)onHotkeyUp {
	if (!self.recording) return;
	if (self.latchRecording) {
		wcLog(@"ignore Fn-up — latch, кликни 🎤 ещё раз для стопа");
		return;
	}
	[self.maxRecordTimer invalidate];
	self.maxRecordTimer = nil;
	[self.meterTimer invalidate];
	self.meterTimer = nil;
	self.recording = NO;
	self.menuRecording = NO;
	self.statusItem.button.title = @"⏳";
	AVAudioRecorder *rec = self.audioRecorder;
	NSString *path = self.wavPath;
	self.audioRecorder = nil;
	self.wavPath = nil;
	if (rec) {
		@try {
			[rec stop];
		} @catch (NSException *ex) {
			wcLog(@"recorder stop exception: %@", ex);
		}
	}
	[self restoreDictationInput];
	self.processing = YES;
	[self rebuildMenu];
	if (!path.length) {
		self.processing = NO;
		self.statusItem.button.title = @"🎤";
		[self rebuildMenu];
		return;
	}
	NSUInteger bytes = [[[NSFileManager defaultManager] attributesOfItemAtPath:path error:nil] fileSize];
	wcLog(@"stopped recording %@ bytes=%lu peak=%lu", path, (unsigned long)bytes, (unsigned long)self.recordPeakAbs);
	/* Короче ~0.5 с — случайный тап Globe/Fn: молча выкидываем, без ASR и без вставки. */
	if (bytes < kWCMinRecordBytes) {
		wcLog(@"reject: too short bytes=%lu (min %lu ≈ %.1fs)", (unsigned long)bytes,
		      (unsigned long)kWCMinRecordBytes, kWCMinRecordSec);
		[[NSFileManager defaultManager] removeItemAtPath:path error:nil];
		self.processing = NO;
		self.statusItem.button.title = @"🎤";
		[self rebuildMenu];
		[self startSilentKeepAlive];
		return;
	}
	[self userNotify:@"Whisper" body:@"Обрабатываю запись…"];
	dispatch_async(dispatch_get_global_queue(QOS_CLASS_USER_INITIATED, 0), ^{
		@try {
			NSString *wav = [self convertRecordingToWav:path];
			double speechSec = 0, rawSec = 0;
			NSString *trimmed = wcTrimWavSilence(wav, &speechSec, &rawSec);
			if (trimmed.length && ![trimmed isEqualToString:wav] && ![wav isEqualToString:path]) {
				[[NSFileManager defaultManager] removeItemAtPath:wav error:nil];
			}
			wav = trimmed;
			if (rawSec < kWCMinRecordSec || speechSec < kWCMinRecordSec) {
				wcLog(@"reject: too short speech=%.2fs raw=%.1fs (min %.1fs)", speechSec, rawSec, kWCMinRecordSec);
				if (rawSec >= kWCMinRecordSec && speechSec < 0.05)
					[self preserveTakeForRetry:wav]; /* длинная тишина — оставить для диагностики */
				else
					[[NSFileManager defaultManager] removeItemAtPath:wav error:nil];
				BOOL silenceLong = (rawSec >= kWCMinRecordSec && speechSec < 0.05);
				dispatch_async(dispatch_get_main_queue(), ^{
					if (silenceLong) {
						[self userNotify:@"Whisper"
						              body:
						                  [NSString stringWithFormat:
						                       @"Микрофон записал тишину (%.0f с). Часто виноваты Bluetooth-наушники — "
						                       @"в следующей записи беру микрофон MacBook. Кликни 🎤 ещё раз.",
						                       rawSec]];
					}
					[self finishProcessingAfterDelay:0.2];
				});
				return;
			}
			if (rawSec > 3.0 && speechSec < rawSec * 0.35) {
				wcLog(@"warn: mostly silence raw=%.1fs speech=%.1fs — trimmed before ASR", rawSec, speechSec);
			}
			[self preserveTakeForRetry:wav];
			[self transcribeAndDeliver:wav deleteSource:![wav isEqualToString:wcLastTakePath()]];
		} @catch (NSException *ex) {
			wcLog(@"transcribe pipeline exception: %@", ex);
			dispatch_async(dispatch_get_main_queue(), ^{
				[self userNotify:@"Whisper — ошибка" body:@"Сбой обработки записи. Попробуй «Повторить расшифровку»."];
				[self finishProcessingAfterDelay:0.2];
			});
		}
	});
}

- (NSString *)extractText:(NSDictionary *)json {
	id t = json[@"text"];
	return [t isKindOfClass:[NSString class]] ? [(NSString *)t stringByTrimmingCharactersInSet:[NSCharacterSet whitespaceAndNewlineCharacterSet]] : @"";
}

- (NSData *)multipartBody:(NSString *)boundary fields:(NSDictionary *)fields fileField:(NSString *)fileField
                 fileName:(NSString *)fileName fileData:(NSData *)fileData mime:(NSString *)mime {
	NSMutableData *body = [NSMutableData data];
	void (^append)(NSString *) = ^(NSString *s) { [body appendData:[s dataUsingEncoding:NSUTF8StringEncoding]]; };
	for (NSString *k in fields) {
		append([NSString stringWithFormat:@"--%@\r\n", boundary]);
		append([NSString stringWithFormat:@"Content-Disposition: form-data; name=\"%@\"\r\n\r\n", k]);
		append([NSString stringWithFormat:@"%@\r\n", fields[k]]);
	}
	append([NSString stringWithFormat:@"--%@\r\n", boundary]);
	append([NSString stringWithFormat:@"Content-Disposition: form-data; name=\"%@\"; filename=\"%@\"\r\n", fileField, fileName]);
	append([NSString stringWithFormat:@"Content-Type: %@\r\n\r\n", mime]);
	[body appendData:fileData];
	append([NSString stringWithFormat:@"\r\n--%@--\r\n", boundary]);
	return body;
}

- (NSDictionary *)transcribeParakeet:(NSString *)wavPath error:(NSError **)outErr {
#if WC_HAS_PARAKEET
	WCParakeetEngine *engine = [WCParakeetEngine shared];
	if (!engine.isSupported) {
		if (outErr)
			*outErr = [NSError errorWithDomain:@"wc" code:3
			                          userInfo:@{NSLocalizedDescriptionKey : @"Parakeet нужен Apple Silicon + macOS 14+"}];
		return nil;
	}
	static dispatch_once_t onceNotify;
	dispatch_once(&onceNotify, ^{
		if (!engine.isReady) {
			dispatch_async(dispatch_get_main_queue(), ^{
				[self userNotify:@"Whisper — Parakeet"
				              body:@"Первый запуск: скачиваю локальную модель (~460 МБ). Интернет нужен один раз."];
			});
		}
	});
	NSError *err = nil;
	NSString *lang = wcParakeetLanguage(self.prefs, self.env);
	NSDate *t0 = [NSDate date];
	NSString *text = [engine transcribeWavAtPath:wavPath languageCode:lang error:&err];
	NSTimeInterval ms = [[NSDate date] timeIntervalSinceDate:t0] * 1000.0;
	if (!text.length) {
		if (outErr) *outErr = err ?: [NSError errorWithDomain:@"wc" code:4
		                                              userInfo:@{NSLocalizedDescriptionKey : @"parakeet empty"}];
		return nil;
	}
	wcLog(@"parakeet OK len=%lu %.0fms lang=%@", (unsigned long)text.length, ms, lang ?: @"auto");
	return @{ @"text" : text, @"route" : @"parakeet", @"latency_ms" : @((NSInteger)ms) };
#else
	if (outErr)
		*outErr = [NSError errorWithDomain:@"wc" code:3
		                          userInfo:@{NSLocalizedDescriptionKey : @"сборка без Parakeet"}];
	return nil;
#endif
}

- (NSDictionary *)transcribeServer:(NSString *)wavPath error:(NSError **)outErr {
	NSString *urlStr = [NSString stringWithFormat:@"%@/transcribe", wcServerURL(self.prefs)];
	NSData *wav = [NSData dataWithContentsOfFile:wavPath];
	if (!wav.length) {
		if (outErr) *outErr = [NSError errorWithDomain:@"wc" code:1 userInfo:@{NSLocalizedDescriptionKey : @"empty wav"}];
		return nil;
	}
	NSString *boundary = [[NSUUID UUID] UUIDString];
	NSData *mpBody = [self multipartBody:boundary fields:@{@"spoken_punctuation" : @"false"} fileField:@"audio"
	                              fileName:@"audio.wav" fileData:wav mime:@"audio/wav"];
	NSDictionary *hdr = @{
		@"Content-Type" : [NSString stringWithFormat:@"multipart/form-data; boundary=%@", boundary],
		@"X-Whisper-Client" : @"mac"
	};
	NSInteger status = -1;
	NSData *respData = nil;
	NSError *err = nil;
	if (!wcHttpRequest(@"POST", urlStr, mpBody, hdr, 900, &status, &respData, &err)) {
		if (outErr) *outErr = err;
		return nil;
	}
	if (status >= 400) {
		NSString *detail = [[NSString alloc] initWithData:respData encoding:NSUTF8StringEncoding] ?: @"server error";
		if (outErr) *outErr = [NSError errorWithDomain:@"wc" code:status userInfo:@{NSLocalizedDescriptionKey : detail}];
		return nil;
	}
	id json = [NSJSONSerialization JSONObjectWithData:respData options:0 error:&err];
	if (err) { if (outErr) *outErr = err; return nil; }
	return [json isKindOfClass:[NSDictionary class]] ? json : nil;
}

- (NSDictionary *)transcribeGroqOnce:(NSString *)wavPath useProxy:(BOOL)useProxy error:(NSError **)outErr {
	NSString *key = wcGroqKey(self.prefs, self.env);
	NSString *proxy = useProxy ? wcGroqProxyURL(self.prefs, self.env) : @"";
	NSString *urlStr = proxy.length ? [NSString stringWithFormat:@"%@/openai/v1/audio/transcriptions", proxy] : kGroqURL;
	if (!proxy.length && !key.length) {
		if (outErr) *outErr = [NSError errorWithDomain:@"wc" code:2 userInfo:@{NSLocalizedDescriptionKey : @"no groq key"}];
		return nil;
	}
	NSData *wav = [NSData dataWithContentsOfFile:wavPath];
	if (!wav.length) {
		if (outErr) *outErr = [NSError errorWithDomain:@"wc" code:1 userInfo:@{NSLocalizedDescriptionKey : @"empty wav"}];
		return nil;
	}
	wcLog(@"groq POST %@ proxy=%d bytes=%lu", urlStr, (int)(proxy.length > 0), (unsigned long)wav.length);
	NSMutableURLRequest *req = [NSMutableURLRequest requestWithURL:[NSURL URLWithString:urlStr]];
	req.HTTPMethod = @"POST";
	/* Layero edge часто рвёт/503 на больших POST (~60s). Быстрый fail → fallback на Railway/direct. */
	NSTimeInterval hardWait = proxy.length ? 20.0 : 180.0;
	req.timeoutInterval = hardWait;
	if (key.length) [req setValue:[NSString stringWithFormat:@"Bearer %@", key] forHTTPHeaderField:@"Authorization"];
	NSString *secret = wcGroqProxySecret(self.prefs, self.env);
	if (proxy.length && secret.length)
		[req setValue:secret forHTTPHeaderField:@"X-Whisper-Groq-Proxy-Secret"];
	NSString *boundary = [[NSUUID UUID] UUIDString];
	[req setValue:[NSString stringWithFormat:@"multipart/form-data; boundary=%@", boundary] forHTTPHeaderField:@"Content-Type"];
	req.HTTPBody = [self multipartBody:boundary
	                            fields:@{
		                            @"model" : kGroqModel,
		                            @"response_format" : @"json",
		                            @"language" : @"ru"
	                            }
	                         fileField:@"file"
	                          fileName:@"audio.wav"
	                          fileData:wav
	                              mime:@"audio/wav"];
	dispatch_semaphore_t sem = dispatch_semaphore_create(0);
	__block NSData *respData = nil;
	__block NSURLResponse *resp = nil;
	__block NSError *err = nil;
	NSURLSessionDataTask *task =
	    [[NSURLSession sharedSession] dataTaskWithRequest:req
	                                    completionHandler:^(NSData *d, NSURLResponse *r, NSError *e) {
		                                    respData = d;
		                                    resp = r;
		                                    err = e;
		                                    dispatch_semaphore_signal(sem);
	                                    }];
	[task resume];
	long waitRc = dispatch_semaphore_wait(sem, dispatch_time(DISPATCH_TIME_NOW, (int64_t)(hardWait * NSEC_PER_SEC)));
	if (waitRc != 0) {
		[task cancel];
		if (outErr)
			*outErr = [NSError errorWithDomain:@"wc" code:-1001
			                          userInfo:@{NSLocalizedDescriptionKey :
			                                         [NSString stringWithFormat:@"groq timeout (%.0fs)", hardWait]}];
		return nil;
	}
	if (err) { if (outErr) *outErr = err; return nil; }
	NSHTTPURLResponse *http = (NSHTTPURLResponse *)resp;
	if (http.statusCode >= 400) {
		NSString *detail = [[NSString alloc] initWithData:respData ?: [NSData data] encoding:NSUTF8StringEncoding] ?: @"";
		if (detail.length > 180) detail = [[detail substringToIndex:180] stringByAppendingString:@"…"];
		if (!detail.length) detail = [NSString stringWithFormat:@"HTTP %ld", (long)http.statusCode];
		if (outErr)
			*outErr = [NSError errorWithDomain:@"wc" code:http.statusCode
			                          userInfo:@{NSLocalizedDescriptionKey : detail}];
		return nil;
	}
	id json = [NSJSONSerialization JSONObjectWithData:respData options:0 error:&err];
	if (err) { if (outErr) *outErr = err; return nil; }
	return [json isKindOfClass:[NSDictionary class]] ? json : nil;
}

- (NSDictionary *)transcribeGroq:(NSString *)wavPath error:(NSError **)outErr {
	BOOL proxyOn = wcGroqProxyEnabled(self.prefs, self.env);
	NSError *firstErr = nil;
	NSDictionary *result = [self transcribeGroqOnce:wavPath useProxy:proxyOn error:&firstErr];
	if (result) return result;
	/* Fallback: proxy ↔ direct, чтобы не зависеть от одного канала из РФ. */
	BOOL tryOther = !proxyOn;
	if (proxyOn) {
		NSInteger code = firstErr.code;
		BOOL retryWorthy = (code == -1001) || (code == NSURLErrorTimedOut) || (code == NSURLErrorCannotConnectToHost) ||
		                   (code == NSURLErrorNetworkConnectionLost) || (code == NSURLErrorNotConnectedToInternet) ||
		                   (code == 403) || (code == 404) || (code == 405) || (code == 408) ||
		                   (code == 429) || (code == 500) || (code == 502) || (code == 503) || (code == 504);
		NSString *msg = firstErr.localizedDescription.lowercaseString ?: @"";
		if ([msg containsString:@"methodnotallowed"] || [msg containsString:@"адрес свободен"] ||
		    [msg containsString:@"forbidden"] || [msg containsString:@"bad gateway"] ||
		    [msg containsString:@"timeout"] || [msg containsString:@"too short"])
			retryWorthy = YES;
		tryOther = retryWorthy;
	} else {
		tryOther = YES; /* proxy was OFF — try proxy once if direct failed */
	}
	if (tryOther) {
		wcLog(@"groq fallback %@ → %@", proxyOn ? @"proxy" : @"direct", proxyOn ? @"direct" : @"proxy");
		NSError *secondErr = nil;
		result = [self transcribeGroqOnce:wavPath useProxy:!proxyOn error:&secondErr];
		if (result) return result;
		if (outErr) *outErr = secondErr ?: firstErr;
		return nil;
	}
	if (outErr) *outErr = firstErr;
	return nil;
}

- (void)transcribeAndDeliver:(NSString *)wavPath deleteSource:(BOOL)deleteSource {
	double speechSec = 0, rawSec = 0;
	NSString *workPath = wcTrimWavSilence(wavPath, &speechSec, &rawSec);
	if (rawSec < kWCMinRecordSec || speechSec < kWCMinRecordSec) {
		wcLog(@"transcribe abort: too short speech=%.2fs raw=%.1fs (min %.1fs)", speechSec, rawSec,
		      kWCMinRecordSec);
		dispatch_async(dispatch_get_main_queue(), ^{
			/* Случайный тап — без баннера и без вставки. */
			[self finishProcessingAfterDelay:0.15];
		});
		if (deleteSource && workPath.length && ![workPath isEqualToString:wcLastTakePath()])
			[[NSFileManager defaultManager] removeItemAtPath:workPath error:nil];
		return;
	}
	if (workPath.length && ![workPath isEqualToString:wavPath]) {
		/* Сохраняем обрезанный take для retry — иначе снова улетит тишина. */
		[self preserveTakeForRetry:workPath];
		if (deleteSource && wavPath.length && ![wavPath isEqualToString:wcLastTakePath()])
			[[NSFileManager defaultManager] removeItemAtPath:wavPath error:nil];
		wavPath = workPath;
		deleteSource = YES;
	}
	NSString *mode = wcBackend(self.prefs, self.env);
	NSDictionary *result = nil;
	NSError *lastErr = nil;
	NSString *usedRoute = nil;
	for (NSString *route in wcBackendOrder(mode)) {
		usedRoute = route;
		wcLog(@"transcribe try route=%@", route);
		@try {
			if ([route isEqualToString:@"parakeet"])
				result = [self transcribeParakeet:wavPath error:&lastErr];
			else if ([route isEqualToString:@"server"])
				result = [self transcribeServer:wavPath error:&lastErr];
			else
				result = [self transcribeGroq:wavPath error:&lastErr];
		} @catch (NSException *ex) {
			wcLog(@"transcribe %@ exception: %@", route, ex);
			lastErr = [NSError errorWithDomain:@"wc" code:-2
			                          userInfo:@{NSLocalizedDescriptionKey : ex.reason ?: @"exception"}];
			result = nil;
		}
		if (result) break;
		wcLog(@"transcribe %@ failed: %@", route, lastErr);
	}
	[self preserveTakeForRetry:wavPath];
	if (deleteSource && wavPath.length && ![wavPath isEqualToString:wcLastTakePath()]) {
		[[NSFileManager defaultManager] removeItemAtPath:wavPath error:nil];
	}
	if (!result) {
		NSString *msg = lastErr.localizedDescription ?: @"нет ответа";
		dispatch_async(dispatch_get_main_queue(), ^{
			[self rebuildMenu];
			[self userNotify:@"Whisper — ошибка"
			              body:[NSString stringWithFormat:@"%@: %@. Аудио сохранено — меню → «Повторить расшифровку».",
			                                              usedRoute ?: @"?", msg]];
			[self finishProcessingAfterDelay:0.15];
		});
		return;
	}
	NSString *text = [self extractText:result];
	if (!text.length) {
		dispatch_async(dispatch_get_main_queue(), ^{
			[self rebuildMenu];
			[self userNotify:@"Whisper" body:@"Пустой ответ. Можно повторить расшифровку из меню."];
			[self finishProcessingAfterDelay:0.15];
		});
		return;
	}
	NSString *polishMode = wcPolishMode(self.prefs, self.env);
	if (![polishMode isEqualToString:@"off"]) {
		NSError *perr = nil;
		NSString *polished = wcPolishText(text, polishMode, self.prefs, self.env, &perr);
		if (perr) wcLog(@"polish fail (keeping STT): %@", perr);
		if (polished.length) {
			wcLog(@"polish %@ %lu → %lu chars", polishMode, (unsigned long)text.length, (unsigned long)polished.length);
			text = polished;
		}
	}
	wcLog(@"text len=%lu route=%@ polish=%@", (unsigned long)text.length, usedRoute, polishMode);
	@try {
		[self appendHistory:text];
	} @catch (NSException *ex) {
		wcLog(@"appendHistory exception: %@", ex);
	}
	NSString *preview = text.length > 160 ? [[text substringToIndex:160] stringByAppendingString:@"…"] : text;
	NSString *pasteMode = wcPasteMode(self.prefs);
	pid_t target = self.pasteTargetPID;
	dispatch_async(dispatch_get_main_queue(), ^{
		@try {
			[self rebuildMenu];
			[[NSPasteboard generalPasteboard] clearContents];
			[[NSPasteboard generalPasteboard] setString:text forType:NSPasteboardTypeString];
			if ([pasteMode isEqualToString:@"history_only"]) {
				[self userNotify:@"Whisper — готово" body:preview];
				[self finishProcessingAfterDelay:0.2];
				return;
			}
			if ([pasteMode isEqualToString:@"clipboard"]) {
				[self userNotify:@"Whisper — готово, в буфере" body:preview];
				[self finishProcessingAfterDelay:0.2];
				return;
			}
			[self pasteCmdV:target];
			[self userNotify:@"Whisper — готово" body:preview];
			/* processing держим до конца Cmd+V — иначе Fn стартует запись и роняет engine. */
			[self finishProcessingAfterDelay:0.45];
		} @catch (NSException *ex) {
			wcLog(@"deliver UI exception: %@", ex);
			[self finishProcessingAfterDelay:0.2];
		}
	});
}

- (BOOL)menuHasKeyEquivalent:(NSMenu *)menu forEvent:(NSEvent *)event target:(id *)target action:(SEL *)action {
	(void)menu;
	(void)event;
	(void)target;
	(void)action;
	return NO;
}

- (void)menuWillOpen:(NSMenu *)menu {
	(void)menu;
	self.menuIsOpen = YES;
	[NSApp activateIgnoringOtherApps:YES];
}

- (void)menuDidClose:(NSMenu *)menu {
	(void)menu;
	self.menuIsOpen = NO;
	if (self.menuNeedsRebuild) [self rebuildMenu];
}

- (void)pasteCmdV:(pid_t)targetPID {
	void (^firePaste)(void) = ^{
		CGEventSourceRef src = CGEventSourceCreate(kCGEventSourceStateHIDSystemState);
		if (!src) return;
		CGEventRef down = CGEventCreateKeyboardEvent(src, (CGKeyCode)9, true);
		CGEventRef up = CGEventCreateKeyboardEvent(src, (CGKeyCode)9, false);
		CGEventSetFlags(down, kCGEventFlagMaskCommand);
		CGEventSetFlags(up, kCGEventFlagMaskCommand);
		CGEventPost(kCGHIDEventTap, down);
		CGEventPost(kCGHIDEventTap, up);
		CFRelease(down);
		CFRelease(up);
		CFRelease(src);
	};
	if (targetPID > 0) {
		for (NSRunningApplication *app in [[NSWorkspace sharedWorkspace] runningApplications]) {
			if (app.processIdentifier == targetPID) {
				[app activateWithOptions:NSApplicationActivateIgnoringOtherApps];
				break;
			}
		}
		/* Never usleep on main — that froze menubar after paste. */
		dispatch_after(dispatch_time(DISPATCH_TIME_NOW, (int64_t)(0.12 * NSEC_PER_SEC)), dispatch_get_main_queue(),
		               firePaste);
	} else {
		firePaste();
	}
}

- (BOOL)applicationShouldTerminateAfterLastWindowClosed:(NSApplication *)sender {
	(void)sender;
	return NO;
}

- (NSApplicationTerminateReply)applicationShouldTerminate:(NSApplication *)sender {
	(void)sender;
	wcLog(@"applicationShouldTerminate");
	return NSTerminateNow;
}

@end

int main(int argc, const char *argv[]) {
	(void)argc;
	(void)argv;
	@autoreleasepool {
		NSString *bid = [[NSBundle mainBundle] bundleIdentifier] ?: @"com.zapnikita95.WhisperClient";
		for (NSRunningApplication *other in [NSRunningApplication runningApplicationsWithBundleIdentifier:bid]) {
			if (other.processIdentifier != getpid() && !other.terminated) {
				/* KeepAlive мог поднять второй инстанс — выходим 0, чтобы SuccessfulExit не крутил цикл. */
				fprintf(stderr, "WhisperClient: another instance pid=%d — exit duplicate\n", other.processIdentifier);
				return 0;
			}
		}
		signal(SIGTERM, wcSignalLog);
		signal(SIGINT, wcSignalLog);
		signal(SIGABRT, wcSignalLog);
		NSApplication *app = [NSApplication sharedApplication];
		[app setActivationPolicy:NSApplicationActivationPolicyAccessory];
		WCAppDelegate *delegate = [[WCAppDelegate alloc] init];
		app.delegate = delegate;
		[app run];
	}
	return 0;
}
