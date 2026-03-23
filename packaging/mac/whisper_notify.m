/*
 * Уведомление из бандла WhisperClient.app (не «Python» в шторке).
 * Вход: stdin, UTF-8 — первая строка = title, остальное = текст.
 *
 * NSUserNotificationCenter устарел и на новых macOS часто не показывает баннеры;
 * используем UserNotifications (UNUserNotificationCenter), с запасным путём и кодом
 * выхода для fallback в Python (osascript).
 *
 * clang -O2 -framework Cocoa -framework UserNotifications -o whisper_notify whisper_notify.m
 */
#import <Cocoa/Cocoa.h>
#import <UserNotifications/UserNotifications.h>
#import <unistd.h>

static NSString *readStdinUTF8(void) {
	NSMutableData *data = [NSMutableData data];
	char buf[4096];
	ssize_t n;
	while ((n = read(STDIN_FILENO, buf, sizeof(buf))) > 0) {
		[data appendBytes:buf length:(NSUInteger)n];
	}
	NSString *raw = [[NSString alloc] initWithData:data encoding:NSUTF8StringEncoding];
	return raw ?: @"";
}

static void parseTitleBody(NSString *raw, NSString **outTitle, NSString **outBody) {
	NSRange nl = [raw rangeOfString:@"\n"];
	if (nl.location != NSNotFound) {
		*outTitle = [[raw substringToIndex:nl.location]
		    stringByTrimmingCharactersInSet:[NSCharacterSet whitespaceAndNewlineCharacterSet]];
		*outBody = [[raw substringFromIndex:(nl.location + nl.length)]
		    stringByTrimmingCharactersInSet:[NSCharacterSet whitespaceAndNewlineCharacterSet]];
	} else {
		*outTitle = [raw stringByTrimmingCharactersInSet:[NSCharacterSet whitespaceAndNewlineCharacterSet]];
		*outBody = @"";
	}
	if ([*outTitle length] == 0) {
		*outTitle = @"Whisper Client";
	}
}

static void deliverDeprecatedBanner(NSString *title, NSString *body) {
#pragma clang diagnostic push
#pragma clang diagnostic ignored "-Wdeprecated-declarations"
	NSUserNotification *note = [[NSUserNotification alloc] init];
	note.title = title;
	note.informativeText = body;
	[[NSUserNotificationCenter defaultUserNotificationCenter] deliverNotification:note];
#pragma clang diagnostic pop
}

/*
 * 0 = запрос уведомлений поставлен в очередь (или доставлен)
 * 1 = не удалось (Python вызовет osascript display notification)
 */
static int deliverUserNotifications(NSString *title, NSString *body) {
	__block int result = 1;
	dispatch_semaphore_t sem = dispatch_semaphore_create(0);
	UNUserNotificationCenter *center = [UNUserNotificationCenter currentNotificationCenter];
	[center requestAuthorizationWithOptions:(UNAuthorizationOptionAlert | UNAuthorizationOptionSound)
	                          completionHandler:^(BOOL granted, NSError *err) {
		                          if (!granted) {
			                          (void)err;
			                          dispatch_semaphore_signal(sem);
			                          return;
		                          }
		                          UNMutableNotificationContent *c = [[UNMutableNotificationContent alloc] init];
		                          c.title = title;
		                          c.body = body;
		                          UNTimeIntervalNotificationTrigger *tr =
		                              [UNTimeIntervalNotificationTrigger triggerWithTimeInterval:0.02
		                                                                                  repeats:NO];
		                          NSString *nid = [[NSUUID UUID] UUIDString];
		                          UNNotificationRequest *req =
		                              [UNNotificationRequest requestWithIdentifier:nid content:c trigger:tr];
		                          [center addNotificationRequest:req
		                                   withCompletionHandler:^(NSError *e2) {
			                                   if (e2 == nil) {
				                                   result = 0;
			                                   }
			                                   dispatch_semaphore_signal(sem);
		                                   }];
	                          }];
	dispatch_semaphore_wait(sem, DISPATCH_TIME_FOREVER);
	return result;
}

int main(int argc, char *argv[]) {
	(void)argc;
	(void)argv;
	@autoreleasepool {
		/* Без NSApplication UN/TCC на части систем ведут себя как «в фоне» и дают exit=1. */
		[NSApplication sharedApplication];
		NSString *raw = readStdinUTF8();
		NSString *title;
		NSString *body;
		parseTitleBody(raw, &title, &body);

		int exitCode;
		if (@available(macOS 10.14, *)) {
			int un = deliverUserNotifications(title, body);
			if (un == 0) {
				exitCode = 0;
			} else {
				/*
				 * Не вызывать deliverDeprecatedBanner: на новых macOS он иногда всё же
				 * показывает баннер, а Python затем делает osascript — два уведомления
				 * с одним текстом (иконка «скрипт» + иконка приложения).
				 */
				exitCode = 1;
			}
		} else {
			deliverDeprecatedBanner(title, body);
			exitCode = 0;
		}

		NSRunLoop *rl = [NSRunLoop currentRunLoop];
		[rl runUntilDate:[NSDate dateWithTimeIntervalSinceNow:0.6]];
		return exitCode;
	}
}
