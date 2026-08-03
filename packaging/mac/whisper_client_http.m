/* HTTP: NSURLSession (если ATS разрешает) + BSD-сокет как fallback для http:// */
#import <Foundation/Foundation.h>
#import "whisper_client_api.h"
#include <sys/select.h>
#include <sys/socket.h>
#include <netinet/in.h>
#include <arpa/inet.h>
#include <netdb.h>
#include <unistd.h>
#include <errno.h>
#include <string.h>

static BOOL wcIsIPv4Host(NSString *host) {
	NSArray *parts = [host componentsSeparatedByString:@"."];
	if (parts.count != 4) return NO;
	for (NSString *p in parts) {
		if (!p.length) return NO;
		NSInteger v = p.integerValue;
		if (v < 0 || v > 255) return NO;
	}
	return YES;
}

static BOOL wcHttpViaURLSession(NSString *method, NSURL *url, NSData *body, NSDictionary *headers,
                                NSTimeInterval timeout, NSInteger *outStatus, NSData **outBody, NSError **outErr) {
	NSMutableURLRequest *req = [NSMutableURLRequest requestWithURL:url];
	req.HTTPMethod = method.uppercaseString;
	req.timeoutInterval = timeout;
	for (NSString *k in headers) [req setValue:headers[k] forHTTPHeaderField:k];
	if (body.length) req.HTTPBody = body;
	dispatch_semaphore_t sem = dispatch_semaphore_create(0);
	__block NSInteger code = -1;
	__block NSData *respBody = nil;
	__block NSError *err = nil;
	[[[NSURLSession sharedSession] dataTaskWithRequest:req completionHandler:^(NSData *d, NSURLResponse *r, NSError *e) {
		err = e;
		if ([r isKindOfClass:[NSHTTPURLResponse class]]) code = [(NSHTTPURLResponse *)r statusCode];
		respBody = d;
		dispatch_semaphore_signal(sem);
	}] resume];
	NSTimeInterval waitSec = timeout > 0 ? (timeout + 5.0) : 60.0;
	if (dispatch_semaphore_wait(sem, dispatch_time(DISPATCH_TIME_NOW, (int64_t)(waitSec * NSEC_PER_SEC))) != 0) {
		if (outErr)
			*outErr = [NSError errorWithDomain:@"wc.http" code:-1001
			                          userInfo:@{NSLocalizedDescriptionKey : @"http timeout"}];
		return NO;
	}
	if (err) {
		if (outErr) *outErr = err;
		return NO;
	}
	if (outStatus) *outStatus = code;
	if (outBody) *outBody = respBody ?: [NSData data];
	return YES;
}

static int wcWaitReadable(int sock, NSTimeInterval sec) {
	fd_set fds;
	FD_ZERO(&fds);
	FD_SET(sock, &fds);
	struct timeval tv;
	tv.tv_sec = (time_t)sec;
	tv.tv_usec = (suseconds_t)((sec - (double)tv.tv_sec) * 1000000.0);
	if (tv.tv_sec < 0) {
		tv.tv_sec = 0;
		tv.tv_usec = 0;
	}
	return select(sock + 1, &fds, NULL, NULL, &tv);
}

static NSInteger wcContentLengthFromHeaders(NSString *hdrStr) {
	for (NSString *line in [hdrStr componentsSeparatedByString:@"\r\n"]) {
		NSString *l = line.lowercaseString;
		if ([l hasPrefix:@"content-length:"]) {
			NSString *v = [[line substringFromIndex:15] stringByTrimmingCharactersInSet:[NSCharacterSet whitespaceCharacterSet]];
			return v.integerValue;
		}
	}
	return -1;
}

static BOOL wcHttpViaSocket(NSString *method, NSURL *url, NSData *body, NSDictionary *headers,
                            NSTimeInterval timeout, NSInteger *outStatus, NSData **outBody, NSError **outErr) {
	NSInteger port = url.port ? url.port.integerValue : 80;
	NSString *path = url.path.length ? url.path : @"/";
	if (url.query.length) path = [path stringByAppendingFormat:@"?%@", url.query];

	struct addrinfo hints = {0}, *res = NULL;
	hints.ai_socktype = SOCK_STREAM;
	hints.ai_family = wcIsIPv4Host(url.host) ? AF_INET : AF_UNSPEC;
	char portbuf[16];
	snprintf(portbuf, sizeof(portbuf), "%ld", (long)port);
	int gai = getaddrinfo(url.host.UTF8String, portbuf, &hints, &res);
	if (gai != 0) {
		if (outErr)
			*outErr = [NSError errorWithDomain:@"wc.http" code:3
			                          userInfo:@{NSLocalizedDescriptionKey : @(gai_strerror(gai))}];
		return NO;
	}

	int sock = -1;
	for (struct addrinfo *ai = res; ai; ai = ai->ai_next) {
		sock = socket(ai->ai_family, ai->ai_socktype, ai->ai_protocol);
		if (sock < 0) continue;
		if (connect(sock, ai->ai_addr, ai->ai_addrlen) == 0) break;
		close(sock);
		sock = -1;
	}
	freeaddrinfo(res);
	if (sock < 0) {
		if (outErr)
			*outErr = [NSError errorWithDomain:@"wc.http" code:4
			                          userInfo:@{NSLocalizedDescriptionKey : @"Не удалось подключиться к серверу"}];
		return NO;
	}

	struct timeval tv = {.tv_sec = (time_t)timeout, .tv_usec = 0};
	if (tv.tv_sec < 10) tv.tv_sec = 10;
	setsockopt(sock, SOL_SOCKET, SO_SNDTIMEO, &tv, sizeof(tv));

	NSMutableString *reqHdr = [NSMutableString stringWithFormat:@"%@ %@ HTTP/1.1\r\nHost: %@:%ld\r\nConnection: close\r\n",
	                                                                    method.uppercaseString, path, url.host, (long)port];
	for (NSString *k in headers) [reqHdr appendFormat:@"%@: %@\r\n", k, headers[k]];
	if (body.length) [reqHdr appendFormat:@"Content-Length: %lu\r\n", (unsigned long)body.length];
	[reqHdr appendString:@"\r\n"];

	NSMutableData *req = [[reqHdr dataUsingEncoding:NSUTF8StringEncoding] mutableCopy];
	if (body.length) [req appendData:body];
	const uint8_t *sendp = req.bytes;
	NSInteger left = (NSInteger)req.length;
	while (left > 0) {
		ssize_t n = send(sock, sendp, (size_t)left, 0);
		if (n <= 0) {
			close(sock);
			if (outErr)
				*outErr = [NSError errorWithDomain:@"wc.http" code:5
				                          userInfo:@{NSLocalizedDescriptionKey : @"Ошибка отправки"}];
			return NO;
		}
		sendp += n;
		left -= n;
	}

	NSMutableData *resp = [NSMutableData data];
	uint8_t buf[16384];
	NSTimeInterval deadline = [NSDate timeIntervalSinceReferenceDate] + timeout;
	for (;;) {
		NSTimeInterval rem = deadline - [NSDate timeIntervalSinceReferenceDate];
		if (rem <= 0) break;
		int wr = wcWaitReadable(sock, rem);
		if (wr <= 0) break;
		ssize_t n = recv(sock, buf, sizeof(buf), 0);
		if (n < 0) {
			if (errno == EINTR) continue;
			close(sock);
			if (outErr)
				*outErr = [NSError errorWithDomain:@"wc.http" code:6
				                          userInfo:@{NSLocalizedDescriptionKey : @"Ошибка чтения ответа"}];
			return NO;
		}
		if (n == 0) break;
		[resp appendBytes:buf length:(NSUInteger)n];

		NSData *sep = [@"\r\n\r\n" dataUsingEncoding:NSUTF8StringEncoding];
		NSRange sepR = [resp rangeOfData:sep options:0 range:NSMakeRange(0, resp.length)];
		if (sepR.location != NSNotFound) {
			NSString *hdrStr = [[NSString alloc] initWithData:[resp subdataWithRange:NSMakeRange(0, sepR.location)]
			                                         encoding:NSUTF8StringEncoding];
			NSInteger cl = wcContentLengthFromHeaders(hdrStr ?: @"");
			NSUInteger bodyLen = resp.length - (sepR.location + sepR.length);
			if (cl >= 0 && (NSInteger)bodyLen >= cl) break;
		}
	}
	close(sock);

	if (!resp.length) {
		if (outErr)
			*outErr = [NSError errorWithDomain:@"wc.http" code:7
			                          userInfo:@{NSLocalizedDescriptionKey : @"Пустой ответ сервера — проверь IP/порт и что API запущен"}];
		return NO;
	}

	NSData *sep = [@"\r\n\r\n" dataUsingEncoding:NSUTF8StringEncoding];
	NSRange sepR = [resp rangeOfData:sep options:0 range:NSMakeRange(0, resp.length)];
	if (sepR.location == NSNotFound) {
		if (outErr)
			*outErr = [NSError errorWithDomain:@"wc.http" code:8
			                          userInfo:@{NSLocalizedDescriptionKey : @"Некорректный HTTP-ответ"}];
		return NO;
	}
	NSString *hdrStr = [[NSString alloc] initWithData:[resp subdataWithRange:NSMakeRange(0, sepR.location)]
	                                         encoding:NSUTF8StringEncoding];
	NSInteger status = -1;
	if (hdrStr.length) {
		NSScanner *sc = [NSScanner scannerWithString:hdrStr];
		[sc scanString:@"HTTP/1." intoString:NULL];
		int junk = 0;
		[sc scanInt:&junk];
		int code = 0;
		if ([sc scanInt:&code]) status = code;
	}
	NSUInteger bodyOff = sepR.location + sepR.length;
	NSData *respBody = bodyOff < resp.length ? [resp subdataWithRange:NSMakeRange(bodyOff, resp.length - bodyOff)] : [NSData data];
	wcLog(@"http socket %@ %@ -> status=%ld bytes=%lu", method, url.absoluteString, (long)status, (unsigned long)respBody.length);
	if (outStatus) *outStatus = status;
	if (outBody) *outBody = respBody;
	return status > 0;
}

BOOL wcHttpRequest(NSString *method, NSString *urlString, NSData *body, NSDictionary *headers,
                   NSTimeInterval timeout, NSInteger *outStatus, NSData **outBody, NSError **outErr) {
	if (outStatus) *outStatus = -1;
	if (outBody) *outBody = nil;
	NSURL *url = [NSURL URLWithString:urlString];
	if (!url || !url.host.length) {
		if (outErr)
			*outErr = [NSError errorWithDomain:@"wc.http" code:1
			                          userInfo:@{NSLocalizedDescriptionKey : @"Некорректный URL"}];
		return NO;
	}
	NSMutableDictionary *hdr = [NSMutableDictionary dictionaryWithDictionary:headers ?: @{}];
	if (!hdr[@"User-Agent"]) hdr[@"User-Agent"] = @"WhisperClient/1.3.1";
	if (!hdr[@"X-Whisper-Client"]) hdr[@"X-Whisper-Client"] = @"mac";
	if (!hdr[@"Accept"]) hdr[@"Accept"] = @"*/*";

	NSString *scheme = url.scheme.lowercaseString;
	if ([scheme isEqualToString:@"https"]) {
		return wcHttpViaURLSession(method, url, body, hdr, timeout, outStatus, outBody, outErr);
	}
	if (![scheme isEqualToString:@"http"]) {
		if (outErr)
			*outErr = [NSError errorWithDomain:@"wc.http" code:2
			                          userInfo:@{NSLocalizedDescriptionKey : @"Поддерживаются только http:// и https://"}];
		return NO;
	}

	NSError *sessErr = nil;
	NSInteger code = -1;
	NSData *sessBody = nil;
	if (wcHttpViaURLSession(method, url, body, hdr, timeout, &code, &sessBody, &sessErr)) {
		wcLog(@"http URLSession %@ %@ -> status=%ld", method, urlString, (long)code);
		if (outStatus) *outStatus = code;
		if (outBody) *outBody = sessBody;
		return YES;
	}
	wcLog(@"http URLSession failed (%@), socket fallback for %@", sessErr.localizedDescription, urlString);
	if (wcHttpViaSocket(method, url, body, hdr, timeout, outStatus, outBody, outErr)) return YES;
	if (outErr && !*outErr && sessErr) *outErr = sessErr;
	return NO;
}
