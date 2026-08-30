/*
 * WhisperClient — нативный MAS клиент: menubar, CGEventTap, Groq/сервер, вставка.
 */
#import <Cocoa/Cocoa.h>
#import <AVFoundation/AVFoundation.h>
#import <ApplicationServices/ApplicationServices.h>
#import <Carbon/Carbon.h>
#import <UserNotifications/UserNotifications.h>
#import <pwd.h>
#import <pthread.h>
#import "whisper_client_api.h"

static NSString *const kDefaultServerHost = @"100.115.68.2";
static const NSInteger kDefaultServerPort = 8001;
static NSString *const kGroqURL = @"https://api.groq.com/openai/v1/audio/transcriptions";
static NSString *const kGroqModel = @"whisper-large-v3";
/* Layero RF mirror → Railway groq_proxy (без VPN из РФ). */
static NSString *const kDefaultGroqProxyURL = @"https://whisper-groq-proxy-production.up.railway.app";

static const CGEventFlags kModFn = kCGEventFlagMaskSecondaryFn;
static const CGEventFlags kOtherMods =
    (kCGEventFlagMaskCommand | kCGEventFlagMaskControl | kCGEventFlagMaskAlternate | kCGEventFlagMaskShift);
static CFMachPortRef g_tap = NULL;
static BOOL g_hotkeyPressed = NO;
static volatile int g_tapRunning = 0;
static pthread_t g_tapThread;
static CFRunLoopRef g_tapLoop = NULL;

@interface WCAppDelegate : NSObject <NSApplicationDelegate, NSMenuDelegate>
@property(nonatomic, strong) NSStatusItem *statusItem;
@property(nonatomic, copy) NSString *appVersion;
@property(nonatomic, strong) AVAudioEngine *audioEngine;
@property(nonatomic, strong) AVAudioFile *audioFile;
@property(nonatomic, copy) NSString *wavPath;
@property(nonatomic, assign) pid_t pasteTargetPID;
@property(nonatomic, assign) BOOL recording;
@property(nonatomic, assign) BOOL menuRecording;
@property(nonatomic, assign) BOOL processing; /* afconvert/upload — UI must stay alive */
@property(nonatomic, assign) BOOL menuIsOpen;
@property(nonatomic, assign) BOOL menuNeedsRebuild;
@property(nonatomic, strong) NSTimer *maxRecordTimer;
@property(nonatomic, strong) NSMutableDictionary *prefs;
@property(nonatomic, strong) NSDictionary *env;
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
- (void)menuStopRecord:(id)sender;
- (void)retryLastTake:(id)sender;
- (void)restartHotkey:(id)sender;
- (void)openInputMonitoring:(id)sender;
- (void)openLog:(id)sender;
- (void)openPrefsFolder:(id)sender;
- (void)quit:(id)sender;
@end

static WCAppDelegate *gApp = nil;

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
	if (type == kCGEventFlagsChanged) {
		if (wcFnCombo(CGEventGetFlags(event))) wcHotkeyDown();
		else wcHotkeyUp();
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
	return b.length ? b : @"server_then_groq";
}

static NSArray<NSString *> *wcBackendOrder(NSString *mode) {
	if ([mode isEqualToString:@"groq"]) return @[ @"groq" ];
	if ([mode isEqualToString:@"server"]) return @[ @"server" ];
	if ([mode isEqualToString:@"groq_then_server"]) return @[ @"groq", @"server" ];
	return @[ @"server", @"groq" ];
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
	NSDictionary *m = @{
		@"server" : @"Только мой сервер",
		@"groq" : @"Только Groq",
		@"server_then_groq" : @"Сервер → Groq",
		@"groq_then_server" : @"Groq → сервер"
	};
	return m[mode] ?: mode;
}

static NSString *wcPasteLabel(NSString *mode) {
	NSDictionary *m = @{ @"auto" : @"В поле + буфер", @"clipboard" : @"Только буфер", @"history_only" : @"Только история" };
	return m[mode] ?: mode;
}

/* Hard cap: unlimited prefs used to leave main thread stuck on huge afconvert. */
static const double kWCHardMaxRecordSec = 600.0;
static const double kWCDefaultMaxRecordSec = 300.0;

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
	/* One-shot b53: dead Layero URLs + re-enable proxy after mirror restore. */
	BOOL changed = NO;
	NSString *purl = wcStringPref(self.prefs, @"groq_proxy_url");
	if (purl.length) {
		NSString *l = purl.lowercaseString;
		if ([l containsString:@"anyquery-whisper-groq-proxy"] || [l containsString:@"preview.layero.ru"]) {
			[self.prefs removeObjectForKey:@"groq_proxy_url"];
			changed = YES;
		}
	}
	if (!self.prefs[@"groq_proxy_migrated_b53"]) {
		self.prefs[@"groq_proxy_enabled"] = @YES;
		self.prefs[@"groq_proxy_migrated_b53"] = @YES;
		changed = YES;
		wcLog(@"migrated groq proxy ON → %@", kDefaultGroqProxyURL);
	}
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
		if (!self.recording) self.statusItem.button.title = @"🎤";
		[self rebuildMenu];
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
	[menu addItem:[self disabled:[NSString stringWithFormat:@"Сервер: %@", url]]];
	[menu addItem:[self disabled:[NSString stringWithFormat:@"Транскрипция: %@", wcBackendLabel(curBackend)]]];
	[menu addItem:[self disabled:[NSString stringWithFormat:@"Текст: %@", wcPasteLabel(curPaste)]]];
	[menu addItem:[self disabled:hk]];
	if (self.processing) [menu addItem:[self disabled:@"⏳ Обработка записи…"]];
	[menu addItem:[NSMenuItem separatorItem]];
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
	self.statusItem.menu = menu;
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
	self.prefs[@"transcribe_backend"] = mode;
	[self savePrefs];
	[self rebuildMenu];
	[self userNotify:@"Whisper" body:[NSString stringWithFormat:@"Транскрипция: %@", wcBackendLabel(mode)]];
}

- (void)setBackendServer:(id)s { (void)s; [self setBackend:@"server"]; }
- (void)setBackendGroq:(id)s { (void)s; [self setBackend:@"groq"]; }
- (void)setBackendServerGroq:(id)s { (void)s; [self setBackend:@"server_then_groq"]; }
- (void)setBackendGroqServer:(id)s { (void)s; [self setBackend:@"groq_then_server"]; }

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
	[[NSWorkspace sharedWorkspace] openFile:p];
}

- (void)menuStartRecord:(id)sender {
	(void)sender;
	self.menuRecording = YES;
	[self rebuildMenu];
	[self onHotkeyDown];
}

- (void)menuStopRecord:(id)sender {
	(void)sender;
	self.menuRecording = NO;
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
	/* Не затираем хороший last_take коротким/пустым кликом Fn. */
	if (bytes < 8000) {
		wcLog(@"skip preserve last_take — too small (%llu)", bytes);
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
	[[NSWorkspace sharedWorkspace] openFile:p];
}

- (void)openPrefsFolder:(id)sender {
	(void)sender;
	NSString *dir = [wcPrefsPath() stringByDeletingLastPathComponent];
	[[NSFileManager defaultManager] createDirectoryAtPath:dir withIntermediateDirectories:YES attributes:nil error:nil];
	[[NSWorkspace sharedWorkspace] openFile:dir];
}

- (void)quit:(id)sender {
	(void)sender;
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

- (void)applicationDidFinishLaunching:(NSNotification *)note {
	(void)note;
	gApp = self;
	self.prefs = [NSMutableDictionary dictionary];
	self.env = [self loadEnv];
	[self reloadPrefs];
	NSString *verPath = [[[NSBundle mainBundle] bundlePath] stringByAppendingPathComponent:@"Contents/Resources/VERSION"];
	self.appVersion = [NSString stringWithContentsOfFile:verPath encoding:NSUTF8StringEncoding error:nil];
	self.appVersion = [self.appVersion stringByTrimmingCharactersInSet:[NSCharacterSet whitespaceAndNewlineCharacterSet]];
	self.statusItem = [[NSStatusBar systemStatusBar] statusItemWithLength:NSVariableStatusItemLength];
	self.statusItem.button.title = @"🎤";
	if (@available(macOS 10.14, *)) {
		[[UNUserNotificationCenter currentNotificationCenter]
		    requestAuthorizationWithOptions:(UNAuthorizationOptionAlert | UNAuthorizationOptionSound)
		                    completionHandler:^(BOOL granted, NSError *err) {
			                    wcLog(@"notification auth granted=%d err=%@", granted, err);
		                    }];
	}
	[self rebuildMenu];
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
	wcLog(@"started v=%@ build=%@ server=%@ backend=%@ proxy=%d input_trusted=%d", self.appVersion,
	      [[NSBundle mainBundle] objectForInfoDictionaryKey:@"CFBundleVersion"] ?: @"?", wcServerURL(self.prefs),
	      wcBackend(self.prefs, self.env), wcGroqProxyEnabled(self.prefs, self.env), AXIsProcessTrusted());
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
	/* Write WAV directly — avoids main-thread afconvert freezes on long takes. */
	NSString *tmp = [NSTemporaryDirectory() stringByAppendingPathComponent:
	                 [NSString stringWithFormat:@"whisper_%@.wav", [[NSUUID UUID] UUIDString]]];
	[[NSFileManager defaultManager] removeItemAtPath:tmp error:nil];

	AVAudioEngine *engine = [[AVAudioEngine alloc] init];
	AVAudioInputNode *input = engine.inputNode;
	AVAudioFormat *inFmt = [input outputFormatForBus:0];
	if (inFmt.sampleRate < 1000 || inFmt.channelCount < 1) {
		wcLog(@"bad input format sr=%f ch=%u", inFmt.sampleRate, inFmt.channelCount);
		[self userNotify:@"Whisper" body:@"Микрофон недоступен — проверь устройство ввода."];
		return;
	}
	NSDictionary *wavSettings = @{
		AVFormatIDKey : @(kAudioFormatLinearPCM),
		AVSampleRateKey : @(inFmt.sampleRate),
		AVNumberOfChannelsKey : @(1),
		AVLinearPCMBitDepthKey : @16,
		AVLinearPCMIsFloatKey : @NO,
		AVLinearPCMIsBigEndianKey : @NO,
		AVLinearPCMIsNonInterleaved : @NO
	};
	NSError *err = nil;
	AVAudioFile *file = [[AVAudioFile alloc] initForWriting:[NSURL fileURLWithPath:tmp] settings:wavSettings error:&err];
	if (!file || err) {
		wcLog(@"audio file fail: %@", err);
		[self userNotify:@"Whisper" body:@"Не удалось начать запись — проверь микрофон."];
		self.menuRecording = NO;
		[self rebuildMenu];
		return;
	}
	AVAudioFormat *outFmt = file.processingFormat;
	BOOL sameFmt = (fabs(inFmt.sampleRate - outFmt.sampleRate) < 0.5) && (inFmt.channelCount == outFmt.channelCount) &&
	               (inFmt.commonFormat == outFmt.commonFormat);
	AVAudioConverter *converter = nil;
	if (!sameFmt) {
		converter = [[AVAudioConverter alloc] initFromFormat:inFmt toFormat:outFmt];
		if (!converter) {
			wcLog(@"AVAudioConverter init failed in=%@ out=%@", inFmt, outFmt);
			[self userNotify:@"Whisper" body:@"Не удалось настроить запись микрофона."];
			return;
		}
	}
	/* Pre-size one reusable PCM buffer — never alloc on the realtime tap thread. */
	AVAudioFrameCount reuseCap = 8192;
	AVAudioPCMBuffer *reuseBuf =
	    sameFmt ? nil : [[AVAudioPCMBuffer alloc] initWithPCMFormat:outFmt frameCapacity:reuseCap];
	__block AVAudioConverter *convRef = converter;
	__block AVAudioPCMBuffer *bufRef = reuseBuf;
	__block AVAudioFrameCount bufCap = reuseCap;
	[input installTapOnBus:0 bufferSize:4096 format:inFmt block:^(AVAudioPCMBuffer *buffer, AVAudioTime *when) {
		(void)when;
		if (!buffer.frameLength) return;
		NSError *werr = nil;
		if (!convRef) {
			[file writeFromBuffer:buffer error:&werr];
			if (werr) wcLog(@"audio write err: %@", werr);
			return;
		}
		AVAudioFrameCount need =
		    (AVAudioFrameCount)ceil((double)buffer.frameLength * outFmt.sampleRate / inFmt.sampleRate) + 32;
		if (!bufRef || need > bufCap) {
			/* Rare resize only — prefer reuse. */
			bufCap = MAX(need, bufCap * 2);
			bufRef = [[AVAudioPCMBuffer alloc] initWithPCMFormat:outFmt frameCapacity:bufCap];
			if (!bufRef) return;
		}
		bufRef.frameLength = 0;
		NSError *cerr = nil;
		__block BOOL provided = NO;
		AVAudioConverterInputBlock inBlock =
		    ^AVAudioBuffer *(AVAudioPacketCount inNumberOfPackets, AVAudioConverterInputStatus *outStatus) {
			    (void)inNumberOfPackets;
			    if (provided) {
				    *outStatus = AVAudioConverterInputStatus_NoDataNow;
				    return nil;
			    }
			    provided = YES;
			    *outStatus = AVAudioConverterInputStatus_HaveData;
			    return buffer;
		    };
		AVAudioConverterOutputStatus st = [convRef convertToBuffer:bufRef error:&cerr withInputFromBlock:inBlock];
		if (cerr) {
			wcLog(@"audio convert err: %@", cerr);
			return;
		}
		if (st == AVAudioConverterOutputStatus_Error || bufRef.frameLength == 0) return;
		[file writeFromBuffer:bufRef error:&werr];
		if (werr) wcLog(@"audio write err: %@", werr);
	}];
	[engine prepare];
	if (![engine startAndReturnError:&err]) {
		wcLog(@"engine start fail: %@", err);
		[input removeTapOnBus:0];
		[self userNotify:@"Whisper" body:[NSString stringWithFormat:@"Запись: %@", err.localizedDescription ?: @"ошибка"]];
		self.menuRecording = NO;
		[self rebuildMenu];
		return;
	}
	self.audioEngine = engine;
	self.audioFile = file;
	self.wavPath = tmp;
	self.recording = YES;
	self.menuRecording = YES;
	self.statusItem.button.title = @"🔴";
	double maxS = wcMaxRecordSeconds(self.prefs);
	[self.maxRecordTimer invalidate];
	self.maxRecordTimer = [NSTimer scheduledTimerWithTimeInterval:maxS repeats:NO block:^(NSTimer *t) {
		(void)t;
		wcLog(@"max record %.0fs reached — auto stop", maxS);
		[gApp onHotkeyUp];
	}];
	wcLog(@"recording engine %@ sr=%.0f→%.0f ch=%u max=%.0fs", tmp, inFmt.sampleRate, outFmt.sampleRate,
	      outFmt.channelCount, maxS);
}

- (NSString *)convertRecordingToWav:(NSString *)src {
	/* Prefer already-WAV path (new recorder). Never NSTask/afconvert in MAS sandbox. */
	if ([src.pathExtension.lowercaseString isEqualToString:@"wav"]) return src;
	wcLog(@"non-wav recording %@ — send as-is (no afconvert in sandbox)", src);
	return src;
}

- (void)onHotkeyUp {
	if (!self.recording) return;
	[self.maxRecordTimer invalidate];
	self.maxRecordTimer = nil;
	self.recording = NO;
	self.menuRecording = NO;
	self.statusItem.button.title = @"⏳";
	AVAudioEngine *engine = self.audioEngine;
	NSString *path = self.wavPath;
	self.audioEngine = nil;
	self.wavPath = nil;
	if (engine) {
		@try {
			[engine.inputNode removeTapOnBus:0];
		} @catch (NSException *ex) {
			wcLog(@"removeTap exception: %@", ex);
		}
		@try {
			[engine stop];
		} @catch (NSException *ex) {
			wcLog(@"engine stop exception: %@", ex);
		}
	}
	/* Close WAV after tap is gone so the file is finalized. */
	self.audioFile = nil;
	self.processing = YES;
	[self rebuildMenu];
	if (!path.length) {
		self.processing = NO;
		self.statusItem.button.title = @"🎤";
		[self rebuildMenu];
		return;
	}
	NSUInteger bytes = [[[NSFileManager defaultManager] attributesOfItemAtPath:path error:nil] fileSize];
	wcLog(@"stopped recording %@ bytes=%lu", path, (unsigned long)bytes);
	if (bytes < 800) {
		[[NSFileManager defaultManager] removeItemAtPath:path error:nil];
		self.processing = NO;
		self.statusItem.button.title = @"🎤";
		[self rebuildMenu];
		[self userNotify:@"Whisper" body:@"Запись пустая — удерживай Fn дольше и проверь микрофон."];
		return;
	}
	[self userNotify:@"Whisper" body:@"Отправляю на сервер…"];
	dispatch_async(dispatch_get_global_queue(QOS_CLASS_USER_INITIATED, 0), ^{
		@try {
			NSString *wav = [self convertRecordingToWav:path];
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
	/* Layero edge ~60–90s; Railway+Groq can need longer for big takes. */
	NSTimeInterval hardWait = proxy.length ? 90.0 : 180.0;
	req.timeoutInterval = hardWait;
	if (key.length) [req setValue:[NSString stringWithFormat:@"Bearer %@", key] forHTTPHeaderField:@"Authorization"];
	NSString *secret = wcGroqProxySecret(self.prefs, self.env);
	if (proxy.length && secret.length)
		[req setValue:secret forHTTPHeaderField:@"X-Whisper-Groq-Proxy-Secret"];
	NSString *boundary = [[NSUUID UUID] UUIDString];
	[req setValue:[NSString stringWithFormat:@"multipart/form-data; boundary=%@", boundary] forHTTPHeaderField:@"Content-Type"];
	req.HTTPBody = [self multipartBody:boundary fields:@{@"model" : kGroqModel, @"response_format" : @"json"} fileField:@"file"
	                           fileName:@"audio.wav" fileData:wav mime:@"audio/wav"];
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
		                   (code == 404) || (code == 405) || (code == 502) || (code == 503) || (code == 504);
		NSString *msg = firstErr.localizedDescription.lowercaseString ?: @"";
		if ([msg containsString:@"methodnotallowed"] || [msg containsString:@"адрес свободен"]) retryWorthy = YES;
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
	NSString *mode = wcBackend(self.prefs, self.env);
	NSDictionary *result = nil;
	NSError *lastErr = nil;
	NSString *usedRoute = nil;
	for (NSString *route in wcBackendOrder(mode)) {
		usedRoute = route;
		wcLog(@"transcribe try route=%@", route);
		@try {
			result = [route isEqualToString:@"server"] ? [self transcribeServer:wavPath error:&lastErr]
			                                           : [self transcribeGroq:wavPath error:&lastErr];
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
	wcLog(@"text len=%lu route=%@", (unsigned long)text.length, usedRoute);
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

@end

int main(int argc, const char *argv[]) {
	(void)argc;
	(void)argv;
	@autoreleasepool {
		NSApplication *app = [NSApplication sharedApplication];
		[app setActivationPolicy:NSApplicationActivationPolicyAccessory];
		WCAppDelegate *delegate = [[WCAppDelegate alloc] init];
		app.delegate = delegate;
		[app run];
	}
	return 0;
}
