
(function () {
	LGUtils = {
		macros: {
			latestOpenedWidgetContainer: null,
			cacheDOM: {},
			visitCount: 0,
			getDevice: function() {
				let device;
			    const ua = {
			        "Generic Linux": /Linux/i,
			        "Android": /Android/i,
			        "BlackBerry": /BlackBerry/i,
			        "Bluebird": /EF500/i,
			        "Chrome OS": /CrOS/i,
			        "Datalogic": /DL-AXIS/i,
			        "Honeywell": /CT50/i,
			        "iPad": /iPad/i,
			        "iPhone": /iPhone/i,
			        "iPod": /iPod/i,
			        "macOS": /Macintosh/i,
			        "Windows": /IEMobile|Windows/i,
			        "Zebra": /TC70|TC55/i,
			    }
			    Object.keys(ua).map(v => navigator.userAgent.match(ua[v]) && (device = v));
			    return device;
			},
			getDeviceType: function() {
				const ua = navigator.userAgent;
				if (/(tablet|ipad|playbook|silk)|(android(?!.*mobi))/i.test(ua)) {
					return 'Планшет';
				}
				if (/Mobile|iP(hone|od)|Android|BlackBerry|IEMobile|Kindle|Silk-Accelerated|(hpw|web)OS|Opera M(obi|ini)/.test(ua)) {
					return 'Мобильный телефон';
				}

				return 'Компьютер';
			},
			getBrowserLanguage: function() {
				return navigator.language || navigator.userLanguage; 
			},
			getBrowserOSOld: function() {
				// This script sets OSName variable as follows:
				// "Windows"    for all versions of Windows
				// "MacOS"      for all versions of Macintosh OS
				// "Linux"      for all versions of Linux
				// "UNIX"       for all other UNIX flavors 
				// "Unknown OS" indicates failure to detect the OS
				let OSName;
				if (navigator.appVersion.indexOf("Win") !== -1) OSName = "Windows";
				if (navigator.appVersion.indexOf("Mac") !== -1) OSName = "MacOS";
				if (navigator.appVersion.indexOf("X11") !== -1) OSName = "UNIX";
				if (navigator.appVersion.indexOf("Linux") !== -1) OSName = "Linux";

				return OSName;
			},
			getBrowserOS: function() {
				var userAgent = window.navigator.userAgent,
		        platform = window.navigator.platform,
		        macosPlatforms = ['Macintosh', 'MacIntel', 'MacPPC', 'Mac68K'],
		        windowsPlatforms = ['Win32', 'Win64', 'Windows', 'WinCE'],
		        iosPlatforms = ['iPhone', 'iPad', 'iPod'],
		        os = null;

		    	if (macosPlatforms.indexOf(platform) !== -1) {
		    		os = 'Mac OS';
	    		} else if (iosPlatforms.indexOf(platform) !== -1) {
		    		os = 'iPhone OS';
		    	} else if (windowsPlatforms.indexOf(platform) !== -1) {
		    		os = 'Windows';
		    	} else if (/Android/.test(userAgent)) {
		    		os = 'Android';
		    	} else if (!os && /Linux/.test(platform)) {
		    		os = 'Linux';
		    	}

		  		return os;
			},
			getBrowser: function() {
				const userAgent = navigator.userAgent;
				
				if (userAgent.match(/chrome|chromium|crios/i)) {
					return "Chrome";
				} else if (userAgent.match(/firefox|fxios/i)) {
					return "Firefox";
				} else if (userAgent.match(/safari/i)) {
				    return "Safari";
				} else if (userAgent.match(/opr\//i)) {
				   return "Opera";
				} else if(userAgent.match(/edg/i)) {
				   return "Edge";
				} else {
				   return null;
				}
			},
			getBrowserTimezone: function() {
				const offset = new Date().getTimezoneOffset(), o = Math.abs(offset);
	    		return 'UTC' + (offset < 0 ? "+" : "-") + ("00" + Math.floor(o / 60)).slice(-2) + ":" + ("00" + (o % 60)).slice(-2);
			},
			getBrowserCookie: function(cookieName) {
				return LeadCore.getCookie(cookieName);
			},
			getGeoLocation: function(tag, _key) {
				const geoStorage = window.localStorage.getItem('LeadgenicVisitorGeo');
				if (!geoStorage) {
					return null;
				}
				const parsedGeoStorage = JSON.parse(geoStorage);
				return parsedGeoStorage[_key];
			},
			checkReferrerRule: function(tag, isFirstPage) {
				if (isFirstPage) {
					const cookieName = tag + 'URL';
					const domain = decodeURIComponent(this.getBrowserCookie(cookieName)).split('/')[2];
					return domain;
				} else {
					return document.referrer.split('/')[2];
				}
			},
			checkUtmTagRule: function(tag, isFirstPage) {
				const cookieName = tag + 'URL';
				return decodeURIComponent(this.getBrowserCookie(cookieName));
				
				// if (isFirstPage) {
				// 	const cookieName = tag + 'URL';
				// 	return this.getBrowserCookie(cookieName);
				// } else {
				// 	return this.getURLTag(tag);
				// }
			},
			checkURLParams: function(tag, isFirstPage, data) {
				if (data && data.param) {
					let _URL;
					if (isFirstPage) {
						const cookieName = 'parameterURL';
						_URL = this.getBrowserCookie(cookieName);
					}
					
					return this.getURLTag(data.param, _URL);
				}
				return null;
			},
			getURLTag: function(tag, _url) {
				const url = new URL(_url || window.location.href);
				return url.searchParams.get(tag);
			},
			getLocalDate: function(d) {
				let f = {"ar-SA":"dd/MM/yy","bg-BG":"dd.M.yyyy","ca-ES":"dd/MM/yyyy","zh-TW":"yyyy/M/d","cs-CZ":"d.M.yyyy","da-DK":"dd-MM-yyyy","de-DE":"dd.MM.yyyy","el-GR":"d/M/yyyy","en-US":"M/d/yyyy","fi-FI":"d.M.yyyy","fr-FR":"dd/MM/yyyy","he-IL":"dd/MM/yyyy","hu-HU":"yyyy. MM. dd.","is-IS":"d.M.yyyy","it-IT":"dd/MM/yyyy","ja-JP":"yyyy/MM/dd","ko-KR":"yyyy-MM-dd","nl-NL":"d-M-yyyy","nb-NO":"dd.MM.yyyy","pl-PL":"yyyy-MM-dd","pt-BR":"d/M/yyyy","ro-RO":"dd.MM.yyyy","ru-RU":"dd.MM.yyyy","hr-HR":"d.M.yyyy","sk-SK":"d. M. yyyy","sq-AL":"yyyy-MM-dd","sv-SE":"yyyy-MM-dd","th-TH":"d/M/yyyy","tr-TR":"dd.MM.yyyy","ur-PK":"dd/MM/yyyy","id-ID":"dd/MM/yyyy","uk-UA":"dd.MM.yyyy","be-BY":"dd.MM.yyyy","sl-SI":"d.M.yyyy","et-EE":"d.MM.yyyy","lv-LV":"yyyy.MM.dd.","lt-LT":"yyyy.MM.dd","fa-IR":"MM/dd/yyyy","vi-VN":"dd/MM/yyyy","hy-AM":"dd.MM.yyyy","az-Latn-AZ":"dd.MM.yyyy","eu-ES":"yyyy/MM/dd","mk-MK":"dd.MM.yyyy","af-ZA":"yyyy/MM/dd","ka-GE":"dd.MM.yyyy","fo-FO":"dd-MM-yyyy","hi-IN":"dd-MM-yyyy","ms-MY":"dd/MM/yyyy","kk-KZ":"dd.MM.yyyy","ky-KG":"dd.MM.yy","sw-KE":"M/d/yyyy","uz-Latn-UZ":"dd/MM yyyy","tt-RU":"dd.MM.yyyy","pa-IN":"dd-MM-yy","gu-IN":"dd-MM-yy","ta-IN":"dd-MM-yyyy","te-IN":"dd-MM-yy","kn-IN":"dd-MM-yy","mr-IN":"dd-MM-yyyy","sa-IN":"dd-MM-yyyy","mn-MN":"yy.MM.dd","gl-ES":"dd/MM/yy","kok-IN":"dd-MM-yyyy","syr-SY":"dd/MM/yyyy","dv-MV":"dd/MM/yy","ar-IQ":"dd/MM/yyyy","zh-CN":"yyyy/M/d","de-CH":"dd.MM.yyyy","en-GB":"dd/MM/yyyy","es-MX":"dd/MM/yyyy","fr-BE":"d/MM/yyyy","it-CH":"dd.MM.yyyy","nl-BE":"d/MM/yyyy","nn-NO":"dd.MM.yyyy","pt-PT":"dd-MM-yyyy","sr-Latn-CS":"d.M.yyyy","sv-FI":"d.M.yyyy","az-Cyrl-AZ":"dd.MM.yyyy","ms-BN":"dd/MM/yyyy","uz-Cyrl-UZ":"dd.MM.yyyy","ar-EG":"dd/MM/yyyy","zh-HK":"d/M/yyyy","de-AT":"dd.MM.yyyy","en-AU":"d/MM/yyyy","es-ES":"dd/MM/yyyy","fr-CA":"yyyy-MM-dd","sr-Cyrl-CS":"d.M.yyyy","ar-LY":"dd/MM/yyyy","zh-SG":"d/M/yyyy","de-LU":"dd.MM.yyyy","en-CA":"dd/MM/yyyy","es-GT":"dd/MM/yyyy","fr-CH":"dd.MM.yyyy","ar-DZ":"dd-MM-yyyy","zh-MO":"d/M/yyyy","de-LI":"dd.MM.yyyy","en-NZ":"d/MM/yyyy","es-CR":"dd/MM/yyyy","fr-LU":"dd/MM/yyyy","ar-MA":"dd-MM-yyyy","en-IE":"dd/MM/yyyy","es-PA":"MM/dd/yyyy","fr-MC":"dd/MM/yyyy","ar-TN":"dd-MM-yyyy","en-ZA":"yyyy/MM/dd","es-DO":"dd/MM/yyyy","ar-OM":"dd/MM/yyyy","en-JM":"dd/MM/yyyy","es-VE":"dd/MM/yyyy","ar-YE":"dd/MM/yyyy","en-029":"MM/dd/yyyy","es-CO":"dd/MM/yyyy","ar-SY":"dd/MM/yyyy","en-BZ":"dd/MM/yyyy","es-PE":"dd/MM/yyyy","ar-JO":"dd/MM/yyyy","en-TT":"dd/MM/yyyy","es-AR":"dd/MM/yyyy","ar-LB":"dd/MM/yyyy","en-ZW":"M/d/yyyy","es-EC":"dd/MM/yyyy","ar-KW":"dd/MM/yyyy","en-PH":"M/d/yyyy","es-CL":"dd-MM-yyyy","ar-AE":"dd/MM/yyyy","es-UY":"dd/MM/yyyy","ar-BH":"dd/MM/yyyy","es-PY":"dd/MM/yyyy","ar-QA":"dd/MM/yyyy","es-BO":"dd/MM/yyyy","es-SV":"dd/MM/yyyy","es-HN":"dd/MM/yyyy","es-NI":"dd/MM/yyyy","es-PR":"dd/MM/yyyy","am-ET":"d/M/yyyy","tzm-Latn-DZ":"dd-MM-yyyy","iu-Latn-CA":"d/MM/yyyy","sma-NO":"dd.MM.yyyy","mn-Mong-CN":"yyyy/M/d","gd-GB":"dd/MM/yyyy","en-MY":"d/M/yyyy","prs-AF":"dd/MM/yy","bn-BD":"dd-MM-yy","wo-SN":"dd/MM/yyyy","rw-RW":"M/d/yyyy","qut-GT":"dd/MM/yyyy","sah-RU":"MM.dd.yyyy","gsw-FR":"dd/MM/yyyy","co-FR":"dd/MM/yyyy","oc-FR":"dd/MM/yyyy","mi-NZ":"dd/MM/yyyy","ga-IE":"dd/MM/yyyy","se-SE":"yyyy-MM-dd","br-FR":"dd/MM/yyyy","smn-FI":"d.M.yyyy","moh-CA":"M/d/yyyy","arn-CL":"dd-MM-yyyy","ii-CN":"yyyy/M/d","dsb-DE":"d. M. yyyy","ig-NG":"d/M/yyyy","kl-GL":"dd-MM-yyyy","lb-LU":"dd/MM/yyyy","ba-RU":"dd.MM.yy","nso-ZA":"yyyy/MM/dd","quz-BO":"dd/MM/yyyy","yo-NG":"d/M/yyyy","ha-Latn-NG":"d/M/yyyy","fil-PH":"M/d/yyyy","ps-AF":"dd/MM/yy","fy-NL":"d-M-yyyy","ne-NP":"M/d/yyyy","se-NO":"dd.MM.yyyy","iu-Cans-CA":"d/M/yyyy","sr-Latn-RS":"d.M.yyyy","si-LK":"yyyy-MM-dd","sr-Cyrl-RS":"d.M.yyyy","lo-LA":"dd/MM/yyyy","km-KH":"yyyy-MM-dd","cy-GB":"dd/MM/yyyy","bo-CN":"yyyy/M/d","sms-FI":"d.M.yyyy","as-IN":"dd-MM-yyyy","ml-IN":"dd-MM-yy","en-IN":"dd-MM-yyyy","or-IN":"dd-MM-yy","bn-IN":"dd-MM-yy","tk-TM":"dd.MM.yy","bs-Latn-BA":"d.M.yyyy","mt-MT":"dd/MM/yyyy","sr-Cyrl-ME":"d.M.yyyy","se-FI":"d.M.yyyy","zu-ZA":"yyyy/MM/dd","xh-ZA":"yyyy/MM/dd","tn-ZA":"yyyy/MM/dd","hsb-DE":"d. M. yyyy","bs-Cyrl-BA":"d.M.yyyy","tg-Cyrl-TJ":"dd.MM.yy","sr-Latn-BA":"d.M.yyyy","smj-NO":"dd.MM.yyyy","rm-CH":"dd/MM/yyyy","smj-SE":"yyyy-MM-dd","quz-EC":"dd/MM/yyyy","quz-PE":"dd/MM/yyyy","hr-BA":"d.M.yyyy.","sr-Latn-ME":"d.M.yyyy","sma-SE":"yyyy-MM-dd","en-SG":"d/M/yyyy","ug-CN":"yyyy-M-d","sr-Cyrl-BA":"d.M.yyyy","es-US":"M/d/yyyy"};
				const l = this.getBrowserLanguage();
				const y = d.getFullYear();
				const m = d.getMonth() + 1;
				const date = d.getDate();

    			f = (l in f) ? f[l] : "MM/dd/yyyy";

    			function z(s) {
    				s = '' + s;
    				return s.length > 1 ? s: '0' + s;
    			}

    			f = f.replace(/yyyy/, y);
    			f = f.replace(/yy/, String(y).substr(2));
				f = f.replace(/MM/, z(m));
				f = f.replace(/M/, m);
    			f = f.replace(/dd/, z(date));
    			f = f.replace(/d/, date);

    			return f;
			},
			getWeekday: function(d) {
				return d.toLocaleString(window.navigator.language, {weekday: 'long'});
			},
			checkCSSSelector: function(selector) {
				const element = document.querySelector(selector);
				return element ? element.innerText : null;
			},
			checkCoupon: function(id) {
				return new Promise((resolve, reject) => {
					setTimeout(async () => {
					    let value;
					    const couponId = id.replace(']', '').split('_');
						const couponElement = LGUtils.macros.latestOpenedWidgetContainer.querySelector('.element-coupon-wr .element-coupon-name[data-ccode="'+couponId[1]+'"]');
						if (couponElement) {
							value = couponElement.innerHTML;
							resolve(value);
						} else {
							resolve(null);
						}
					}, 100);
			    });
			},
			checkCouponHandler: async function(id) {
				return new Promise(async (resolve) => {
					const result = await this.checkCoupon(id);
	  				resolve(result);
  				});
			},
			getCustomVariable: function(_variable) {
				const storage = window.localStorage.getItem('LeadgenicCustomVariables');
				if (!storage) {
					return null;
				}
				const parsedStorage = JSON.parse(storage);
				return parsedStorage[_variable];
			},
			getGenericParseMacros: function(macros, data) {
				return new Promise(async (resolve) => {
					switch (macros) {

						// UTM
						case '$utm_source':
							resolve(this.checkUtmTagRule('utm_source', !this.visitCount));
							return;

						case '$utm_medium':
							resolve(this.checkUtmTagRule('utm_medium', !this.visitCount));
							return;

						case '$utm_campaign':
							resolve(this.checkUtmTagRule('utm_campaign', !this.visitCount));
							return;

						case '$utm_term':
							resolve(this.checkUtmTagRule('utm_term', !this.visitCount));
							return;

						case '$utm_content':
							resolve(this.checkUtmTagRule('utm_content', !this.visitCount));
							return;


						// DATE
						case '$date':
							resolve(this.getLocalDate(new Date()));
							return;

						case '$day':
							resolve(new Date().getDate());
							return;

						case '$month':
							resolve(new Date().getMonth() + 1);
							return;

						case '$year':
							resolve(new Date().getFullYear());
							return;

						case '$weekday':
							resolve(this.getWeekday(new Date()));
							return;


						// DEVICE
						case '$browser_language':
							resolve(this.getBrowserLanguage());
							return;

						case '$os':
							resolve(this.getBrowserOS());
							return;

						case '$Browser':
							resolve(this.getBrowser());
							return;

						case '$device':
							resolve(this.getDevice());
							return;

						case '$device_type':
							resolve(this.getDeviceType());
							return;


						// VISIT PARAMS
						case '$referrer_domain_website':
							resolve(this.checkReferrerRule('referrer', true));
							return;

						case '$referrer_domain_page':
							resolve(this.checkReferrerRule('referrer', false));
							return;

						case '$URL_parameter_website':
							resolve(this.checkURLParams('parameter', true, data));
							return;

						case '$URL_parameter_page':
							resolve(this.checkURLParams('parameter', false, data));
							return;

						case '$page_title':
							resolve(document.title);
							return;

						case '$geo_city':
							resolve(data && data.param && this.getGeoLocation(data.param, 'city'));
							return;

						case '$geo_region':
							resolve(data && data.param && this.getGeoLocation(data.param, 'region'));
							return;

						case '$geo_country':
							resolve(data && data.param && this.getGeoLocation(data.param, 'country'));
							return;

						case '$cookie':
							resolve(data && data.param && this.getBrowserCookie(data.param));
							return;

						case '$css_selector':
							resolve(data && data.param && this.checkCSSSelector(data.param));
							return;

						// TODO: Remove it for now. Let's back to coupon later
						// case '$coupon':
						// 	resolve(data && data.param && await this.checkCouponHandler(data.param));
						// 	return;

						case '$custom_variable':
							resolve(data && data.param && this.getCustomVariable(data.param))

						case '$display_rule':
							resolve('DEF');
							return;

						default:
		            		resolve(null);
					}
				});
			},
			cleanSpecialForCondition: function(condition, exp) {
				return condition.replaceAll(exp, '');
			},
			checkForConditionRule: function(_condition, _macrosValue) {
				const condition = _condition.toLowerCase();
				const macrosValue = _macrosValue.toLowerCase();

				if (condition.indexOf('*') === 0 && condition.lastIndexOf('*') === condition.length - 1) {
					return macrosValue.indexOf(this.cleanSpecialForCondition(condition, '*')) > -1;

				} 
				if (condition.lastIndexOf('*') === condition.length - 1) {
					return macrosValue.indexOf(this.cleanSpecialForCondition(condition, '*')) === 0;

				} 
				if (condition.indexOf('*') === 0) {
					const cleanCondition = this.cleanSpecialForCondition(condition, '*');
					return macrosValue.lastIndexOf(this.cleanSpecialForCondition(condition, '*')) === macrosValue.length - cleanCondition.length;

				} 
				if (condition.indexOf('>') === 0) {
					return parseInt(this.cleanSpecialForCondition(condition, '>')) < parseInt(macrosValue);

				} 
				if (condition.indexOf('<') === 0) {
					return parseInt(this.cleanSpecialForCondition(condition, '<')) > parseInt(macrosValue);

				} 
				
				return this.cleanSpecialForCondition(condition, '*') === macrosValue;
			},
			parseRuleData: function(ruleData, macrosValue) {
				if (!macrosValue) {
					return false;
				}
				if (macrosValue.includes('http://') || macrosValue.includes('https://')) {
					macrosValue = decodeURI(macrosValue);
				}
				let conditionValue;
				ruleData.split('|').some((itemRule) => {
					const checkPos1 = itemRule.indexOf('==');
					if (checkPos1 > -1) {
						const condition = itemRule.substring(0, checkPos1);
						const isCondition = this.checkForConditionRule(condition, macrosValue);
						if (isCondition) {
							conditionValue = itemRule.substring(checkPos1 + 2, itemRule.length);
							return true;
						} else {
							return false;
						}
					}
					return false;
				});
				return conditionValue;
			},

			parseFormulaIfNeed: function(ruleData, macrosValue) {
				const checkForFormulaChar = (value, character) => {
					return new Promise(async (resolve) => {
						const leftPartString  = value.substring(0, value.indexOf(character)).replace('{', '').replace('}', '');
						const rightPartString = value.substring(value.indexOf(character) + 3, value.length).replace('{', '').replace('}', '');
						const leftPart = await this.checkForDefault(leftPartString) || leftPartString;
						const rightPart = await this.checkForDefault(rightPartString) || rightPartString;
						if (character === "'-'") {
							resolve(leftPart - rightPart);
						} else if (character === "'+'") {
							resolve(parseInt(leftPart) + parseInt(rightPart));
						} else if (character === "'*'") {
							resolve(leftPart * rightPart);
						} else if (character === "'/'") {
							resolve(leftPart / rightPart);
						} else {
							resolve(null);
						}
					});
				};

				return new Promise(async (resolve) => {
					let conditionValue = await this.parseRuleData(ruleData, macrosValue);
					if (conditionValue && conditionValue.indexOf('{-formula:') > -1 && conditionValue.indexOf('-}') > -1) {
						const startIndex = conditionValue.indexOf('{-formula:');
						const endIndex = conditionValue.indexOf('-}');
						const parsedValue = conditionValue.substring(startIndex + 10, endIndex);
						if (parsedValue.indexOf("'-'") > -1) {
							conditionValue = this.replaceBetween(conditionValue, startIndex, endIndex + 2, await checkForFormulaChar(parsedValue, "'-'"));
						} else if (parsedValue.indexOf("'+'") > -1) {
							conditionValue = this.replaceBetween(conditionValue, startIndex, endIndex + 2, await checkForFormulaChar(parsedValue, "'+'"));
						} else if (parsedValue.indexOf("'*'") > -1) {
							conditionValue = this.replaceBetween(conditionValue, startIndex, endIndex + 2, await checkForFormulaChar(parsedValue, "'*'"));
						} else if (parsedValue.indexOf("'/'") > -1) {
							conditionValue = this.replaceBetween(conditionValue, startIndex, endIndex + 2, await checkForFormulaChar(parsedValue, "'/'"));
						}
					}

					if (conditionValue && conditionValue.indexOf('{$') > -1 && conditionValue.indexOf('}') > -1) {
						const startIndex = conditionValue.indexOf('{');
						const endIndex = conditionValue.indexOf('}');
						const parsedValue = conditionValue.substring(startIndex + 1, endIndex);
						const specPart = await this.checkForDefault(parsedValue);
						conditionValue = this.replaceBetween(conditionValue, startIndex, endIndex + 1, specPart);
					}

					resolve(conditionValue);
				});
			},
			parseDisplayRule: function(macros) {
				return new Promise(async (resolve) => {
					const displayRuleStartPos = macros.indexOf('$display_rule||');
					macros = macros.substring(displayRuleStartPos + 15, macros.length);

					if (this.checkForMacrosWithParam(macros)) {
						const defStartPos = macros.indexOf(":");
						let param;
						if (defStartPos > -1) {
							param = macros.substring(defStartPos + 2, macros.length);
							macros = macros.substring(0, defStartPos);

							const defStartPos2 = param.indexOf(":");
							const specCharThere = param.indexOf("{");
							if (defStartPos2 > -1) {
								const param2 = param.substring(defStartPos2 + 1, param.length);
								param = param.substring(0, defStartPos2 - 1);
								
								const macrosValue = await this.getGenericParseMacros(macros, {param});
								resolve(await this.parseFormulaIfNeed(param2, macrosValue));
							} else {
								const macrosValue = await this.getGenericParseMacros(macros);
								resolve(await this.parseFormulaIfNeed(param, macrosValue));
							}
						}
					} else {
						const defStartPos = macros.indexOf(":");
						let param;
						if (defStartPos > -1) {
							param = macros.substring(defStartPos + 1, macros.length);
							macros = macros.substring(0, defStartPos);
							
							const macrosValue = await this.getGenericParseMacros(macros);
							resolve(await this.parseFormulaIfNeed(param, macrosValue));
						}
					}
					
					resolve(await this.parseParams(macros, true));
				});
			},
			parseParams: function(macros, isDisplayRule) {
				return new Promise(async (resolve) => {
					const defStartPos = macros.indexOf(":");
					let param;
					if (defStartPos > -1) {
						param = macros.substring(defStartPos + 2, macros.length - 1);
						macros = macros.substring(0, defStartPos);
					}
					resolve(await this.getGenericParseMacros(macros, {param}));
				});
			},
			checkForMacrosWithParam: function(macros) {
				return macros.indexOf('$URL_parameter_website') > -1 || macros.indexOf('$URL_parameter_page') > -1 || 
					macros.indexOf('$geo_city') > -1 || macros.indexOf('$geo_region') > -1 ||
					macros.indexOf('$geo_country') > -1 || macros.indexOf('$cookie') > -1 ||
					macros.indexOf('$form_field_id') > -1 || macros.indexOf('$css_selector') > -1 ||
					macros.indexOf('$coupon') > -1 || macros.indexOf('$custom_variable') > -1;
			},
			checkForParams: function(macros) {
				return new Promise(async (resolve) => {
					if (macros.indexOf('$display_rule') > -1) {
						resolve(await this.parseDisplayRule(macros));
					} else if (this.checkForMacrosWithParam(macros)) {
						resolve(await this.parseParams(macros));
					} else {
						resolve(await this.getGenericParseMacros(macros));
					}
				});
			},
			checkForDefault: function(macros) {
				return new Promise(async (resolve) => {
					const defStartPos = macros.lastIndexOf(",'default:");
					const defEndPos = macros.lastIndexOf("'");
					let defValue = '';
					if (defStartPos > -1 && defEndPos > -1) {
						defValue = macros.substring(defStartPos + 10, defEndPos);
						macros = macros.substring(0, defStartPos);
					}
					const replcementValueAfterParams = await this.checkForParams(macros) || defValue;
					resolve(replcementValueAfterParams);
				});
			},
			indexesOf: function(string, regex) {
			    let match,
			        indexes = {};

			    regex = new RegExp(regex);

			    while (match = regex.exec(string)) {
			        if (!indexes[match[0]]) indexes[match[0]] = [];
			        indexes[match[0]].push(match.index);
			    }

			    return indexes;
			},
			replaceBetween(origin, startIndex, endIndex, insertion) {
				return origin.substring(0, startIndex) + insertion + origin.substring(endIndex);
			},
			replacementLoopLevel1: async function(widgetId, textList) {
				return new Promise(async (resolve) => {
					textList.forEach(async (_, i) => {
						resolve(await this.replacementLoopLevel2(widgetId, i, _));
					});
				});
			},
			replacementLoopLevel2: async function(widgetId, i, item) {
				return new Promise(async (resolve) => {
					const tags = this.cacheDOM[widgetId][i];
					const textTags = this.cacheDOM[widgetId + 'text'][i];
					const macrosList = this.indexesOf(tags, /{{\$|}}/g);
					const macrosListText = this.indexesOf(textTags, /{{\$|}}/g);
					if (macrosList['{{$'] && macrosList['}}'] && macrosList['{{$'].length === macrosList['}}'].length) {
						let replacedHTML = '';
						let lastIndex = 0;
						for (let i = 0; i < macrosList['{{$'].length; i++) {
							const startI = macrosList['{{$'][i];
							const startIText = macrosListText['{{$'][i];

							const endI = macrosList['}}'][i];
							const endIText = macrosListText['}}'][i];

							const macros = textTags.substring(startIText + 2, endIText);
							const macrosReplacementValue = await this.checkForDefault(macros);
							const substractedTag = tags.substring(lastIndex, startI);
							replacedHTML = replacedHTML + substractedTag + macrosReplacementValue;
							lastIndex = endI + 2;
						}
                        const substractedPart = tags.substring(lastIndex);
						replacedHTML = replacedHTML + substractedPart;
						item.innerHTML = replacedHTML;
					}
					resolve();
				});
			},
			initReplaceMacro: function(container, widgetId, visitCount) {
				return new Promise(async (resolve, reject) => {
					this.visitCount = visitCount;
					const ulList = container.querySelector('ul');
					const textList = [...ulList.querySelectorAll('.title-main-new-dot, button#btnExitButtonLGWG > div, button#btnExitLGWGPop > div, button.form-ext-button > div > div')];
					
					this.latestOpenedWidgetContainer = container;
					if (!this.cacheDOM[widgetId]) {
						this.cacheDOM[widgetId] = textList.map(_ => _.innerHTML);
						this.cacheDOM[widgetId + 'text'] = textList.map(_ => _.textContent);
					}

					if (!textList.length) {
						resolve();
						return;
					}
					await this.replacementLoopLevel1(widgetId, textList);
					resolve();
				});
			}
		}
	};
})();



