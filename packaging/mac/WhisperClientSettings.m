/* Настройки WhisperClient — отдельное окно. */
#import <Cocoa/Cocoa.h>
#import "whisper_client_api.h"

@interface WCAppDelegate : NSObject
@property(nonatomic, strong) NSMutableDictionary *prefs;
@property(nonatomic, strong) NSDictionary *env;
- (void)reloadPrefs;
- (void)savePrefs;
- (void)rebuildMenu;
- (void)userNotify:(NSString *)title body:(NSString *)body;
@end

@interface WCSettingsPanel : NSWindowController <NSWindowDelegate>
@property(nonatomic, weak) WCAppDelegate *app;
@property(nonatomic, strong) NSTextField *hostField;
@property(nonatomic, strong) NSTextField *portField;
@property(nonatomic, strong) NSTextField *urlField;
@property(nonatomic, strong) NSPopUpButton *backendPopup;
@property(nonatomic, strong) NSPopUpButton *pastePopup;
@property(nonatomic, strong) NSTextField *groqField;
@property(nonatomic, strong) NSTextField *statusLabel;
- (NSMutableDictionary *)prefsFromForm;
@end

static WCSettingsPanel *WCSettingsShared = nil;

static NSTextField *wcMakeTextField(NSRect frame) {
	NSTextField *f = [[NSTextField alloc] initWithFrame:frame];
	f.bezeled = YES;
	f.bordered = YES;
	f.drawsBackground = YES;
	f.editable = YES;
	f.selectable = YES;
	return f;
}

static void WCInstallEditMenu(void) {
	if ([NSApp mainMenu]) return;
	NSMenu *mainMenu = [[NSMenu alloc] initWithTitle:@"Main"];
	NSMenuItem *appItem = [[NSMenuItem alloc] init];
	[mainMenu addItem:appItem];
	NSMenu *appMenu = [[NSMenu alloc] initWithTitle:@"WhisperClient"];
	[appMenu addItemWithTitle:@"Выход" action:@selector(terminate:) keyEquivalent:@"q"];
	appItem.submenu = appMenu;

	NSMenuItem *editItem = [[NSMenuItem alloc] initWithTitle:@"Правка" action:NULL keyEquivalent:@""];
	NSMenu *editMenu = [[NSMenu alloc] initWithTitle:@"Edit"];
	[editMenu addItemWithTitle:@"Вырезать" action:@selector(cut:) keyEquivalent:@"x"];
	[editMenu addItemWithTitle:@"Копировать" action:@selector(copy:) keyEquivalent:@"c"];
	[editMenu addItemWithTitle:@"Вставить" action:@selector(paste:) keyEquivalent:@"v"];
	[editMenu addItemWithTitle:@"Выделить всё" action:@selector(selectAll:) keyEquivalent:@"a"];
	editItem.submenu = editMenu;
	[mainMenu addItem:editItem];
	[NSApp setMainMenu:mainMenu];
}

@implementation WCSettingsPanel

- (instancetype)initWithApp:(WCAppDelegate *)app {
	self = [super initWithWindow:nil];
	if (!self) return nil;
	_app = app;
	NSRect frame = NSMakeRect(0, 0, 520, 460);
	NSWindow *w = [[NSWindow alloc] initWithContentRect:frame
	                                          styleMask:(NSWindowStyleMaskTitled | NSWindowStyleMaskClosable)
	                                            backing:NSBackingStoreBuffered defer:NO];
	w.title = @"WhisperClient — Настройки";
	w.releasedWhenClosed = NO;
	self.window = w;
	w.delegate = self;

	NSView *cv = w.contentView;
	CGFloat y = 400;

	NSTextField *hdr = [NSTextField labelWithString:@"Сервер"];
	hdr.font = [NSFont boldSystemFontOfSize:13];
	hdr.frame = NSMakeRect(20, y, 200, 20);
	[cv addSubview:hdr];
	y -= 30;

	_hostField = wcMakeTextField(NSMakeRect(150, y, 340, 24));
	NSTextField *hL = [NSTextField labelWithString:@"IP / host:"];
	hL.frame = NSMakeRect(20, y + 2, 120, 20);
	[cv addSubview:hL];
	[cv addSubview:_hostField];
	y -= 34;

	_portField = wcMakeTextField(NSMakeRect(150, y, 100, 24));
	NSTextField *pL = [NSTextField labelWithString:@"Порт:"];
	pL.frame = NSMakeRect(20, y + 2, 120, 20);
	[cv addSubview:pL];
	[cv addSubview:_portField];
	y -= 34;

	_urlField = wcMakeTextField(NSMakeRect(150, y, 340, 24));
	NSTextField *uL = [NSTextField labelWithString:@"Полный URL:"];
	uL.frame = NSMakeRect(20, y + 2, 120, 20);
	[cv addSubview:uL];
	[cv addSubview:_urlField];
	y -= 44;

	_backendPopup = [[NSPopUpButton alloc] initWithFrame:NSMakeRect(150, y, 340, 26) pullsDown:NO];
	[_backendPopup addItemsWithTitles:@[ @"Только мой сервер", @"Только Groq", @"Сервер → Groq", @"Groq → сервер" ]];
	NSTextField *bL = [NSTextField labelWithString:@"Транскрипция:"];
	bL.frame = NSMakeRect(20, y + 2, 120, 20);
	[cv addSubview:bL];
	[cv addSubview:_backendPopup];
	y -= 40;

	_pastePopup = [[NSPopUpButton alloc] initWithFrame:NSMakeRect(150, y, 340, 26) pullsDown:NO];
	[_pastePopup addItemsWithTitles:@[ @"В поле + буфер", @"Только буфер", @"Только история" ]];
	NSTextField *ptL = [NSTextField labelWithString:@"Режим текста:"];
	ptL.frame = NSMakeRect(20, y + 2, 120, 20);
	[cv addSubview:ptL];
	[cv addSubview:_pastePopup];
	y -= 40;

	_groqField = wcMakeTextField(NSMakeRect(150, y, 340, 24));
	_groqField.placeholderString = @"gsk_… (⌘V вставить)";
	NSTextField *gL = [NSTextField labelWithString:@"Groq API ключ:"];
	gL.frame = NSMakeRect(20, y + 2, 120, 20);
	[cv addSubview:gL];
	[cv addSubview:_groqField];
	y -= 50;

	NSButton *testBtn = [NSButton buttonWithTitle:@"Проверить связь" target:self action:@selector(testConnection:)];
	testBtn.frame = NSMakeRect(20, y, 150, 32);
	[cv addSubview:testBtn];
	NSButton *saveBtn = [NSButton buttonWithTitle:@"Сохранить" target:self action:@selector(save:)];
	saveBtn.frame = NSMakeRect(190, y, 120, 32);
	saveBtn.bezelStyle = NSBezelStyleRounded;
	[cv addSubview:saveBtn];
	y -= 44;

	_statusLabel = [NSTextField labelWithString:@""];
	_statusLabel.frame = NSMakeRect(20, 20, 470, 50);
	_statusLabel.maximumNumberOfLines = 4;
	_statusLabel.textColor = [NSColor secondaryLabelColor];
	[cv addSubview:_statusLabel];

	[self reloadFields];
	[w center];
	return self;
}

- (void)reloadFields {
	[_app reloadPrefs];
	NSDictionary *p = _app.prefs;
	NSString *su = p[@"server_url"];
	_urlField.stringValue = ([su isKindOfClass:[NSString class]] ? su : @"");
	NSString *host = [p[@"server_host"] isKindOfClass:[NSString class]] ? p[@"server_host"] : @"";
	if (!host.length) host = @"100.115.68.2";
	_hostField.stringValue = host;
	NSInteger port = 8001;
	id sp = p[@"server_port"];
	if ([sp respondsToSelector:@selector(integerValue)] && [sp integerValue] > 0) port = [sp integerValue];
	_portField.stringValue = [NSString stringWithFormat:@"%ld", (long)port];
	NSString *bk = wcBackend(p, _app.env);
	NSDictionary *bm = @{ @"server" : @0, @"groq" : @1, @"server_then_groq" : @2, @"groq_then_server" : @3 };
	NSNumber *bidx = bm[bk];
	[_backendPopup selectItemAtIndex:bidx ? bidx.integerValue : 2];
	NSString *pm = wcPasteMode(p);
	NSDictionary *pmM = @{ @"auto" : @0, @"clipboard" : @1, @"history_only" : @2 };
	NSNumber *pidx = pmM[pm];
	[_pastePopup selectItemAtIndex:pidx ? pidx.integerValue : 0];
	NSString *gk = p[@"groq_api_key"];
	_groqField.stringValue = [gk isKindOfClass:[NSString class]] ? gk : @"";
	_statusLabel.stringValue = [NSString stringWithFormat:@"Сейчас: %@ · %@ · прокси %@", wcBackendLabel(bk), wcServerURL(p),
	                                                      (wcGroqProxyEnabled(p, self.app.env) ? @"ON" : @"OFF")];
}

- (void)save:(id)sender {
	(void)sender;
	NSMutableDictionary *p = [self prefsFromForm];
	NSString *gk = p[@"groq_api_key"];
	if ([gk isKindOfClass:[NSString class]] && [gk containsString:@"⌘V"]) {
		[p removeObjectForKey:@"groq_api_key"];
	}
	_app.prefs = p;
	[_app savePrefs];
	[_app rebuildMenu];
	_statusLabel.stringValue = @"✓ Сохранено";
	[_app userNotify:@"Whisper" body:[NSString stringWithFormat:@"Сохранено: %@, сервер %@", wcBackendLabel(p[@"transcribe_backend"]), wcServerURL(p)]];
}

- (NSMutableDictionary *)prefsFromForm {
	NSMutableDictionary *p = [_app.prefs mutableCopy] ?: [NSMutableDictionary dictionary];
	NSString *url = [_urlField.stringValue stringByTrimmingCharactersInSet:[NSCharacterSet whitespaceCharacterSet]];
	if (url.length) {
		p[@"server_url"] = url;
		[p removeObjectForKey:@"server_host"];
		[p removeObjectForKey:@"server_port"];
	} else {
		[p removeObjectForKey:@"server_url"];
		NSString *host = [_hostField.stringValue stringByTrimmingCharactersInSet:[NSCharacterSet whitespaceCharacterSet]];
		if (!host.length) host = @"100.115.68.2";
		NSInteger port = [_portField.stringValue integerValue];
		if (port <= 0) port = 8001;
		p[@"server_host"] = host;
		p[@"server_port"] = @(port);
	}
	NSArray *bk = @[ @"server", @"groq", @"server_then_groq", @"groq_then_server" ];
	NSArray *pm = @[ @"auto", @"clipboard", @"history_only" ];
	p[@"transcribe_backend"] = bk[[_backendPopup indexOfSelectedItem]];
	p[@"paste_mode"] = pm[[_pastePopup indexOfSelectedItem]];
	NSString *gk = [_groqField.stringValue stringByTrimmingCharactersInSet:[NSCharacterSet whitespaceCharacterSet]];
	if (gk.length) p[@"groq_api_key"] = gk;
	else [p removeObjectForKey:@"groq_api_key"];
	return p;
}

static void wcHttpProbe(NSString *urlStr, void (^done)(NSInteger code, NSError *err)) {
	NSInteger code = -1;
	NSError *err = nil;
	NSData *body = nil;
	if (!wcHttpRequest(@"GET", urlStr, nil, nil, 15, &code, &body, &err)) {
		done(-1, err);
		return;
	}
	(void)body;
	done(code, nil);
}

- (void)testConnection:(id)sender {
	(void)sender;
	_statusLabel.stringValue = @"Проверяю связь…";
	NSMutableDictionary *formPrefs = [self prefsFromForm];
	_app.prefs = formPrefs;
	[_app savePrefs];
	[_app rebuildMenu];
	NSString *backend = wcBackend(formPrefs, _app.env);
	BOOL testServer = ![backend isEqualToString:@"groq"];
	BOOL testGroq = ![backend isEqualToString:@"server"];
	NSString *base = wcServerURL(formPrefs);
	NSString *groqKey = formPrefs[@"groq_api_key"];
	if ([groqKey isKindOfClass:[NSString class]] && ![(NSString *)groqKey length]) groqKey = nil;
	if (!groqKey.length) {
		NSString *ek = _app.env[@"GROQ_API_KEY"] ?: _app.env[@"WHISPER_GROQ_API_KEY"];
		if ([ek isKindOfClass:[NSString class]] && ek.length) groqKey = ek;
	}
	dispatch_async(dispatch_get_global_queue(QOS_CLASS_USER_INITIATED, 0), ^{
		NSMutableArray<NSString *> *lines = [NSMutableArray array];
		BOOL allOk = YES;
		if (testServer) {
			__block NSInteger code = -1;
			__block NSError *err = nil;
			wcHttpProbe([NSString stringWithFormat:@"%@/", base], ^(NSInteger c, NSError *e) {
				code = c;
				err = e;
			});
			if (code >= 200 && code < 500) {
				[lines addObject:[NSString stringWithFormat:@"✓ Сервер %@ (HTTP %ld)", base, (long)code]];
			} else if (err) {
				allOk = NO;
				[lines addObject:[NSString stringWithFormat:@"✗ Сервер: %@", err.localizedDescription]];
			} else {
				allOk = NO;
				[lines addObject:[NSString stringWithFormat:@"✗ Сервер: нет ответа (код %ld)", (long)code]];
			}
		}
		if (testGroq) {
			BOOL proxyOn = wcGroqProxyEnabled(formPrefs, self.app.env);
			NSString *proxyBase = wcGroqProxyURL(formPrefs, self.app.env);
			if (proxyOn && proxyBase.length) {
				__block NSInteger pcode = -1;
				__block NSError *perr = nil;
				__block NSData *pbody = nil;
				NSInteger codeTmp = -1;
				NSError *errTmp = nil;
				NSData *bodyTmp = nil;
				if (!wcHttpRequest(@"GET", [NSString stringWithFormat:@"%@/", proxyBase], nil, nil, 15, &codeTmp, &bodyTmp,
				                   &errTmp)) {
					pcode = -1;
					perr = errTmp;
				} else {
					pcode = codeTmp;
					pbody = bodyTmp;
				}
				NSInteger hcode = -1;
				NSError *herr = nil;
				NSData *hbody = nil;
				wcHttpRequest(@"GET", [NSString stringWithFormat:@"%@/__rf_mirror_health", proxyBase], nil, nil, 15, &hcode,
				              &hbody, &herr);
				(void)herr;
				BOOL proxyOk = (pcode >= 200 && pcode < 300);
				if (proxyOk) {
					[lines addObject:[NSString stringWithFormat:@"✓ Groq-прокси %@ (HTTP %ld)%@", proxyBase, (long)pcode,
					                                            (hcode == 200 ? @" · Layero OK" : @"")]];
				} else if (perr) {
					allOk = NO;
					[lines addObject:[NSString stringWithFormat:@"✗ Прокси %@: %@", proxyBase, perr.localizedDescription]];
				} else {
					allOk = NO;
					[lines addObject:[NSString stringWithFormat:@"✗ Прокси %@: HTTP %ld (нужен 2xx, не 404)", proxyBase,
					                                            (long)pcode]];
				}
				(void)pbody;
				if (hcode > 0 && hcode != 200) {
					[lines addObject:[NSString stringWithFormat:@"· mirror health HTTP %ld", (long)hcode]];
				}
				if (!groqKey.length) {
					[lines addObject:@"· Ключ Groq на клиенте не задан — прокси может подставить свой"];
				}
			} else if (!groqKey.length) {
				allOk = NO;
				[lines addObject:@"✗ Groq: ключ не задан (прокси выключен)"];
			} else {
				NSMutableURLRequest *req =
				    [NSMutableURLRequest requestWithURL:[NSURL URLWithString:@"https://api.groq.com/openai/v1/models"]];
				req.timeoutInterval = 15;
				[req setValue:[NSString stringWithFormat:@"Bearer %@", groqKey] forHTTPHeaderField:@"Authorization"];
				dispatch_semaphore_t sem = dispatch_semaphore_create(0);
				__block NSInteger code = -1;
				__block NSError *err = nil;
				[[[NSURLSession sharedSession] dataTaskWithRequest:req
				                                 completionHandler:^(NSData *d, NSURLResponse *r, NSError *e) {
					                                 (void)d;
					                                 err = e;
					                                 if ([r isKindOfClass:[NSHTTPURLResponse class]])
						                                 code = [(NSHTTPURLResponse *)r statusCode];
					                                 dispatch_semaphore_signal(sem);
				                                 }] resume];
				dispatch_semaphore_wait(sem, dispatch_time(DISPATCH_TIME_NOW, (int64_t)(20 * NSEC_PER_SEC)));
				if (code == 200) {
					[lines addObject:@"✓ Groq API напрямую (ключ OK)"];
				} else if (code == 401 || code == 403) {
					allOk = NO;
					[lines addObject:[NSString stringWithFormat:@"✗ Groq: ключ отклонён (HTTP %ld)", (long)code]];
				} else if (err) {
					allOk = NO;
					[lines addObject:[NSString stringWithFormat:@"✗ Groq: %@", err.localizedDescription]];
				} else {
					allOk = NO;
					[lines addObject:[NSString stringWithFormat:@"✗ Groq: HTTP %ld", (long)code]];
				}
			}
		}
		NSString *summary = [lines componentsJoinedByString:@"\n"];
		dispatch_async(dispatch_get_main_queue(), ^{
			NSAlert *alert = [[NSAlert alloc] init];
			self.statusLabel.stringValue = summary;
			if (allOk) {
				alert.messageText = @"Связь OK";
				alert.informativeText = summary;
				[self.app userNotify:@"Whisper — связь OK" body:summary];
			} else {
				alert.messageText = @"Ошибка связи";
				alert.informativeText = summary;
				[self.app userNotify:@"Whisper — ошибка" body:summary];
			}
			[alert runModal];
		});
	});
}

- (void)windowWillClose:(NSNotification *)notification {
	(void)notification;
	[_app rebuildMenu];
}

@end

void WCShowSettingsPanel(WCAppDelegate *app) {
	WCInstallEditMenu();
	[NSApp activateIgnoringOtherApps:YES];
	if (!WCSettingsShared) WCSettingsShared = [[WCSettingsPanel alloc] initWithApp:app];
	[WCSettingsShared reloadFields];
	[WCSettingsShared showWindow:nil];
	[WCSettingsShared.window makeKeyAndOrderFront:nil];
}
