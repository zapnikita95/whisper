/*
 * Короткое уведомление из бандла WhisperClient.app (не «Python» в шторке).
 * Вход: stdin, UTF-8 — первая строка = title, остальное = текст.
 * clang -O2 -framework Cocoa -o whisper_notify whisper_notify.m
 */
#import <Cocoa/Cocoa.h>
#import <unistd.h>

int main(int argc, char *argv[]) {
	(void)argc;
	(void)argv;
	@autoreleasepool {
		NSMutableData *data = [NSMutableData data];
		char buf[4096];
		ssize_t n;
		while ((n = read(STDIN_FILENO, buf, sizeof(buf))) > 0) {
			[data appendBytes:buf length:(NSUInteger)n];
		}

		NSString *raw = [[NSString alloc] initWithData:data encoding:NSUTF8StringEncoding];
		if (raw == nil) {
			raw = @"";
		}
		NSRange nl = [raw rangeOfString:@"\n"];
		NSString *title;
		NSString *body;
		if (nl.location != NSNotFound) {
			title = [[raw substringToIndex:nl.location]
			    stringByTrimmingCharactersInSet:[NSCharacterSet whitespaceAndNewlineCharacterSet]];
			body = [[raw substringFromIndex:(nl.location + nl.length)]
			    stringByTrimmingCharactersInSet:[NSCharacterSet whitespaceAndNewlineCharacterSet]];
		} else {
			title = [raw stringByTrimmingCharactersInSet:[NSCharacterSet whitespaceAndNewlineCharacterSet]];
			body = @"";
		}
		if ([title length] == 0) {
			title = @"Whisper Client";
		}

		[NSApplication sharedApplication];
#pragma clang diagnostic push
#pragma clang diagnostic ignored "-Wdeprecated-declarations"
		NSUserNotification *note = [[NSUserNotification alloc] init];
		note.title = title;
		note.informativeText = body;
		[[NSUserNotificationCenter defaultUserNotificationCenter] deliverNotification:note];
#pragma clang diagnostic pop

		NSRunLoop *rl = [NSRunLoop currentRunLoop];
		[rl runUntilDate:[NSDate dateWithTimeIntervalSinceNow:0.45]];
	}
	return 0;
}
