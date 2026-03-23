(function () {
	if (typeof LeadCore !== 'undefined') {
		return;
	}

	LeadWidgets = {
		list : {}
	};

	LeadCoreExt = {
		getFA5PackIcon: function(_iconId) {
			return LG_FA5Pack.includes(_iconId) ? _iconId : 'fas fa-circle';
		},
		hiddenFieldCoupons: {},
        isOS: function() {
			return navigator.userAgent.match(/ipad|ipod|iphone/i);
		},
		buildWidgetScript: function(script) {
			var newScript  = document.createElement("script");
			newScript.type = "text/javascript";
			newScript.textContent = script;
			document.getElementsByTagName("body")[0].appendChild(newScript);
		},
		parseWidgetScript: function(response) {
			let onScript = response;
			onScript = onScript.replace(/<script[^>]*>/gi, '');
    		onScript = onScript.replace(/<\/script>/gi, '');
    		//onScript = onScript.replace(/ /g, ''); 
    		return onScript;
		},
		parseFieldsForWidgetScript: function(script, data) {
			let targetScript = script;
    		if (data.email) {
    			targetScript = targetScript.replace(/{__email__}/g, data.email);
    		}
    		if (data.firstName) {
    			targetScript = targetScript.replace(/{__name__}/g, data.firstName);
    		}
    		if (data.phone) {
    			targetScript = targetScript.replace(/{__phone__}/g, data.phone);
    		}
    		if (data.comment) {
    			targetScript = targetScript.replace(/{__message__}/g, data.comment);
    		}
			if (data.customFields && !LGWGService.isObjectEmpty(data.customFields && data.helpData && !LGWGService.isObjectEmpty(data.helpData)) ) {
				Object.keys(data.customFields).forEach(fieldItem => {
					const scriptKey = `{__${data.helpData[fieldItem]}__}`;
					if (targetScript.indexOf(scriptKey) !== -1) {
						const pattern = new RegExp(scriptKey, "g");
						targetScript = targetScript.replace(pattern, data.customFields[fieldItem]);
					}
				});
			}
    		return targetScript;
		},
        getPromise: function(url, getRequest) {
			return new Promise(function(resolve, reject) {
				let xhr = new XMLHttpRequest();
				if (getRequest) {
					xhr.open("GET", url, true);
				} else {
					xhr.open("POST", url, true);
                	xhr.setRequestHeader("Content-Type", "application/json; charset=UTF-8");
				}

				xhr.onload = () => {
					if (xhr.status === 200 && xhr.response) {
						resolve(xhr.response);
					} else {
						var error = new Error(xhr.statusText);
						error.code = xhr.status;
						reject(error);
					}
				};

				xhr.onerror = () => {
					reject(new Error("Network Error"));
				};

				xhr.send();
			});

		},
		isExitIntent: function(exitData) {
			return ((exitData.enable || exitData.enabled) && typeof exitData.desktopEnable === 'undefined' && typeof exitData.mobileEnable === 'undefined') || 
				((exitData.enable || exitData.enabled) && (((typeof exitData.desktopEnable !== 'undefined') && exitData.desktopEnable) || ((typeof exitData.mobileEnable !== 'undefined') && exitData.mobileEnable)));
		},
		isExitIntentDesktop: function(exitData) {
			return ((exitData.enable || exitData.enabled) && typeof exitData.desktopEnable === 'undefined' && typeof exitData.mobileEnable === 'undefined') || 
				((exitData.enable || exitData.enabled) && ((typeof exitData.desktopEnable !== 'undefined') && exitData.desktopEnable));
		},
		isExitIntentMobile: function(exitData) {
			return ((exitData.enable || exitData.enabled) && typeof exitData.desktopEnable === 'undefined' && typeof exitData.mobileEnable === 'undefined') || 
				((exitData.enable || exitData.enabled) && ((typeof exitData.mobileEnable !== 'undefined') && exitData.mobileEnable));
		},
		isExitIntentReadyToShow: function(exit) {
			return !exit && !LeadCore.isWidgetActive.length;
		},
		setCouponBtnHandler: function(btn, couponValue, lgwgClickEvent, couponCopyAction) {
            btn.addEventListener(lgwgClickEvent, function(event) {
                var _this = this;
                event.stopPropagation();

                if (!couponValue) return;
                LeadCoreExt.LGWGCopyToClipboard(couponValue, function() {
                    _this.classList.add("element-coupon-copied");
                    setTimeout(function() {
                        _this.classList.remove("element-coupon-copied");
                    }, 3000);
                    const { isCouponCopyAction, metrikaId, onTargetScript, targetSettings } = couponCopyAction;
                    if (isCouponCopyAction && metrikaId) {
                    	if (!LeadCore.getCookie('LGWGCouponCopyActionLock'+metrikaId).length) {
                    		LeadCore.setCookie('LGWGCouponCopyActionLock'+metrikaId, LeadCore.siteId, 0.007);
	                    	LeadCore.pushTargetAction(1, metrikaId);

	                    	if (targetSettings) {
	                    		const { cookieName, type } = targetSettings;
                                LGWGService.checkTargetLock(type, cookieName);
							}

	                    	if (onTargetScript) {
	                    		LeadCoreExt.buildWidgetScript(onTargetScript);
	                    	}

	                    	LeadCore.sendAnalyticGlobal(metrikaId);
                    	}
                    }
                });
            });
		},
        getCoupon: function(dParams, btn, couponEl, lgwgClickEvent, couponCopyAction) {
            var EMPTY_COUPON = "&nbsp;";
            var couponElLoader = btn.querySelector(".element-coupon-loader");
			var targetUrl = dParams.base + "/api/gate/sites/" + dParams.siteId + "/visits/" + dParams.visitId + "/coupons/" + dParams.couponCode;

            couponEl.innerHTML = EMPTY_COUPON;

			LeadCoreExt.getPromise(targetUrl).then(function(response) {
				var result = JSON.parse(response).data;
				if (result) {
                    couponEl.innerHTML = result.value;
                    btn.classList.remove("non-coupon-value");
                    couponElLoader.classList.add("lgwg-none");

                    if (!LeadCoreExt.hiddenFieldCoupons[couponCopyAction.metrikaId]) {
                    	LeadCoreExt.hiddenFieldCoupons[couponCopyAction.metrikaId] = [];
                    }
                    const couponCache = {
                    	code: result.code,
						value: result.value,
					};
                    LeadCoreExt.hiddenFieldCoupons[couponCopyAction.metrikaId].push(couponCache);
                    LeadCoreExt.setCouponBtnHandler(btn, result.value, lgwgClickEvent, couponCopyAction);
				} else {
                    couponEl.innerHTML = EMPTY_COUPON;
                    couponElLoader.classList.add("lgwg-none");
				}
			}, function(error) {
                couponEl.innerHTML = EMPTY_COUPON;
                couponElLoader.classList.add("lgwg-none");
			});
		},
        LGWGCopyToClipboard: function(str, callback) {
            var el = document.createElement("textarea");
            el.value = str;
            el.setAttribute("readonly", "");
            el.style.position = "absolute";
            el.style.left = "-9999px";
            document.body.appendChild(el);

            var selected;
            // handle iOS as a special case
            if (LeadCoreExt.isOS()) {
                // save current contentEditable/readOnly status
                var editable = el.contentEditable;
                var readOnly = el.readOnly;

                // convert to editable with readonly to stop iOS keyboard opening
                el.contentEditable = true;
                el.readOnly = true;

                // create a selectable range
                var range = document.createRange();
                range.selectNodeContents(el);

                // select the range
                var selection = window.getSelection();
                selection.removeAllRanges();
                selection.addRange(range);
                el.setSelectionRange(0, 999999);

                // restore contentEditable/readOnly to original state
                el.contentEditable = editable;
                el.readOnly = readOnly;
            } else {
                selected = document.getSelection().rangeCount > 0 ? document.getSelection().getRangeAt(0) : false;
                el.select();
            }

            document.execCommand("copy");
            document.body.removeChild(el);

            if (selected) {
                document.getSelection().removeAllRanges();
                document.getSelection().addRange(selected);
            }
            callback();
		},
        initCouponClickOperation: function(LGWGCouponWrappers, lgwgClickEvent, dParam, couponCopyAction) {
            for (var i = 0; i < LGWGCouponWrappers.length; i++) {
                var btn = LGWGCouponWrappers[i];

                var couponEl = btn.querySelector(".element-coupon-name");
				if (!dParam) return;
                dParam["couponCode"] = couponEl.getAttribute("data-ccode");

                if (!couponCopyAction.isCouponCopyAction && couponCopyAction.couponElements && couponCopyAction.couponElements.length) {
                	var couponModel = couponCopyAction.couponElements.filter(function(el) {
			        	return el.counter == couponEl.getAttribute("data-ccounter");
			        });
			        couponCopyAction.isCouponCopyAction = couponModel[0].isCopyAction;
                }
                LeadCoreExt.getCoupon(dParam, btn, couponEl, lgwgClickEvent, couponCopyAction);
            }
		},
        initFormCouponClickOperation: function(LGWGCouponWrappers, lgwgClickEvent, couponValue, couponCopyAction) {
            var EMPTY_COUPON = "&nbsp;";
            for (var i = 0; i < LGWGCouponWrappers.length; i++) {
                var btn = LGWGCouponWrappers[i];

                var couponEl = btn.querySelector(".element-coupon-name");
                couponEl.innerHTML = couponValue;
                var couponElLoader = btn.querySelector(".element-coupon-loader");
                couponElLoader.classList.add("lgwg-none");

                if (couponValue !== EMPTY_COUPON) {
                    btn.classList.remove("non-coupon-value");
                    LeadCoreExt.setCouponBtnHandler(btn, couponValue, lgwgClickEvent, couponCopyAction);
                }
            }
        },
        isItSocialCallbackCoupon: function(_) {
            return _.couponCallback && _.couponCallback.enable;
		},
        isItExitCallbackCoupon: function(_) {
            return _.couponCallback && _.couponCallback.enable;
        },
        isItFormCallbackCoupon: function(_) {
            return _.enable && _.couponCallback && _.couponCallback.enable;
        },
        openCouponCallback: function(widgetId, couponModel, type, couponValue, metrikaId, onTargetScript, targetSettings) {
            if (couponModel.couponCallback && couponModel.couponCallback.enable) {
                var iframeCC = document.getElementById(widgetId + "__iframe__" + type);
                iframeCC.contentWindow.showCC(widgetId, couponModel, couponValue, metrikaId, onTargetScript, targetSettings);

                var divElementCC = document.getElementById(widgetId + "__div__" + type);
                divElementCC.classList.remove("wv-cc-none-start-pop");
			}
        },
		isCouponAndPossibleToCloseWidget: function(widgetElementSettings) {
			return (typeof widgetElementSettings.couponCallback !== "undefined") && 
				   (typeof widgetElementSettings.couponCallback.coupon !== "undefined") &&
				   widgetElementSettings.couponCallback.enable &&
				   widgetElementSettings.couponCallback.coupon.closeAfter;
		},
		isCouponAndPossibleToCopyAction: function(widgetElementSettings) {
			return (typeof widgetElementSettings.couponCallback !== "undefined") && 
				   (typeof widgetElementSettings.couponCallback.coupon !== "undefined") &&
				   widgetElementSettings.couponCallback.coupon.isCopyAction;
		}
	};

	LeadCoreDEV = {
		attempts: 0,
		scriptTagUrl: {
			dev: "192.168.50.140:9999/getscript",
			labs: "gate-labs.leadgenic.ru/getscript",
			production: "gate.leadgenic.ru/getscript",
		},
		baseUrl: {
			dev: "http://192.168.50.140:9999",
			labs: "https://gate-labs.leadgenic.ru",
			production: "https://gate.leadgenic.ru"
		},
		widgetsUrl: {
			dev: "http://192.168.50.140:8181/",
			labs: LeadCoreEnv.servicePath.baseUri + LeadCoreEnv.servicePath.location,
			production: LeadCoreEnv.servicePath.baseUri + LeadCoreEnv.servicePath.location
		},
		currentMode: LeadCoreEnv.mode,
		labsToDev: {
			siteId: '62c6c4a79de8360001d1dab4',
			popup: {
				js: 'http://192.168.50.140:8181/src/widgets/lg_widgets/popup/lgwg_popup.js',
				css: 'http://192.168.50.140:8181/src/widgets/lg_widgets/popup/lgwg_popup.css'
			},
			label_widget: {
				js: 'http://192.168.50.140:8181/src/widgets/lg_widgets/label/lgwg_label.js',
				css: 'http://192.168.50.140:8181/src/widgets/lg_widgets/label/lgwg_label.css'
			},
			optindot: {
				js: 'http://192.168.50.140:8181/src/widgets/lg_widgets/dot/dot_hunter.js',
				css: 'http://192.168.50.140:8181/src/widgets/lg_widgets/dot/dot_hunter.css'
			},
			containerized: {
				js: 'http://192.168.50.140:8181/src/widgets/lg_widgets/static/lgwg_static.js',
				css: 'http://192.168.50.140:8181/src/widgets/lg_widgets/static/lgwg_static.css'
			},
			0: {
				js: 'http://192.168.50.140:8181/src/widgets/lg_widgets/invite/script-invite.js',
				css: 'http://192.168.50.140:8181/src/widgets/lg_widgets/invite/style-invite.css'
			},
			3: {
				js: 'http://192.168.50.140:8181/src/widgets/lg_widgets/smart-pp/script-smart-pp.js',
				css: 'http://192.168.50.140:8181/src/widgets/lg_widgets/smart-pp/style-smart-pp.css'
			},
		},
	};

	getLGSiteIdFromScript = function() {
	  var scripts = document.getElementsByTagName("script");

	  for (var i=0; i<scripts.length; i++) {
	  	var matchUrl = LeadCoreDEV.scriptTagUrl[LeadCoreDEV.currentMode];
	  	if (LeadCoreDEV.currentMode === "production") {
	  		var matchUrl2 = "gate.leadgenic.com/getscript";
	  	}
	    if ((scripts[i].src.indexOf("/" + matchUrl) > -1) || (matchUrl2 && scripts[i].src.indexOf("/" + matchUrl2) > -1)) {
	      var pa = scripts[i].src.split("?").pop().split("&");

	      var p = {};
	      for(var j=0; j<pa.length; j++) {
	        var kv = pa[j].split("=");
	        p[kv[0]] = kv[1];
	      }
	      return p.site || null;
	    }
	  }
	  // No scripts match
	  return {};
	};

	LeadCore = {
	    getUserTime: function() {
	        var udate = new Date();
	        return udate.getHours() * 3600000 + udate.getMinutes() * 60000 + udate.getSeconds() * 1000;
	    },
		constants: {
            lgLinkStatic: "Виджет LeadGenic - Хотите такой же?",
			lgLink: "Виджет LeadGenic - Хотите такой же?",
			workOn: "Работает на ",
			workOnLg: "Работает на LeadGenic",
			lgLink60: "LeadGenic",
			fromStoS: "От края до края",
			onCenter: "По центру",
			fromRight: "Справа",
			fromLeft: "Слева",
			fromBottom: "Снизу",
			fromTop: "Сверху",
			ownValue: "Собственная",
			auto: "Авто",
			horizontal: "Горизонтальная",
			vertical: "Вертикальная",
            fromStartSide: "От верхней границы",
            fromEndSide: "От нижней границы",
            fromCenterSide: "По центру",
			fromBottomBorder: "От нижней границы",
			onCenterWidget: "По центру виджета",
			underContent: "Под контентом",
			toAllWidth: "На всю ширину",
			leftBottomCorner: "Левый нижний угол",
			rightBottomCorner: "Правый нижний угол",
			leftBrowserSide: "Левая сторона браузера",
			rightBrowserSide: "Правая сторона браузера",
			topLeftCorner: "Верхний левый угол",
			topCenterCorner: "Сверху по центру",
			topRightCorner: "Верхний правый угол",
			centerLeftCorner: "Слева по центру",
			centerCenterCorner: "По центру окна браузера",
			centerRightCorner: "Справа по центру",
			bottomLeftCorner: "Нижний левый угол",
			bottomCenterCorner: "Снизу по центру",
			bottomRightCorner: "Нижний правый угол",
			orderFromSite: "Заявка с сайта",
			findForYouThisSite: "Нашел для тебя этот сайт",
			lookAt: "Посмотри:",
			alignOnCenter: "По центру",
			alignOnTop: "По верхнему краю",
			alignOnBottom: "По нижнему краю",
			alignToAllSize: "Растянуть по ширине и высоте блока",
			alignToUserSize: "Установить произвольные габариты",
			fullWidgetArea: "Вся площадь виджета",
            onlyContentWidgetArea: "Только над контентом",
            onlyContentWidgetAreaUnder: "Только под контентом",
			autoinviteAND: "при соблюдении ВСЕХ активированных правил",
			autoinviteOR: "при соблюдении ЛЮБОГО ИЗ активированных правил",
			autoinviteANDEx: "всех",
			autoinviteOREx: "любого из"
		},
		isMobile: {
			Android: function() {
				return navigator.userAgent.match(/Android/i);
			},
			BlackBerry: function() {
				return navigator.userAgent.match(/BlackBerry/i);
			},
			iOS: function() {
				return navigator.userAgent.match(/iPhone|iPad|iPod/i);
			},
			Opera: function() {
				return navigator.userAgent.match(/Opera Mini/i);
			},
			Windows: function() {
				return navigator.userAgent.match(/IEMobile/i);
			},
			Firefox: function() {
				return navigator.userAgent.match(/Firefox/i);
			},
			Edge: function() {
				return navigator.userAgent.match(/Edge/i);
			},
			any: function() {
				return (LeadCore.isMobile.Android() || LeadCore.isMobile.BlackBerry() || LeadCore.isMobile.iOS() || LeadCore.isMobile.Opera() || LeadCore.isMobile.Windows());
			}
		},
		createLGWGElement: function(name, attributes ) {
			let el = document.createElement(name);
			if (typeof attributes == 'object') {
				for (let i in attributes) {
					el.setAttribute(i, attributes[i]);

					if (i.toLowerCase() === 'class') {
						el.className = attributes[i]; // for IE
					} else if (i.toLowerCase() === 'style') {
						el.style.cssText = attributes[i]; // for IE
					}
				}
			}
			for (let i = 2; i < arguments.length; i++) {
				let val = arguments[i];
				if (typeof val == 'string') {
					el.innerHTML = val;
					val = document.createTextNode('');
				}
				el.appendChild(val);
			}
			return el;
		},
		server: {
			protocol        : null,
			domain          : null,
			port            : null,
			iframe          : null,
			getPushInfoPath : function() {
				return LeadCore.base + "/pushInfo";
			}

		},
		siteId    : getLGSiteIdFromScript(),
		baseLGURL : LeadCoreDEV.baseUrl[LeadCoreDEV.currentMode],
		base      : LeadCoreDEV.baseUrl[LeadCoreDEV.currentMode],
		visit     : null,
		isWidgetActive: [],
		hidden: {},
		addTopForDot: {
			placeNewLabel: "default",
			placeOldLabel: "default"
		},
		mouse: {
			posX: 0,
			posY: 0
		},
		addScriptItem: function(url) {
			const newScript = document.createElement("script");
			newScript.src  = url;
			document.getElementsByTagName("body")[0].appendChild(newScript);
		},
		getCookie: function (cname) {
			var name = cname + "=";
			var ca = document.cookie.split(';');
			for ( var i=0; i < ca.length; i++) {
				var c = ca[i];
				while (c.charAt(0)==' ') c = c.substring(1);
				if (c.indexOf(name) == 0) return c.substring(name.length,c.length);
			}
			return "";
		},
		setCookie: function(cname, cvalue, exdays) {
			var exp = 0;
			var d = new Date();

			if (exdays > 0) {
				exp = d.setTime(d.getTime() + (exdays*24*60*60*1000));
				exp = d.toUTCString();
			}

			var expires = "expires="+exp;
			document.cookie = cname + "=" + cvalue + "; " + expires + "; path=/";
		},
		eraseCookie: function (cname) {
		    document.cookie = cname + '=; max-age=0';
		},
		removeCookie: function (cname) {
			document.cookie = cname +'=; Path=/; Expires=Thu, 01 Jan 1970 00:00:01 GMT;';
		},
		setActionLockCookie: function() {
			var d = new Date();
			LeadCore.setCookie("LGWGActionLock", d.getTime(), 365);
		},
		isActionLockExpire: function(gap, cookieName) {
			var currentD = new Date();
			var actionLockTime = LeadCore.getCookie(cookieName);
			if (actionLockTime.length) {
				var hours = Math.abs(currentD.getTime() - actionLockTime) / 3600000;
				if (hours > gap) {
					LeadCore.eraseCookie('LGWGActionLock');
					return false;
				} else {
					return true;
				}
			}
			
			return false;
		},
		sendAnalyticGlobal: function (widgetID, eventType) {
			if (typeof LeadCore.analyticsParams !== "undefined") {
				var analParams = LeadCore.analyticsParams;
		 
				for (var i = 0; i < analParams.length; i++) {
					var analyticsParamsObj = analParams[i];
					if (analyticsParamsObj.type === "ymetrika") {
			   			if (typeof window['yaCounter'+analyticsParamsObj.counter+''] != 'undefined') {
							switch (eventType) {
								case 'SHOW':
									window['yaCounter'+analyticsParamsObj.counter+''].reachGoal('leadgenic_show_send');
									window['yaCounter'+analyticsParamsObj.counter+''].reachGoal('leadgenic_widget_show_'+widgetID);
									break;

								default:
									window['yaCounter'+analyticsParamsObj.counter+''].reachGoal('leadgenic_lead_send');
									window['yaCounter'+analyticsParamsObj.counter+''].reachGoal('leadgenic_widget_lead_'+widgetID);
									break;
							}
			   			}
			  		}
			  		if (analyticsParamsObj.type === "ganalytics") {
					    if (typeof window.dataLayer != 'undefined' && window.dataLayer.length) {
						    switch (eventType) {
							    case 'SHOW':
									window.dataLayer.push({'event': 'leadgenic_show_send'});
									window.dataLayer.push({'event': 'leadgenic_widget_show_'+widgetID});
								    break;
						   
							    default:
									window.dataLayer.push({'event': 'leadgenic_lead_send'});
									window.dataLayer.push({'event': 'leadgenic_widget_lead_'+widgetID});
								   	break;
						    }
					    }
					    if (analyticsParamsObj.service === "UNIVERSAL" && (typeof window.ga != 'undefined')) {
						   switch (eventType) {
							   case 'SHOW':
									window.ga('send', 'event', 'lg_click', 'leadgenic_show_send');
									window.ga('send', 'event', 'lg_click', 'leadgenic_widget_show_'+widgetID);
								  	break;
						   
							   default:
									window.ga('send', 'event', 'lg_click', 'leadgenic_lead_send');
									window.ga('send', 'event', 'lg_click', 'leadgenic_widget_lead_'+widgetID);
									break
						   }
					    }
					    if ((analyticsParamsObj.service === "GTAG") && (typeof window.gtag != 'undefined')) {
						   switch (eventType) {
							   case 'SHOW':
									window.gtag('event', 'leadgenic_show_send', {'event_category': 'lg_click'});
									window.gtag('event', 'leadgenic_widget_show_'+widgetID, {'event_category': 'lg_click'});
								   break;
						   
							   default:
									window.gtag('event', 'leadgenic_lead_send', {'event_category': 'lg_click'});
									window.gtag('event', 'leadgenic_widget_lead_'+widgetID, {'event_category': 'lg_click'});
								   break;
						   }
					   	}
			  		}
			 	}
			}
	   	},
		setCorrectIntervalForCookie: function(intervalType, value) {
			if (intervalType === "DAY") {
				return value;
			} else if (intervalType === "HOU") {
				return value/24;
			} else if (intervalType === "MIN") {
				return (value/(24*60));
			} else if (intervalType === "SEC") {
				return (value/(24*60*60));
			}
		},
		loadSocTracking: function() {
            LeadCore.server.domain   = LeadCore.visit.domainInfo.domain;
            LeadCore.server.iframe   = LeadCore.visit.domainInfo.iframe;
            LeadCore.server.port 	 = LeadCore.visit.domainInfo.port;
            LeadCore.server.protocol = LeadCore.visit.domainInfo.protocol;
			LeadCore.addScriptItem("${base}/socTracking?site=${site.id}");
		},
		loadWidget: function(widget) {
			return new Promise((resolve) => {
				const head   = document.getElementsByTagName('head')[0];
				const style  = document.createElement('link');
				const script = document.createElement('script');

				script.setAttribute("type", "text/javascript");
				script.setAttribute("charset", "UTF-8");
            	script.setAttribute("defer", "");
            	if (LeadCore.siteId === LeadCoreDEV.labsToDev.siteId && LeadCoreDEV.currentMode === 'labs') {
            		if (widget.template && widget.type.code) {
            			widget.template.js = LeadCoreDEV.labsToDev[widget.type.code].js;
						widget.template.css = LeadCoreDEV.labsToDev[widget.type.code].css;
					}
					if (widget.dataType === 'SMARTPOINT' && widget.js && widget.css) {
						widget.js = LeadCoreDEV.labsToDev[widget.type].js;
						widget.css = LeadCoreDEV.labsToDev[widget.type].css;
					}
				}
            	style.href = widget.template ? widget.template.css : widget.css;
            	style.setAttribute("rel", "stylesheet");
            	head.appendChild(style);

				script.addEventListener('load', function() {
					this.removeEventListener('load', arguments.callee);
					resolve(true);
				});

				script.src = widget.template ? widget.template.js : widget.js;
				head.appendChild(script);
			});
		},
        addGeneralWidgetToSite: function(type, fileName) {
        	const LGWGPathForDevGeneral = LeadCoreDEV.widgetsUrl[LeadCoreDEV.currentMode] + type + "/";
			const ccStyle  = document.createElement('link');
			const ccScript = document.createElement('script');
            ccStyle.href = LGWGPathForDevGeneral + fileName + ".css";
            ccScript.src = LGWGPathForDevGeneral + fileName + ".js";
            ccScript.setAttribute("async", "");
            ccScript.setAttribute("defer", "");
            ccStyle.setAttribute("rel", "stylesheet");
            document.getElementsByTagName("head")[0].appendChild(ccStyle);
            document.getElementsByTagName("body")[0].appendChild(ccScript);
        },
        loadCouponCallbackGeneralScript: function() {
			LeadCore.addGeneralWidgetToSite('coupon-callback', 'lgwg_coupon_callback');
        },
		getMultiProgressBarDefaultSettings: function() {
	    	return {
                enable: false,
                bgColor: '#CCC',
                barColor: '#FF0000',
                thickness: 10,
                radius: 6,
                title: '<span>Готово:</span>',
                titleColor: '#000',
                fontSize: 12,
                font: {
                    fontFamily: "Arial, sans-serif",
                    name: "Arial",
                },
                start: 0,
                end: 100,
                progressValueEnable: true,
                progressValueUnit: '%',
                animate: true,
                isFirstStep: true,
            };
        },
		getMultiRuleDefaultSetting: function() {
	    	return {
                enable: false,
                rule: {
                    element: null,
                    show: true,
                    stepId: 0,
                    value: null
                }
            };
		},
		parseSettingsWithoutMulti: function(guiprops) {
	    	return {
                ...guiprops,
                formExt: {
                    enable: guiprops.formExt.enable,
                    steps: [
                        {
                            isCollapsed: false,
                            list: guiprops.formExt.model.list,
                            settings: LeadCore.getMultiRuleDefaultSetting(),
                            stepId: 0,
                        }
                    ],
                    model: {
                        mainSettings: {
                            ...guiprops.formExt.model.mainSettings,
                            progressBar: LeadCore.getMultiProgressBarDefaultSettings(),
                        },
                    },
                },
            };
		},
        parseSettingsForOldForm: function(guiprops) {
            return {
                ...guiprops,
                formExt: {
                    enable: false,
                    steps: [],
                    model: {
                        mainSettings: {
                            progressBar: LeadCore.getMultiProgressBarDefaultSettings(),
                        },
                    },
                },
            };
        },
		loadWidgetsCheck: function(widgets, isTemplate) {
			let popupLoad = false;
            let containerizedLoad = false;
			let isPinterestLoad = false;
			
			let isExtraScriptsGeneral = false;

			if (widgets[0].guiprops) {
				LeadCore.loadCouponCallbackGeneralScript();
			}

			const isOwnWidgetReady = (wList, type) => {
				return wList.some(_ => _.type.code === type);
			};

			const isOwnLabelWidgetReadyAndPlace = (wList, place) => {
				const labelWidget = wList.find(_ => _.type.code === 'label_widget');
				if (labelWidget) {
					return (labelWidget.guiprops.labelMain.place === LeadCore.constants.bottomLeftCorner && place === 2) || 
						   (labelWidget.guiprops.labelMain.place === LeadCore.constants.bottomRightCorner && place === 0) ||
						   (labelWidget.guiprops.labelMain.place === LeadCore.constants.leftBrowserSide && place === 3) ||
						   (labelWidget.guiprops.labelMain.place === LeadCore.constants.rightBrowserSide && place === 1);
				} else {
					return false;
				}
			};

			const isOwnDotWidgetReadyAndPlace = (wList, place) => {
				const optindotWidget = wList.find(_ => _.type.code === 'optindot');
				if (optindotWidget) {
					return (optindotWidget.guiprops.dhVisual.place === LeadCore.constants.rightBottomCorner && place === 0) || 
						   (optindotWidget.guiprops.dhVisual.place === LeadCore.constants.leftBottomCorner && place === 2);
				} else {
					return false;
				}
			};

			const widgetListForLoad = widgets.reduce((filtered, widgetItem) => {
				if (widgetItem.guiprops) {
					if (widgetItem.type.code === 'label_widget') {
						if (LeadCore.isMobile.any() || (widgetItem.guiprops.labelMain.place === "Нижний левый угол" || widgetItem.guiprops.labelMain.place === "Нижний правый угол")) {
							LeadCore.addTopForDot.placeNewLabel = widgetItem.guiprops.labelMain.place;
							LeadCore.addTopForDot.valueNewLabel = widgetItem.guiprops.labelMain.height;
						}
					}

					for (var g = 0; g < widgetItem.guiprops.social.items.length; g++) {
						if (widgetItem.guiprops.social.items[g].name === "pinterest") {
							if (!isPinterestLoad) {
								var pinScript = document.createElement('script');
								pinScript.src = "//assets.pinterest.com/js/pinit.js";
								pinScript.setAttribute("async", "");
								pinScript.setAttribute("defer", "");
								document.getElementsByTagName("body")[0].appendChild(pinScript);
								isPinterestLoad = true;
							}
						}
					}

					if (widgetItem.guiprops.formExt && widgetItem.guiprops.formExt.enable && !isExtraScriptsGeneral) {
						isExtraScriptsGeneral = true;
						LeadCore.addGeneralWidgetToSite('datepicker', 'lgwg_date_picker');
						LeadCore.addGeneralWidgetToSite('dropdown', 'lgwg_dropdown');
					}
				} else {
					if (widgetItem.type === 1) {
						if (widgetItem.position === 0) {
							LeadCore.addTopForDot.placeOldLabel = "Нижний правый угол";
							LeadCore.addTopForDot.valueOldLabel = 34;
						}
						if (widgetItem.position === 2) {
							LeadCore.addTopForDot.placeOldLabel = "Нижний левый угол";
							LeadCore.addTopForDot.valueOldLabel = 34;
						}
					}
				}

				if (widgetItem.type.code !== "popup" && widgetItem.type.code !== "containerized") {
					if (LeadCore.isMobile.any()) {
						if (((widgetItem.type === 5 && !isOwnWidgetReady(filtered, "label_widget")) && 
							(widgetItem.type !== 0 && widgetItem.type !== 1 && widgetItem.type !== 2 && widgetItem.type !== 3 && widgetItem.type !==4 )) || 
							widgetItem.guiprops) {
							if (widgetItem.type === 5) {
								LeadCore.addTopForCustomDotMobile = 55;
							}
							filtered.push(widgetItem);
						}
					}
					else if (widgetItem.guiprops || 
						(widgetItem.type !== 5 && widgetItem.type === 0 && !isOwnDotWidgetReadyAndPlace(filtered, widgetItem.position)) || 
						(widgetItem.type !== 5 && widgetItem.type === 1 && !isOwnLabelWidgetReadyAndPlace(filtered, widgetItem.position)) ||
						(widgetItem.type !== 5 && widgetItem.type !== 0 && widgetItem.type !== 1)) {
						filtered.push(widgetItem);
					}
				} else {
					if (!popupLoad && widgetItem.type.code === "popup") {
						popupLoad = true;
						filtered.push(widgetItem);
					}
                    if (!containerizedLoad && widgetItem.type.code === "containerized") {
                    	containerizedLoad = true;
                    	filtered.push(widgetItem);
                    }
				}
				return filtered;
			}, []);


			console.log('wlist ', widgetListForLoad);
			Promise.all(widgetListForLoad.map(_ => LeadCore.loadWidget(_)));
		},
		loadGeo: function() {
			const geoUrl = 'https://leadgenic.ru/g.htm';
			LeadCoreExt.getPromise(geoUrl, true).then((response) => {
				window.localStorage.setItem('LeadgenicVisitorGeo', response);
			});
		},
		checkUrlTags: function() {
			const utmSource   = LGWGService.getURLTag('utm_source');
			const utmMedium   = LGWGService.getURLTag('utm_medium');
			const utmCampaign = LGWGService.getURLTag('utm_campaign');
			const utmTerm     = LGWGService.getURLTag('utm_term');
			const utmContent  = LGWGService.getURLTag('utm_content');
			const referrer    = document.referrer;
			
			if (!!utmSource) {
				LeadCore.setCookie('utm_sourceURL', encodeURIComponent(utmSource), 1);
			}

			if (!!utmMedium) {
				LeadCore.setCookie('utm_mediumURL', encodeURIComponent(utmMedium), 1);
			}

			if (!!utmCampaign) {
				LeadCore.setCookie('utm_campaignURL', encodeURIComponent(utmCampaign), 1);
			}

			if (!!utmTerm) {
				LeadCore.setCookie('utm_termURL', encodeURIComponent(utmTerm), 1);
			}

			if (!!utmContent) {
				LeadCore.setCookie('utm_contentURL', encodeURIComponent(utmContent), 1);
			}

			if (!!referrer) {
				LeadCore.setCookie('referrerURL', encodeURIComponent(referrer), 1);
			}

			LeadCore.setCookie('parameterURL', document.URL, 1);
		},
		loadVisit: function() {
			var url = LeadCore.baseLGURL+"/api/gate/sites/"+LeadCore.siteId+"/visits";
			var visitId;

			var key = LeadCore.getCookie("lgkey");
			var usr = LeadCore.getCookie("lgusr");

			var uTime = new Date();

			var titleOfPage = document.title;
			if (!titleOfPage) {
				titleOfPage = "No title";
			}

			// TODO: Don't forget to remove it

			var data = {
				utime: LeadCore.getUserTime(),
				url: window.location.href || document.URL,
				// url: "http://test-ny.com/",
				title: titleOfPage,
				userAgent: navigator.userAgent,
				refer: document.referrer
			};

			if (key.length > 0 && key !== "undefined") {
				data.key = key;
			}

			var oReq = new XMLHttpRequest();
			oReq.onreadystatechange = function() {
				if (oReq.readyState === 4 && oReq.status === 200) {
					var response = JSON.parse(oReq.responseText).data;
					if (!response) {
						return;
					}

					LeadCore.visit = response;
					
					visitId = response.visitInfo.visitId;
                    LeadCore.currentVisitId = visitId;
                    LeadCore.smartParams = response.smartParams;

                    if (response.visitInfo.actionsCount === 0) {
                    	LeadCore.checkUrlTags();
                    	// LeadCore.loadGeo();
                    }

					LeadCore.setCookie("lgvid", visitId, 0);

					if (key === "undefined" || key.length === 0) {
						if (response.visitInfo.key) {
							LeadCore.setCookie("lgkey", response.visitInfo.key, 1000);
						}
					}

					LeadCore.getPushLeadPath = function(actionId) {
						return LeadCore.baseLGURL + "/api/gate/sites/" + LeadCore.siteId + "/visits/" + visitId + "/leads";
					};

                    LeadCore.pushCreateLeadPromise = function(dParams, sync) {
                        return new Promise(function(resolve, reject) {
                            const oReq = new XMLHttpRequest();

                            const targetUrl = LeadCore.baseLGURL + "/api/gate/sites/" + LeadCore.siteId + "/visits/" + visitId + "/leads";

                            oReq.open("POST", targetUrl, sync);
                            oReq.setRequestHeader('Content-Type', 'application/json; charset=UTF-8');

                            oReq.onload = function() {
                                LeadCore.setActionLockCookie();
                                console.log('SENDDDD');
                                resolve(this.response);
                            };

                            oReq.onerror = function() {
                                reject(new Error("Network Error"));
                            };
                            dParams.pageUrl = window.location.href;

                            oReq.send(JSON.stringify(dParams));
                        });
                    };

					LeadCore.pushTargetAction = function(type, widgetId, callbackFunction) {
						var oReq  = new XMLHttpRequest();
						var uTime = new Date();
						uTime = uTime.getTime();
						var targetUrl = LeadCore.base+"/api/gate/sites/"+LeadCore.siteId+"/visits/"+visitId+"/statistics/";

						var typeSend;
						if (type === 0 || !type) {
							typeSend = "EVENT_OPEN";
						} else if (type === 1) {
							typeSend = "EVENT_TARGET";
							LeadCore.setActionLockCookie();
						}
						var params = {
							type: typeSend,
							timestamp: uTime,
							widgetId: widgetId
						};

						oReq.open("POST", targetUrl, true);
						oReq.setRequestHeader('Content-Type', 'application/json; charset=UTF-8');
						if (typeof callbackFunction !== "undefined") {
							oReq.onreadystatechange = callbackFunction;
						}
						oReq.send(JSON.stringify(params));
					};


					if (LeadCore.visit.socTrackingEnabled) {
						LeadCore.loadSocTracking();
					}

					LeadCore.analyticsParams = LeadCore.visit.analyticsParams;

					let widgetList = [];

					if (LeadCore.visit.widgets.length) {
						LeadWidgets.list = LeadCore.visit.widgets;
						widgetList = widgetList.concat(LeadCore.visit.widgets);
					}
					if (LeadCore.visit.smartPoints.length) {
						LeadCore.activeWidget = 0;
						LeadCore.visit.actions = [];
						LeadCore.widgets = LeadCore.visit.smartPoints;
						widgetList = widgetList.concat(LeadCore.visit.smartPoints);
					}

					if (widgetList.length) {
						LeadCore.loadWidgetsCheck(widgetList);
					}
				}
			};

			oReq.open("POST", url, true);
			oReq.setRequestHeader('Content-Type', 'application/json; charset=UTF-8');
			oReq.send(JSON.stringify(data));
		}
	};

	LeadCore.loadVisit();
})();

(function () {
    const progressMainClass = 'widget-form-multi-progress';
    const progressTitleClass = 'widget-form-multi-progress__title';
    const progressTitleValueClass = 'widget-form-multi-progress__value';
    const progressMeterClass = 'widget-form-multi-progress__meter';
    const hideFirstStepClass = 'hide-first-step';

    class LGMultiFormProgress {
        constructor(progressData, widgetEl) {
            this.dataSettings = {
                ...progressData,
                width: 0,
            };
            this.widgetForm = widgetEl;
        }

        get settings() {
            return this.dataSettings;
        }

        static create(progressData, widgetFormEl) {
        	return new LGMultiFormProgress(progressData, widgetFormEl);
		}

		static getCurrentWidth(currentStep, stepLength, setting) {
            const { isSendLastStep, start, end } = setting;
            const stepListLength = isSendLastStep ? stepLength + 1 : stepLength;
            const step = currentStep + 1;
            return step === 1 ? Math.round(start / end * 100) : Math.round((currentStep + 1) / stepListLength * 100);
        }

		static getMarkup(progressBar, stepLength) {
            const startTitleValue = progressBar.start;
            let barMarkup = "";
            if (progressBar.enable) {
                const animateClass = progressBar.animate ? 'animate' : '';
                const progressValueHideClass = !progressBar.progressValueEnable ? 'hide-show-value' : '';
                const hideOnFirstStepClass = !progressBar.isFirstStep ? hideFirstStepClass : '';
                barMarkup += "<div class=\""+progressMainClass+" "+animateClass+" "+hideOnFirstStepClass+"\">";
                barMarkup += "<div class=\""+progressTitleClass+" "+progressValueHideClass+"\" style=\"font-size:"+progressBar.fontSize+"px;color:"+progressBar.titleColor+";font-family:"+progressBar.font.fontFamily+"\">"+progressBar.title+" "+
                    "<span class=\""+progressTitleValueClass+"\" style=\"color:"+progressBar.barColor+"\"><span>"+startTitleValue+"</span>"+" "+progressBar.progressValueUnit+"</span></div>";
                barMarkup += "<div class=\""+progressMeterClass+"\" style=\"height:"+progressBar.thickness+"px;border-radius:"+progressBar.radius+"px;background:"+progressBar.bgColor+"\"><span style=\"background:"+progressBar.barColor+";width:"+LGMultiFormProgress.getCurrentWidth(0, stepLength, progressBar)+"%\"></span></div>";
                barMarkup += "</div>";
            }
            return barMarkup;
        }

        getMainElement() {
            return this.widgetForm.querySelector('.'+progressMainClass);
        }
        getCurrentValue(currentStep, stepLength) {
        	const { isSendLastStep, start, end } = this.dataSettings;
        	return currentStep === 0 ? start : isSendLastStep
                ? Math.round((end * (currentStep + 1) / (stepLength + 1)) * 10) / 10
                : Math.round((end * (currentStep + 1) / stepLength) * 10) / 10;
		}
        update(currentStep, stepLength) {
        	const mainEl = this.getMainElement();
        	if (!mainEl) return;
        	console.log('currentStep ', currentStep, this.dataSettings);

        	if (currentStep === 0 && !this.dataSettings.isFirstStep) {
                mainEl.classList.add(hideFirstStepClass);
            } else {
                mainEl.classList.remove(hideFirstStepClass);
            }
            const value = this.getCurrentValue(currentStep, stepLength);
            this.dataSettings.width = LGMultiFormProgress.getCurrentWidth(currentStep, stepLength, this.dataSettings);
            mainEl.querySelector('.'+progressMeterClass+' span').style.width = this.dataSettings.width+'%';
            mainEl.querySelector('.'+progressTitleValueClass+' span').innerHTML = value;
        }
        resetToDefault(stepLength) {
            const mainEl = this.getMainElement();
            if (!mainEl) return;
            if (!this.dataSettings.isFirstStep) {
                mainEl.classList.add(hideFirstStepClass);
            }
        	const width = LGMultiFormProgress.getCurrentWidth(0, stepLength, this.dataSettings);
            mainEl.querySelector('.'+progressMeterClass+' span').style.width = width+'%';
            mainEl.querySelector('.'+progressTitleValueClass+' span').innerHTML = this.dataSettings.start;
		}
    }

    class LGMultiFormMain {
        enable;
        previousStepId = [];
        closeFunction;
        redirectFunction;
        sendFormFunction;
        progressBar;
        constructor(formData, formEl, closeBtnEl, widgetId) {
            const { enable, steps, model } = formData;
            if (!enable) return;
            this.widgetId = widgetId;
            this.enable = enable;
            this.steps = steps;
            this.model = model;
            this.widgetForm = formEl;
            this.closeBtnEl = closeBtnEl;
            this.currentStepId = steps[0].stepId;
            this.progressBar = LGMultiFormProgress.create(model.mainSettings.progressBar, formEl);
            this.buttonsExtValues = [];
            this.storedRulesFromPrevSteps = {};
            this.formExtFieldStepList = {}; // model of steps of Array of input fields which should be checked before send a lead
        }

        static create(formData, formEl, closeBtnEl, widgetId) {
            return new LGMultiFormMain(formData, formEl, closeBtnEl, widgetId);
        }

        get isMulti() {
            return this.steps.length > 1;
        }

        get extFieldStepList() {
        	return this.formExtFieldStepList;
		}

        addMethods(_close, _redirect, _sendForm) {
        	this.closeFunction = _close;
        	this.redirectFunction = _redirect;
        	this.sendFormFunction = _sendForm;
		}

		isStepValid() {
            const nextStepNormalId = this.steps.findIndex(_step => _step.stepId === this.currentStepId);
            const currentStepModel = this.steps[nextStepNormalId];
            const paramsToSend = {
                error: false
            };
            const content = {};

            const hiddenFields = currentStepModel.list.filter(item => item.type === 'hidden');
            if (hiddenFields.length) {
                LGWGService.prepareHiddenFields(hiddenFields, content);
            }
            const stepForm = this.widgetForm.querySelector(`#fMultiStep-${this.currentStepId}`);
            const formExtFields = stepForm.querySelectorAll('.form-ext-field');
            LGWGService.checkFormExtFields(formExtFields, paramsToSend, content);
            const hasHiddenInputsError = LGWGService.checkForHidden(this.widgetId);

            return paramsToSend.error || hasHiddenInputsError;
		}

		storeFormExtFieldStepList() {
            const nextStepNormalId = this.steps.findIndex(_step => _step.stepId === this.currentStepId);
            const currentStepModel = this.steps[nextStepNormalId];
            const stepForm = this.widgetForm.querySelector(`#fMultiStep-${this.currentStepId}`);
            const formExtFields = stepForm.querySelectorAll('.form-ext-field');

            console.log(this.steps, currentStepModel, formExtFields);
            this.formExtFieldStepList = {
				...this.formExtFieldStepList,
                [currentStepModel.stepId]: formExtFields,
			};
		}

		storeStepRuleData(btn) {
            this.storedRulesFromPrevSteps[this.currentStepId] = [];
            if (btn) {
                const buttonId = btn.getAttribute('data-id');
                const buttonCustomValue = btn.getAttribute('data-custom');
                const buttonServiceValue = btn.getAttribute('data-service');
                if (!buttonCustomValue) return;
                this.storedRulesFromPrevSteps[this.currentStepId].push({type: 'button', id: buttonId, value: buttonCustomValue, service: buttonServiceValue});
            }

            const nextStepNormalId = this.steps.findIndex(_step => _step.stepId === this.currentStepId);
            const currentStepModel = this.steps[nextStepNormalId];
            const stepForm = this.widgetForm.querySelector(`#fMultiStep-${this.currentStepId}`);
            const formExtFields = stepForm.querySelectorAll('.form-ext-field');

            this.storedRulesFromPrevSteps[this.currentStepId] = this.storedRulesFromPrevSteps[this.currentStepId].concat(LGWGService.storeRuleFields(formExtFields));
        }

		resetToFirstStep() {
			this.previousStepId = [];
            this.currentStepId = this.steps[0].stepId;

            const stepListEl = this.widgetForm.querySelectorAll('.widget-form-multi-step');
            stepListEl.forEach((_el, index) => {
            	_el.classList.remove('hide-left');
            	if (index > 0) {
                    _el.classList.add('hide-right');
				}
			});
            const showStepForm = this.widgetForm.querySelector(`#fMultiStep-${this.currentStepId}`);
            showStepForm.style.transform = `translateX(0%)`;
            this.progressBar.resetToDefault(this.steps.length);
            this.resetButtonExtValues();

            this.formExtFieldStepList = {};
		}

        setButtonExtValue(btn) {
            const buttonId = btn.getAttribute('data-id');
            const buttonCustomValue = btn.getAttribute('data-custom');
            if (!buttonCustomValue) return;
            this.buttonsExtValues.push({id: buttonId, value: buttonCustomValue});
        }

        removeButtonExtValue(btn) {
            this.buttonsExtValues.pop();
        }

        resetButtonExtValues() {
            this.buttonsExtValues = [];
        }

        parseButtonExtValues() {
            return this.buttonsExtValues.reduce((res, item) => {
                res[item.id] = item.value;
                return res;
            }, {});
        }

        nextStepAction(btn) {
            if (this.isStepValid()) return;
            this.storeStepRuleData(btn);
            this.storeFormExtFieldStepList();

            const currentNormalId = this.steps.findIndex(_step => _step.stepId === this.currentStepId);
            let nextStepNormalId = currentNormalId + 1;
            let nextStepId;

            const stepWithSpecialRule = this.steps.slice(nextStepNormalId).find((_step) => {
                const { enable, rule } = _step.settings;
                if (enable) {
                    if (!this.storedRulesFromPrevSteps[rule.stepId]) return false;
                    return this.storedRulesFromPrevSteps[rule.stepId].some((_stepRule) => {
                        if (_stepRule.type !== rule.element.type) return false;
                        if (_stepRule.type === 'button') {
                            return _stepRule.service === rule.element.service && rule.value.includes(_stepRule.value);
                        } else return _stepRule.id === rule.element.id && rule.value.includes(_stepRule.value);
                    });
                }
                return true;
            });

            if (stepWithSpecialRule) {
                nextStepId = stepWithSpecialRule.stepId;
                nextStepNormalId = this.steps.findIndex(_step => _step.stepId === nextStepId);
            }

            if (!nextStepId) return;

            const showStepForm = this.widgetForm.querySelector(`#fMultiStep-${nextStepId}`);
            const currentStepForm = this.widgetForm.querySelector(`#fMultiStep-${this.currentStepId}`);

            this.previousStepId.push(this.currentStepId);
            this.currentStepId = nextStepId;

            currentStepForm.classList.add('hide-left');
            showStepForm.classList.remove('hide-right');

            currentStepForm.style.transform = `translateX(${-100*(nextStepNormalId)}%)`;
            showStepForm.style.transform = `translateX(${-100*(nextStepNormalId)}%)`;
            this.progressBar.update(nextStepNormalId, this.steps.length);
        }

        prevStepAction(btn) {
            if (!this.previousStepId.length) return;
            const nextStepNormalId = this.steps.findIndex(_step => _step.stepId === this.previousStepId[this.previousStepId.length - 1]);
            const nextStepId = this.steps[nextStepNormalId].stepId;
            this.currentStepId = nextStepId;
            this.previousStepId.pop();

            const showStepForm = this.widgetForm.querySelector(`#fMultiStep-${this.currentStepId}`);
            const currentStepForm = btn.closest('.widget-form-multi-step');

            currentStepForm.classList.add('hide-right');
            showStepForm.classList.remove('hide-left');

            currentStepForm.style.transform = `translateX(${-100*(nextStepNormalId)}%)`;
            showStepForm.style.transform = `translateX(${-100*(nextStepNormalId)}%)`;
            this.progressBar.update(nextStepNormalId, this.steps.length);

            // Remove unused this.formExtFieldStepList
            if (this.formExtFieldStepList[this.currentStepId]) {
            	delete this.formExtFieldStepList[this.currentStepId];
			}
        }

        initInputForm() {
            const formExtInputFields = this.widgetForm.querySelectorAll('.form-ext-input-field');
            formExtInputFields.forEach((_input) => {
                if (_input.classList.contains('form-cntrl-phone')) {
                	let phoneInputModel;
                    this.steps.some((_step) => {
                        phoneInputModel = _step.list.filter(function(item) {return item.type === 'phone'});
                        return !!phoneInputModel.length;
					});
                    if (phoneInputModel.length && phoneInputModel[0].mask && phoneInputModel[0].mask.enable) {
                        new phoneMaskFieldClass(_input, phoneInputModel[0].mask.value.replace(/\*/g,'_'));
                    } else {
                        _input.addEventListener('focus', function() {
                            this.classList.remove('form-control-error');
                            this.closest('.form-ext-field').classList.remove('form-control-error');
                            this.onkeypress = function(e) {
                                if (e.keyCode == 8) {
                                    return true;
                                }
                                return !(/[^+0-9---() ]/.test(String.fromCharCode(e.charCode)));
                            }
                        });
                    }
                }
                else {
                    _input.addEventListener('focus', function() {
                        this.classList.remove('form-control-error');
                        this.closest('.form-ext-field').classList.remove('form-control-error');
                    });
                }
			});
		}

        initButtonHandler() {
            if (!this.enable) return;
            const formExtButtons = this.widgetForm.querySelectorAll('.form-ext-button');

            formExtButtons.forEach((_btn) => {
                const _this = this;
                if (_btn.classList.contains('form-ext-button-type2') && this.closeBtnEl) {
                    this.closeBtnEl.classList.add("lgwg-none-imp-forever");
                }

                _btn.addEventListener('click', function(e) {
                    const btn = this;

                    if (btn.classList.contains('form-ext-button-type0')) {
                        if (_this.isStepValid()) return;
                        _this.setButtonExtValue(btn);
                        _this.storeFormExtFieldStepList();
                        _this.sendFormFunction(btn, _this.parseButtonExtValues()).then(() => {
                        	_this.resetToFirstStep();
                        });
                        return;
                    } else if (btn.classList.contains('form-ext-button-type1')) {
                        // Send Form and Redirect
                        if (_this.isStepValid()) return;
                        var redirectData = {
                            blank: btn.classList.contains('form-ext-button-redirect-blank-true'),
                            url: btn.getAttribute('data-url')
                        };
                        _this.setButtonExtValue(btn);
                        _this.storeFormExtFieldStepList();
                        _this.sendFormFunction(btn, _this.parseButtonExtValues(), redirectData).then(() => {
                            _this.resetToFirstStep();
                        });
                        return;
                    } else if (btn.classList.contains('form-ext-button-type2')) {
                        _this.closeFunction(btn).then(() => {
                            _this.resetToFirstStep();
                        });
                        e.stopPropagation();
                        e.preventDefault();
                        return;
                    } else if (btn.classList.contains('form-ext-button-type3')) {
                        _this.redirectFunction(btn).then(() => {
                            _this.resetToFirstStep();
                        });
                        return;
                    } else if (btn.classList.contains('form-ext-button-type4')) {
                        // Show next step
                        _this.setButtonExtValue(btn);
                        _this.nextStepAction(btn);
                        return;
                    } else if (btn.classList.contains('form-ext-button-type5')) {
                        // Show prev step
                        _this.removeButtonExtValue(btn);
                        _this.prevStepAction(btn);
                    }
                });
            });
        }

        inputHandlerAction(containerAction, isStep) {
            if (!containerAction.length) {
                return;
            }
            const _this = this;
            containerAction.forEach(function(item) {
                //Rating action
                if (item.classList.contains('form-ext-type-rating')) {
                    const ratingInput = item.querySelector('.rating-click-container');
                    if (!ratingInput) return;

                    ratingInput.addEventListener('click', function() {
                        item.classList.remove('form-control-error');
                        if (_this.isStepValid()) return;
                        if (isStep) {
                            _this.nextStepAction()
						} else {
                            _this.storeFormExtFieldStepList();
                            _this.sendFormFunction(null, _this.parseButtonExtValues()).then(() => {
                                _this.resetToFirstStep();
                            });
						}
                    });
                }

                //Variants action
                if (item.classList.contains('form-ext-type-variants')) {
                    const checkBoxInputs = item.querySelector('.form-ext-checkbox-wrapper');
                    const isMultiSelect = item.classList.contains('form-ext-multi-true');
                    if (isMultiSelect) return;
                    checkBoxInputs.addEventListener('click', function(e) {
                        if (_this.isStepValid()) return;
                        if (e.target && e.target.checked) {
                            if (isStep) {
                                _this.nextStepAction()
                            } else {
                                _this.storeFormExtFieldStepList();
                                _this.sendFormFunction(null, _this.parseButtonExtValues()).then(() => {
                                    _this.resetToFirstStep();
                                });
                            }
                        }
                    });
                }

                //DD action
                if (item.classList.contains('form-ext-type-dd')) {
                    const ddInput = item.querySelector('.form-control');

                    ddInput.addEventListener('change', function(e) {
                        setTimeout(function() {
                            if (_this.isStepValid()) return;
                            if (e.target.value) {
                                if (isStep) {
                                    _this.nextStepAction()
                                } else {
                                    _this.storeFormExtFieldStepList();
                                    _this.sendFormFunction(null, _this.parseButtonExtValues()).then(() => {
                                        _this.resetToFirstStep();
                                    });
                                }
                            }
                        }, 100);
                    });
                }
            });
        }

        initInputHandler() {
            const formExtSendFormOnAction = this.widgetForm.querySelectorAll('.form-ext-send-form-on-action-true');
            this.inputHandlerAction(formExtSendFormOnAction);

            const formExtNextStepOnAction = this.widgetForm.querySelectorAll('.form-ext-next-step-on-action-true');
            this.inputHandlerAction(formExtNextStepOnAction, true);
        }
    }

    LGMulti = {
        getProgressBarMarkup: function(progressBarData, stepLength) {
            return LGMultiFormProgress.getMarkup(progressBarData, stepLength);
        },
    	getProgressBarInstance: function(progressBarData, widgetFormEl) {
    		return LGMultiFormProgress.create(progressBarData, widgetFormEl);
		},
        getFormInstance: function(formData, widgetFormEl, closeBtnEl, widgetId) {
            return LGMultiFormMain.create(formData, widgetFormEl, closeBtnEl, widgetId);
        },
	};
})();


/*************************************************************************
 *Waves active btn
 */
function waveActBtnB(block) {
	block.classList.add('lg-wg-an-wave-white');
	setTimeout(function() {
		block.classList.add('lg-wg-an-wave-blue-2');
	}, 300);
	setTimeout(function() {
		block.classList.remove('lg-wg-an-wave-white');
		block.classList.remove('lg-wg-an-wave-blue-2');
	}, 350);
}
function waveActBtnG(block) {
	block.classList.add('lg-wg-an-wave-white');
	setTimeout(function() {
		block.classList.add('lg-wg-an-wave-green-2');
	}, 300);
	setTimeout(function() {
		block.classList.remove('lg-wg-an-wave-white');
		block.classList.remove('lg-wg-an-wave-green-2');
	}, 350);
}


/*************************************************************************
 *Validate phone input
 */
function validPhoneInput(input) {
	var re = /^[\d\+\(\)\ -]{4,17}\d$/;
	var valid = re.test(input);
	return valid;
}

/*************************************************************************
 *Validate email input
 */
function validEmailInput(input) {
	var r = /^([a-z0-9_-]+\.)*[a-z0-9_-]+@[a-z0-9_-]+(\.[a-z0-9_-]+)*\.[a-z]{2,6}$/i;
	var valid = r.test(input);
	return valid;
}


/*************************************************************************
 *Find closest tag
 */
function closest(el, selector) {
	var matches = el.webkitMatchesSelector ? 'webkitMatchesSelector' : (el.msMatchesSelector ? 'msMatchesSelector' : 'matches');

	while (el.parentElement) {
		if (el[matches](selector)) return el;

		el = el.parentElement;
	}

	return null;
}

/*************************************************************************
 *Send request
 */
function sendRequestLGWG(data, blockOpen, blockClose, btn, closeFunc, interval) {
	if (!data.email) {
		delete data.email;
	}
	var roistatIdNew = LeadCore.getCookie("roistat_visit");
	if (roistatIdNew) {
		data.roistatId = roistatIdNew;
	}
	var tInterval = interval || 5000;

	var xhr = new XMLHttpRequest();

	btn.classList.remove('lg-wg-an-wave-ef-b');
	btn.classList.remove('lg-wg-an-wave-ef-g');
	btn.classList.add('lg-wg-sub-go');
	xhr.open("POST", LeadCore.getPushLeadPath("sendWidgetForm"));

	xhr.setRequestHeader('Content-Type', 'application/json; charset=UTF-8');

	xhr.onload = function() {
		LeadCore.setActionLockCookie();
		blockClose.classList.add('lg-wg-form-none');
		setTimeout(function () {
			blockOpen.classList.remove('lg-wg-form-none');
		}, 500);
		setTimeout(function () {
			blockOpen.classList.add('lg-wg-visib');
		}, 550);
		btn.classList.add('lg-wg-an-wave-ef-b');
		btn.classList.remove('lg-wg-sub-go');
		LeadCore.setCookie('lg-wg-sended', LeadCore.siteId, 7);
		setTimeout(closeFunc, tInterval);
	};

	data.pageUrl = window.location.href;
	xhr.send(JSON.stringify(data));

}


function _instanceof(left, right) { if (right != null && typeof Symbol !== "undefined" && right[Symbol.hasInstance]) { return right[Symbol.hasInstance](left); } else { return left instanceof right; } }

function _classCallCheck(instance, Constructor) { if (!_instanceof(instance, Constructor)) { throw new TypeError("Cannot call a class as a function"); } }

function _defineProperties(target, props) { for (var i = 0; i < props.length; i++) { var descriptor = props[i]; descriptor.enumerable = descriptor.enumerable || false; descriptor.configurable = true; if ("value" in descriptor) descriptor.writable = true; Object.defineProperty(target, descriptor.key, descriptor); } }

function _createClass(Constructor, protoProps, staticProps) { if (protoProps) _defineProperties(Constructor.prototype, protoProps); if (staticProps) _defineProperties(Constructor, staticProps); return Constructor; }

var phoneMaskFieldClass =
/*#__PURE__*/
function () {
	/***
	 handler = the DOM object
	 mask = any preferrable phone mask
	 placeholder = character used to fill the space when char is deleted
	 start = the position of the first num character user can enter
	 ***/
	//mask = '+7(___)___-____'
	function PhoneMaskField(handler, mask) {
		var _this = this;

		var placeholder = arguments.length > 2 && arguments[2] !== undefined ? arguments[2] : '_';

		_classCallCheck(this, PhoneMaskField);

		this.handler = handler;
		this.mask = mask;
		this.placeholder = placeholder;
		this.placeholderPos = 1; //set the length

		this.setLength(); //set value to placeholder

		this.setValue(); //check where is the first enerable character index

		this.start = this.placeHolderPosition() - 1; //focused - move carette to the first placeholder

		this.handler.addEventListener('focusin', function () {
			_this.focused();
		});
		this.handler.addEventListener('focusout', function () {
			if (_this.mask === _this.handler.value) {
				_this.removeValue();

				_this.handler.classList.remove("masked");
			}
		}); //keydown - check key/remove placeholder/push numbers further or do nothing

		this.handler.addEventListener('keydown', function (e) {
			_this.input(e);
		});
		this.removeValue();
	}

	_createClass(PhoneMaskField, [{
		key: "focused",
		value: function focused() {
			if (this.mask === this.handler.value || !this.handler.value) {
				this.setValue();
				this.handler.classList.add("masked");
			}

			this.placeholderPos = this.placeHolderPosition();
			var el = this.handler;
			var pos = this.placeholderPos;
			setTimeout(function () {
				if (el.setSelectionRange) {
					el.setSelectionRange(pos, pos);
				} else {
					// IE
					var range = el.createTextRange();
					range.collapse(true);
					range.moveEnd("character", pos);
					range.moveStart("character", pos);
					range.select();
				}
			}, 10);
		}
	}, {
		key: "input",
		value: function input(e) {
			//unless it is a tab, prevent action
			if (!this.isDirectionKey(e.key)) {
				e.preventDefault();
			} //if integer, enter it


			if (this.isNum(e.key)) {
				this.changeChar(e.key);
			} //if user deletes, delete a number
			else if (this.isDeletionKey(e.key)) {
				if (e.key === 'Backspace') {
					var index = this.start;
					var dir = -1;
					this.changeChar(this.placeholder, dir, index);
				} else {
					this.changeChar(this.placeholder);
				}
			}
		} //put max length to the length of the mask

	}, {
		key: "setLength",
		value: function setLength() {
			this.handler.maxLength = this.mask.length;
		} //set initial value

	}, {
		key: "setValue",
		value: function setValue() {
			this.handler.value = this.mask;
		}
	}, {
		key: "removeValue",
		value: function removeValue() {
			this.handler.value = "";
		} //check if input is number

	}, {
		key: "isNum",
		value: function isNum(i) {
			return !isNaN(i) && parseInt(Number(i)) == i && !isNaN(parseInt(i, 10));
		} //check if it is a button to delete stuff

	}, {
		key: "isDeletionKey",
		value: function isDeletionKey(i) {
			return i === 'Delete' || i === 'Backspace';
		} //check if direction arrow

	}, {
		key: "isDirectionKey",
		value: function isDirectionKey(i) {
			return i === 'ArrowUp' || i === 'ArrowDown' || i === 'ArrowRight' || i === 'ArrowLeft' || i === 'Tab';
		}
	}, {
		key: "isPlaceholder",
		value: function isPlaceholder(i) {
			return i == this.placeholder;
		}
	}, {
		key: "placeHolderPosition",
		value: function placeHolderPosition() {
			return this.handler.value.indexOf(this.placeholder);
		}
	}, {
		key: "changeChar",
		value: function changeChar(i) {
			var dir = arguments.length > 1 && arguments[1] !== undefined ? arguments[1] : 1;
			var max = arguments.length > 2 && arguments[2] !== undefined ? arguments[2] : this.mask.length;
			var val = this.handler.value;
			var pos = this.placeholderPos > -1 ? this.placeholderPos : this.handler.selectionStart;

			if (dir === -1) {
				pos = this.handler.selectionStart - 1;
			}

			var newVal = ''; //if cursor at end, do nothing

			if (pos === max) {
				return false;
			}
			

			if (!this.isNum(val[pos]) && !this.isPlaceholder(val[pos])) {
				do {
					pos += dir; //if cursor at end, do nothing

					if (pos === max) {
						return false;
					}
				} while (!this.isNum(val[pos]) && !this.isPlaceholder(val[pos]));
			} //replace char at index


			newVal = this.replaceAt(val, pos, i); //update the value in the field

			this.handler.value = newVal; //move the caret if direction is forward

			if (dir > 0) pos += dir;
			this.placeholderPos = this.placeHolderPosition();
			this.handler.selectionStart = pos;
			this.handler.selectionEnd = pos;
		}
	}, {
		key: "replaceAt",
		value: function replaceAt(str, pos, val) {
			return str.substring(0, pos) + val + str.substring(++pos);
		}
	}]);

	return PhoneMaskField;
}();


(function () {
	LGWGService = {
		checkCookieLockRestrictions: (cookieRestriction) => {
			if (!cookieRestriction.name) {
				return true;
			}
			const lockCookie = LeadCore.getCookie(cookieRestriction.name);
			if (!lockCookie.length) {
				return true;
			}
			if (!cookieRestriction.value) {
				return false;
			}
			return lockCookie.indexOf(cookieRestriction.value) < 0;
		},
		checkPagesLockRestrictions: (pageRestriction, cName) => {
			if (pageRestriction && pageRestriction.enable) {
				const sitePages = window.location.pathname.split('/');
				const parsedURLs = pageRestriction.url.map(_ => _.value.split('/').slice(-1)[0]);
				// const isVisitedPage = parsedURLs.some(_ => sitePages.indexOf(_) > -1);
                const isVisitedPage = parsedURLs.some(_ => sitePages.some(_item => _item.indexOf(_) > -1));
				if (isVisitedPage) {
					LeadCore.setCookie(cName, LeadCore.siteId, (pageRestriction.gap / 24));
				}
			}
		},
		checkTargetLock: (targetSettings, cookieLabel) => {
			if (targetSettings.mode === 2) {
				LeadCore.setCookie(cookieLabel, LeadCore.siteId, 1095);
			}
			if (targetSettings.mode === 0) {
				LeadCore.setCookie(cookieLabel, LeadCore.siteId, (targetSettings.gap / 24));
			}
		},
		checkAutoInviteLock: (autoinviteLockSettings, cookieLabel) => {
			if (autoinviteLockSettings.enable) {
				LeadCore.setCookie(cookieLabel, LeadCore.siteId, (autoinviteLockSettings.gap / 24));
			}
		},
		setOpacityForBg: function(bgSettings) {
			return typeof bgSettings.opacity !== 'undefined' ? bgSettings.opacity : '1';
		},
		getBorderStyle: function(bgSettings) {
			if(bgSettings.border && bgSettings.border.enable && bgSettings.border.style) {
				return bgSettings.border.style;
			} else {
				return '0px solid transparent';
			}
		},
		getInnerBorderStyle: function(bgSettings) {
			if(bgSettings.border && bgSettings.border.enable && bgSettings.border.style && bgSettings.border.thickness && bgSettings.borderRadius) {
				return (bgSettings.borderRadius - bgSettings.border.thickness + 1) + 'px';
			} else {
				return '0';
			}
		},
		getBoxShadowStyle: function(bgSettings) {
			if (!bgSettings.shadow) {
				return "0px 1px 5px 0px rgba(0,0,0,0.25)";
			}
			if (bgSettings.shadow && bgSettings.shadow.enable && bgSettings.shadow.style) {
				return bgSettings.shadow.style;
			}
			if (bgSettings.shadow && !bgSettings.shadow.enable) {
				return "0px 1px 5px 0px rgba(0,0,0,0)";
			}
		},
		isFormBorder: function(item) {
			return item.border.enable ? 'widget-input-border' : '';
		},
		getVideoImageWidth: function(item) {
			if ((window.screen.availWidth <= 760) && LeadCore.isMobile.any()) {
				if (item.width_type === LeadCore.constants.fromStoS) {
					return item.widthpx + "px";
				} else {
					if (item.widthpx > (window.screen.availWidth - 38)) {
						return "100%";
					} else {
						return item.widthpx + "px";
					}
				}
			} else {
				return item.widthpx + "px";
			}
		},
        getImageBorderRadius: function(radius) {
            return radius || 0;
        },
		getVideoHeight: function(item, dhVisual) {
			if ((window.screen.availWidth <= 760) && LeadCore.isMobile.any()) {
				if (item.width_type === LeadCore.constants.fromStoS) {
					return ((window.screen.availWidth - 38)/1.666);
				} else {
					if (item.widthpx > (window.screen.availWidth - 38)) {
						return ((window.screen.availWidth - 38)/1.666);
					} else {
						return (item.widthpx/1.666);
					}
				}
			} else {
				if (item.width_type === LeadCore.constants.fromStoS) {
					return ((dhVisual.widget_ul_width_nopx - 1)/1.666);
				} else {
					return (item.widthpx/1.666);
				}
			}
		},
		hrPosSel: function(item) {
		    var className = '';

		    if (item.position === LeadCore.constants.onCenter)
		        className = 'widget1-hr-center';

		    if (item.position === LeadCore.constants.fromRight)
		        className = 'widget1-hr-right';

		    if (item.position === LeadCore.constants.fromLeft)
		        className = 'widget1-hr-left';

		    if (item.width_type === LeadCore.constants.fromStoS)
		        className += ' widget1-hr-full-w';

		    if (item.width_type === LeadCore.constants.ownValue)
		        className += ' widget1-hr-user-w';

		    if (item.width_type === LeadCore.constants.auto)
		        className += ' widget1-hr-auto-w';

		    return className;
		},
		getHRThickness: function(item) {
			if (item.thickness === undefined) {
				if (item.type === '2') {
					return 3;
				}
				if (item.type === '5' || item.type === '6') {
					return 2;
				}
				return 1;
			} else {
				return item.thickness;
			}
		},
		getAlignOfCloseLink: function(item) {
			return !item.position ? 'widget1-hr-center' : LGWGService.hrPosSel(item);
		},
		getWholeFormWidth: function(item) {
			return item.form_widthpx || 200;
		},
		hrPosSelWholeForm: function(item) {
		    var className = '';
		    if (!item.form_position || !item.form_width_type) {
		    	return 'widget1-w-hr-left widget1-w-hr-full-w';
		    }

		    if (item.form_position === LeadCore.constants.onCenter)
		        className = 'widget1-w-hr-center';

		    if (item.form_position === LeadCore.constants.fromRight)
		        className = 'widget1-w-hr-right';

		    if (item.form_position === LeadCore.constants.fromLeft)
		        className = 'widget1-w-hr-left';

		    if (item.form_width_type === LeadCore.constants.fromStoS)
		        className += ' widget1-w-hr-full-w';

		    if (item.form_width_type === LeadCore.constants.ownValue)
		        className += ' widget1-w-hr-user-w';

		    return className;
		},
		heightIfrmPosSel: function(item) {
		    var className = '';

		    if (item.height_type === LeadCore.constants.auto)
		        className += ' widget1-hrh-full-w';

		    if (item.height_type === LeadCore.constants.ownValue)
		        className += ' widget1-hrh-user-w';

		    return className;
		},
		classNameFormInputMask: function(type, mask) {
			return (type === "phone" && mask && mask.enable) ? '' : '';
		},
		classNameInputItem: function(item, orient) {
		    var className = '';

		    if (orient === LeadCore.constants.horizontal) {
		        if (item.type === 'message') {
		            className = 'widget-input-gorizontal-textar';
		        }
		        else {
		            className = 'widget-input-gorizontal';
		        }
		    }
		    else {
		       if (item.type === 'message') {
		            className = 'widget-input-vert-textar';
		        }
		    }

		    return className;
		},
		classNameVerticalOrient: function(dhVisual) {
		    var className = '';

		    if (dhVisual.widget_content_height === LeadCore.constants.ownValue) {
		        if (dhVisual.widget_content_height_orient === LeadCore.constants.fromBottomBorder)
		            className = 'widget-main-ul-bottom';

		        if (dhVisual.widget_content_height_orient === LeadCore.constants.onCenterWidget)
		            className = 'widget-main-ul-center';
		    } else {
		    	className = 'widget-main-ul-auto';
		    }

		    return className;
		},
		hrPosSelForm: function(item) {
		    var className = '';

		    if (item.width_type === LeadCore.constants.fromStoS)
		        className += ' widget1-hr-full-w';

		    if (item.width_type === LeadCore.constants.ownValue)
		        className += ' widget1-hr-user-w';

		    return className;
		},
		btnWidthSel: function(item) {
		    var className = '';

		    if (item.btn_width === LeadCore.constants.fromStoS)
		        className = 'button-full-width';

		    if (item.btn_width === LeadCore.constants.ownValue)
		        className = 'button-user-width';

		    if (item.btn_width === LeadCore.constants.auto)
		        className = 'button-auto-width';

		    return className;
		},
		btnPosSel: function(visualObj) {
		    var className = '';

		    if (visualObj.button.position === LeadCore.constants.onCenter)
		        className = 'widget1-btn-bl-center';

		    if (visualObj.button.position === LeadCore.constants.fromRight)
		        className = 'widget1-btn-bl-right';

		    if (visualObj.dhVisual.place === LeadCore.constants.fromLeft)
		        className = 'widget1-btn-bl';

		    return className;
		},
		btnExitPosSel: function(item, place) {
		    var className = '';

		    if (item.position === LeadCore.constants.onCenter)
		        className = 'widget1-btn-bl-center';

		    if (item.position === LeadCore.constants.fromRight)
		        className = 'widget1-btn-bl-right';

		    if (place === LeadCore.constants.fromLeft)
		        className = 'widget1-btn-bl';

		    return className;
		},
		btnStyleSel: function(item) {
		    var className = '';

		    if(item.styleType) {
			    if (item.styleType === 'Border Style')
			        className = 'widget-btn-border-style-none-bg';

			    if (item.styleType === 'Material')
			        className = 'widget-btn-style__material widget-btn-border-style-none-border';

			    if (item.styleType === 'Flat')
			        className = 'widget-btn-style__flat widget-btn-border-style-none-border';

			    if (item.styleType === 'Default')
			        className = 'widget-btn-border-style-none-border';
		    }

		    return className;
		},
		isTextEnable: function(item) {
			return !item.enable ? " lgwg-none" : "";
		},
		isTextShadow: function(item) {
			return !item.textShadow.enable ? 'no-text-shadow-imp' : '';
		},
		hexToRgb: function(r,t) {
			var n=/^#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i.exec(r),a=function(){return void 0==this.alpha?"rgb("+this.r+", "+this.g+", "+this.b+")":(this.alpha>1?this.alpha=1:this.alpha<0&&(this.alpha=0),"rgba("+this.r+", "+this.g+", "+this.b+", "+this.alpha+")")};return void 0==t?n?{r:parseInt(n[1],16),g:parseInt(n[2],16),b:parseInt(n[3],16),toString:a}:null:(t>1?t=1:0>t&&(t=0),n?{r:parseInt(n[1],16),g:parseInt(n[2],16),b:parseInt(n[3],16),alpha:t,toString:a}:null)
		},
		isObjectEmpty: function(obj) {
			for(var prop in obj) {
				if(Object.prototype.hasOwnProperty.call(obj, prop)) {
					return false;
				}
			}
			return JSON.stringify(obj) === JSON.stringify({});
		},
		getRGBAColor: function(item) {
		    return (LGWGService.hexToRgb(item.textShadow.color, item.textShadow.opacity)).toString();
		},
		getRGBAColorItems: function(color, opacity) {
		    return (LGWGService.hexToRgb(color, opacity)).toString();
		},
		getCouponRGBABG: function(item) {
		    return (LGWGService.hexToRgb(item.color, item.opacity)).toString();
		},
		setWideOrNarrowBgStyle: function(dhVisual) {
			if ((dhVisual.widget_width_nopx !== 0) && (dhVisual.widget_height_nopx !== 0)) {
		        if ((dhVisual.widget_width_nopx/dhVisual.widget_height_nopx) >= (16/9)) {
		            return "wide-video-bg-ext";
		        } else {
		            return "narrow-video-bg-ext"; 
		        }
		    }

		    return "";
		},
		redirectParams: function(data, redirectUrl) {
			var EMAIL_CONST = '{email}',
			    PHONE_CONST = '{phone}',
			    NAME_CONST = '{name}',
			    MESSAGE_CONST = '{message}';

			var url = redirectUrl;

			if(!data) {
				if(url.indexOf('?') !== -1 && (url.indexOf(EMAIL_CONST)!== -1 || url.indexOf(PHONE_CONST) !== -1 || url.indexOf(NAME_CONST) !== -1 || url.indexOf(MESSAGE_CONST) !== -1)) {
					url = url.substr(0, url.indexOf('?'));
				}
				return url;
			}

			if (data.customFields && !LGWGService.isObjectEmpty(data.customFields && data.helpData && !LGWGService.isObjectEmpty(data.helpData)) ) {
				Object.keys(data.customFields).forEach(fieldItem => {
					const urlKey = `{${data.helpData[fieldItem]}}`;
					if (url.indexOf(urlKey) !== -1) {
						const pattern = new RegExp(urlKey, "g");
						url = url.replace(pattern, data.customFields[fieldItem]);
					}
				});
			}

			if(url.indexOf(EMAIL_CONST) !== -1 && data.email) {
				url = url.replace(EMAIL_CONST, data.email);
			}

			if(url.indexOf(PHONE_CONST) !== -1 && data.phone) {
				url = url.replace(PHONE_CONST, encodeURIComponent(data.phone));
			}

			if(url.indexOf(NAME_CONST) !== -1 && data.firstName) {
				url = url.replace(NAME_CONST, encodeURIComponent(data.firstName));
			}

			if(url.indexOf(MESSAGE_CONST) !== -1 && data.comment) {
				url = url.replace(MESSAGE_CONST, encodeURIComponent(data.comment));
			}

			return url;
		},
		getTopValueOfColorPod: function(LGWGNewDotformBlock, LGWGNewDotButtonBlock, visualObj, LGWGNewDotFormExtBlock, isPopup) {
			const getOffsetForElement = (element) => {
				const { transform } = getComputedStyle(element.closest('li'));
				if (transform) {
					const { m42 } = new WebKitCSSMatrix(transform);
					return m42;
				}
				return 0;
			};
			var offsetPadding = 6;
		    var topOfColorPod = 0;

			if (LGWGNewDotformBlock) {
				if (visualObj.form.orient === LeadCore.constants.vertical) {
		            offsetPadding = - 8;
		        }
		        topOfColorPod = LGWGNewDotformBlock.getBoundingClientRect().top - 20 + offsetPadding - getOffsetForElement(LGWGNewDotformBlock);
			} else if (LGWGNewDotButtonBlock) {
				offsetPadding = 8;
				topOfColorPod = LGWGNewDotButtonBlock.getBoundingClientRect().top - 20 - offsetPadding - getOffsetForElement(LGWGNewDotButtonBlock);
			} else if (LGWGNewDotFormExtBlock) {
				topOfColorPod = LGWGNewDotFormExtBlock.getBoundingClientRect().top - 12 - offsetPadding - getOffsetForElement(LGWGNewDotFormExtBlock);
				if (isPopup) {
					topOfColorPod = topOfColorPod - 10;
				}
			}

			if (visualObj.bg.border && visualObj.bg.border.enable) {
		        topOfColorPod = topOfColorPod - visualObj.bg.border.thickness;
		    }
			
			return topOfColorPod;
		},
		// Rating
        getPosition: function(e, offsetLeft) {
        	var WIDGET_PADDING = 0;
            return e.pageX - WIDGET_PADDING - offsetLeft;
        },
        getDecimalPlaces: function(num) {
            var match = ("" + num).match(/(?:\.(\d+))?(?:[eE]([+-]?\d+))?$/);
            return !match ? 0 : Math.max(0, (match[1] ? match[1].length : 0) - (match[2] ? +match[2] : 0));
        },
        applyPrecision: function(val, precision) {
            return parseFloat(val.toFixed(precision));
        },
        getValueFromPosition: function(pos, target, maxStars) {
            var self = {
                min: 0,
                step: 1
            };
            var precision = LGWGService.getDecimalPlaces(self.step),
                val, factor, maxWidth = target.offsetWidth - 2;
            
            factor = ((maxStars - self.min) * pos) / (maxWidth * self.step);
            factor = Math.ceil(factor);
            
            val = LGWGService.applyPrecision(parseFloat(self.min + factor * self.step), precision);
            val = Math.max(Math.min(val, maxStars), self.min);
           
            return val;
        },
        getWidthFromValue: function(val, maxStars) {
            if (val >= maxStars) {
                return 100;
            }
            return val * 100 / maxStars;
        },
        calculate: function(pos, target, maxStars) {
            var val = LGWGService.getValueFromPosition(pos, target, maxStars);
            var width = LGWGService.getWidthFromValue(val, maxStars);
            
            width += "%";
            return { width: width, value: val };
        },
        setStars: function(pos, target, item) {
            var out = LGWGService.calculate(pos, target, target.dataset.content.length);
            if (target.nextElementSibling) {
            	target.nextElementSibling.style.width = out.width;
            }
            target.dataset.cacheWidth = out.width;
            target.dataset.cacheValue = out.value;
        },
        hoverStars: function(w, target) {
        	if (!target) return;
            target.style.width = w;
        },
        ratingStarClicked: function(e) {
        	var viewPortParent = e.target.parentElement.getBoundingClientRect();
            var pos = LGWGService.getPosition(e, viewPortParent.left);
            LGWGService.setStars(pos, e.target);
            e.target.dataset['starClicked'] = true;
        },
        ratingStarMoved: function(e) {
            e.target.dataset['starClicked'] = false;
            var viewPortParent = e.target.parentElement.getBoundingClientRect();
            
            var pos = LGWGService.getPosition(e, viewPortParent.left);
            var out = LGWGService.calculate(pos, e.target, e.target.dataset.content.length);
            
            LGWGService.hoverStars(out.width, e.target.nextElementSibling);
        },
        ratingStarLeaved: function(e) {
            if (e.target.dataset['starClicked'] && e.target.dataset['starClicked'] === 'true') return;

            var cacheW = e.target.dataset.cacheWidth || "0%";
            LGWGService.hoverStars(cacheW, e.target.nextElementSibling);
        },
		ratingStars: function(item) {
            var content = "";
            var star = "\ue819";
            for (var i = 1; i <= item.numberOfStars; i++) {
                content += star;
            }
            return content;
        },
        ratingType: function(item) {
			return item.fieldType && item.fieldType.type ? item.fieldType.type : 'rating';
		},
        setRatingItem: function(pos, target, item) {
            var out = LGWGService.calculate(pos, target, target.dataset.content.length);
            if (target.nextElementSibling) {
                target.nextElementSibling.style.width = out.width;
            }
            target.dataset.cacheWidth = out.width;
            target.dataset.cacheValue = out.value;
        },
        ratingItemClicked: function(e) {
			const clickValue = e.target.dataset['value'];
			if (!clickValue) return;
            const parent = e.target.parentElement;
            parent.dataset.cacheValue = clickValue;
            const items = parent.querySelectorAll('.selected');
            items.forEach(_item => {
                _item.classList.remove('selected');
            });
			e.target.classList.add('selected');
        },
        emojiItemClicked: function(e) {
            const clickValue = e.dataset['value'];
            if (!clickValue) return;
            const parent = e.parentElement;
            parent.dataset.cacheValue = clickValue;
            const items = parent.querySelectorAll('.selected');
            items.forEach(_item => {
                _item.classList.remove('selected');
            });
            e.classList.add('selected');
        },
		removeEmojiSelected: function(ratings) {
            for (var i = 0; i < ratings.length; i++) {
            	delete ratings[i].dataset.cacheValue;
                const items = ratings[i].getElementsByClassName('rating-item');
                for (let k = 0; k < items.length; k++) {
                    const currentItem = items[k];
                    currentItem.classList.remove('selected');
                }
            }
		},
        getBGColor: function(formSettings) {
        	return formSettings.border.enable ? formSettings.border.color : formSettings.colorTitleInputForm;
        },
        // END Rating
        getVariantsMarkup: function(elementModel, formSettings) {
        	var variantsMarkup = "";
        	var variantInputM = elementModel.multiEnable ? "<input type=\"checkbox\">" : "<input type=\"radio\" name=\"radio-"+elementModel.id+"\">";
        	var variantLabelM = elementModel.multiEnable ? 
	        	"<span class=\"form-ext-checkbox-checkmark\" style=\"background-color:"+formSettings.rgbaInputForm+";border-color:"+(formSettings.border.enable ? formSettings.border.color : 'transparent')+"\"></span>" : 
	        	"<span class=\"form-ext-checkbox-checkmark-radio\" style=\"background-color:"+formSettings.rgbaInputForm+";border-color:"+(formSettings.border.enable ? formSettings.border.color : 'transparent')+"\"></span>";
        	
        	for (var f = 0; f < elementModel.variants.length; f++) {
        		var fVariant = elementModel.variants[f];

        		variantsMarkup += "<label class=\"form-ext-checkbox-container\" style=\"font-size:"+elementModel.fontSize+"px;font-family:"+elementModel.font.fontFamily+";color:"+elementModel.colorText+"\">"+
        							fVariant+
        							"<div style=\"background-color:"+LGWGService.getBGColor(formSettings)+";border-color:"+LGWGService.getBGColor(formSettings)+"\">"+
        						  		variantInputM+
        						  		variantLabelM+
    						  		"</div>"+
    						  "</label>";
        	}
        	return variantsMarkup;
        },
		getRatingMarkup: function(fElement) {
            if (fElement.fieldType && fElement.fieldType.type) {
            	if (fElement.fieldType.type === 'emoji') {
                    return "<div class=\"emoji-container rating-click-container\">"+
                        "<div data-value=\"Ужасно\" class=\"emoji-item rating-item\"><img src=\"https://app.leadgenic.ru/assets/images/widgets/emoji/1.svg\" /></div>"+
                        "<div data-value=\"Плохо\" class=\"emoji-item rating-item\"><img src=\"https://app.leadgenic.ru/assets/images/widgets/emoji/2.svg\" /></div>"+
                        "<div data-value=\"Нормально\" class=\"emoji-item rating-item\"><img src=\"https://app.leadgenic.ru/assets/images/widgets/emoji/3.svg\" /></div>"+
                        "<div data-value=\"Хорошо\" class=\"emoji-item rating-item\"><img src=\"https://app.leadgenic.ru/assets/images/widgets/emoji/4.svg\" /></div>"+
                        "<div data-value=\"Отлично\" class=\"emoji-item rating-item\"><img src=\"https://app.leadgenic.ru/assets/images/widgets/emoji/5.svg\" /></div>"+
                        "</div>";
				}
                if (fElement.fieldType.type === 'nps') {
                    return "<div class=\"nps-container\">"+
                        		"<div class=\"nps-numbers rating-click-container\">"+
                        			"<div class=\"nps-number-item rating-item\" data-value=\"0\">0</div>"+
									"<div class=\"nps-number-item rating-item\" data-value=\"1\">1</div>"+
									"<div class=\"nps-number-item rating-item\" data-value=\"2\">2</div>"+
									"<div class=\"nps-number-item rating-item\" data-value=\"3\">3</div>"+
									"<div class=\"nps-number-item rating-item\" data-value=\"4\">4</div>"+
									"<div class=\"nps-number-item rating-item\" data-value=\"5\">5</div>"+
									"<div class=\"nps-number-item rating-item\" data-value=\"6\">6</div>"+
									"<div class=\"nps-number-item rating-item yellow\" data-value=\"7\">7</div>"+
									"<div class=\"nps-number-item rating-item yellow\" data-value=\"8\">8</div>"+
									"<div class=\"nps-number-item rating-item green\" data-value=\"9\">9</div>"+
                        			"<div class=\"nps-number-item rating-item green\" data-value=\"10\">10</div>"+
                        		"</div>"+
                    			"<div class=\"nps-text\">"+
                                	"<span class=\"nps-text-item\">0 - не порекомендую</span>"+
                                	"<span class=\"nps-text-item\">10 - обязательно порекомендую</span>"+
                                "</div>"+
						"</div>";
                }
                if (fElement.fieldType.type === 'like') {
                    return "<div class=\"like-container rating-click-container\">"+
                        "<div data-value=\"Не нравится\" class=\"like-item rating-item\"><img src=\"https://app.leadgenic.ru/assets/images/widgets/like/dislike.svg\" alt=\"Не нравится\" /></div>"+
                        "<div data-value=\"Нравится\" class=\"like-item rating-item\"><img src=\"https://app.leadgenic.ru/assets/images/widgets/like/like.svg\" alt=\"Нравится\" /></div>"+
                        "</div>";
                }
                return "<div class=\"rating-container\" data-content=\""+LGWGService.ratingStars(fElement)+"\" style=\"color:"+fElement.colorInactive+"\">"+
                    "<div class=\"rating-container-in rating-click-container\" data-content=\""+LGWGService.ratingStars(fElement)+"\"></div>"+
                    "<div class=\"rating-stars\" data-content=\""+LGWGService.ratingStars(fElement)+"\" style=\"color:"+fElement.colorActive+"\"></div>"+
                    "</div>";
			}
            return "<div class=\"rating-container\" data-content=\""+LGWGService.ratingStars(fElement)+"\" style=\"color:"+fElement.colorInactive+"\">"+
                "<div class=\"rating-container-in rating-click-container\" data-content=\""+LGWGService.ratingStars(fElement)+"\"></div>"+
                "<div class=\"rating-stars\" data-content=\""+LGWGService.ratingStars(fElement)+"\" style=\"color:"+fElement.colorActive+"\"></div>"+
                "</div>";
		},
        getFormExtButtonMarkup: function(elementModel) {
        	var buttonMarkup = "";
        	if (elementModel.bType.type === 1 || elementModel.bType.type === 2) {
        		buttonMarkup += "<i class=\""+elementModel.icon.selectedIcon+"\" style=\"color:"+elementModel.icon.color+"\"></i>";
        	}
        	if (elementModel.bType.type === 0 || elementModel.bType.type === 1) {
        		buttonMarkup += "<div>"+elementModel.textSummer+"</div>";
        	}
        	return buttonMarkup;
        },
        getFormExtWidthElement: function(value, type) {
        	return "width: " + value + (type === 0 ? "%" : "px");
        },
        getFormExtNewLineClass: function(isNewLine, index) {
        	return index > 0 && isNewLine ? "widget1-form-ext-new-line-for-next" : "";
        },
        getFormExtPlaceholderMobile: function(placeholder) {
        	return ((window.screen.availWidth <= 760) && LeadCore.isMobile.any()) ? "" : "";
        },
        getFormExtInputType: function(fElement) {
        	return ((window.screen.availWidth <= 760) && LeadCore.isMobile.any() && fElement.type === "phone" && fElement.mask && fElement.mask.enable) ? "tel" : "text";
        },
		getButtonHoverStyle: function(buttonSettings) {
            return buttonSettings.colorBtnHover || (buttonSettings.styleType === 'Border Style' ? 'transparent' : buttonSettings.colorBtn);
		},
		getButtonHoverStyle: function(buttonSettings) {
            return buttonSettings.colorBtnHover || (buttonSettings.styleType === 'Border Style' ? 'transparent' : buttonSettings.colorBtn);
		},
		getFormExtListMarkup: function(visualFormObj, stepId) {
			const _stepId = stepId || 0;
			var formMarkup = "";

			for (var f = 0; f < visualFormObj.list.length; f++) {
				var fElement = visualFormObj.list[f];

				formMarkup += "<div class=\"widget-form-ext-end-el "+LGWGService.getFormExtNewLineClass(fElement.newLine, f)+"\"></div>";

				const inputStyle = "background:"+visualFormObj.mainSettings.rgbaInputForm+";color:"+visualFormObj.mainSettings.colorTitleInputForm+";border-radius:"+visualFormObj.mainSettings.borderRadiusInputForm+"px;border-color:"+visualFormObj.mainSettings.border.color+";--inputBorderColorHover:"+(visualFormObj.mainSettings.border.colorHover || visualFormObj.mainSettings.border.color);

				if (fElement.type === "email" || fElement.type === "name" || fElement.type === "phone") {
					formMarkup += "<div class=\"widget-inp-bl\" style=\""+LGWGService.getFormExtWidthElement(fElement.widthValue, fElement.widthType.type)+"\" data-field=\""+fElement.idField+"\">"+
									  "<div class=\"text-input-class form-ext-field form-ext-field-"+fElement.type+"\">"+
										"<input id=\""+fElement.type+"\" name=\""+fElement.type+"\" autocomplete=\""+fElement.type+"\" placeholder=\""+LGWGService.getFormExtPlaceholderMobile(fElement.placeholder)+"\" type=\""+LGWGService.getFormExtInputType(fElement)+"\" class=\"form-control form-widget-cntrl form-ext-input-field form-control-ext-def form-label-for-change form-cntrl-"+fElement.type+" form-req-"+fElement.required+" "+LGWGService.isFormBorder(visualFormObj.mainSettings)+"\" style=\""+inputStyle+"\">"+
										"<label for=\""+fElement.type+"\" class=\"form-widget-cntrl-label\" style=\"color:"+visualFormObj.mainSettings.colorTitleInputForm+"\">"+fElement.placeholder+"</label>"+
								  "</div></div>";
				}

				if (fElement.type === "message") {
					formMarkup += "<div class=\"widget-inp-bl\" style=\""+LGWGService.getFormExtWidthElement(fElement.widthValue, fElement.widthType.type)+"\" data-field=\""+fElement.idField+"\">"+
									  "<div class=\"text-input-class form-ext-field text-input-area-class form-ext-field-"+fElement.type+"\">"+
										"<textarea id=\"elementidmessage\" placeholder=\""+LGWGService.getFormExtPlaceholderMobile(fElement.placeholder)+"\" type=\"text\" class=\"form-control form-widget-cntrl form-ext-input-field form-control-ext-def form-label-for-change form-cntrl-message form-req-"+fElement.required+" "+LGWGService.isFormBorder(visualFormObj.mainSettings)+"\" style=\""+inputStyle+"\"></textarea>"+
										"<label for=\"elementidmessage\" class=\"form-widget-cntrl-label\" style=\"color:"+visualFormObj.mainSettings.colorTitleInputForm+"\">"+fElement.placeholder+"</label>"+
								  "</div></div>";
				}

				if (fElement.type === "text") {
					formMarkup += "<div class=\"widget-inp-bl form-ext-field form-ext-unique form-ext-req-"+fElement.required+" form-ext-field-"+fElement.type+"\" data-field=\""+fElement.idField+"\" data-id=\""+fElement.id+"\" style=\""+LGWGService.getFormExtWidthElement(fElement.widthValue, fElement.widthType.type)+"\">"+
									  "<div class=\"text-input-class text-input-class-ext-"+fElement.multiLine+"\">"+
									  	(fElement.multiLine ? "<textarea id=\"elementid"+fElement.idField+_stepId+"\" type=\"text\" class=\"form-control form-ext-input-field form-widget-cntrl form-label-for-change form-cntrl-"+fElement.type+" "+LGWGService.isFormBorder(visualFormObj.mainSettings)+"\" style=\""+inputStyle+"\"></textarea>" :
										"<input id=\"elementid"+fElement.idField+_stepId+"\" placeholder=\""+LGWGService.getFormExtPlaceholderMobile(fElement.placeholder)+"\" type=\"text\" class=\"form-control form-widget-cntrl form-label-for-change form-cntrl-"+fElement.type+" "+LGWGService.isFormBorder(visualFormObj.mainSettings)+"\" style=\""+inputStyle+"\">") +
										"<label for=\"elementid"+fElement.idField+_stepId+"\" class=\"form-widget-cntrl-label\" style=\"color:"+visualFormObj.mainSettings.colorTitleInputForm+"\">"+fElement.placeholder+"</label>"+
									  "</div>"+
								  "</div>";
				}

				if (fElement.type === "rating") {
					formMarkup += "<div class=\"widget-inp-bl form-ext-field form-ext-unique form-ext-type-"+fElement.type+" form-ext-req-"+fElement.required+" form-ext-send-form-on-action-"+fElement.sendFormIfAction+" form-ext-next-step-on-action-"+fElement.nextStepIfAction+" form-ext-field-"+fElement.type+"\" data-field=\""+fElement.idField+"\" data-id=\""+fElement.id+"\" style=\""+LGWGService.getFormExtWidthElement(fElement.widthValue, fElement.widthType.type)+"\">"+
									  "<div class=\"rating-input-class\">"+
										"<div class=\"rating-wrapper\" data-type=\""+LGWGService.ratingType(fElement)+"\">"+
											LGWGService.getRatingMarkup(fElement)+
										"</div>"+
									  "</div>"+
								  "</div>";
				}

				if (fElement.type === "variants") {
					formMarkup += "<div class=\"widget-inp-bl form-ext-field form-ext-unique form-ext-type-"+fElement.type+" form-ext-req-"+fElement.required+" form-ext-send-form-on-action-"+fElement.sendFormIfAction+" form-ext-next-step-on-action-"+fElement.nextStepIfAction+" form-ext-multi-"+fElement.multiEnable+" form-ext-field-"+fElement.type+"\" data-field=\""+fElement.idField+"\" data-id=\""+fElement.id+"\" style=\""+LGWGService.getFormExtWidthElement(fElement.widthValue, fElement.widthType.type)+"\">"+
									  "<div class=\"checkbox-input-class\">"+
										"<div class=\"form-ext-checkbox-wrapper "+(fElement.everyNewLine && 'form-ext-checkbox-wrapper__wrapped')+"\">"+LGWGService.getVariantsMarkup(fElement, visualFormObj.mainSettings)+"</div>"+
									  "</div>"+
								  "</div>";
				}

				if (fElement.type === "dd") {
					formMarkup += "<div class=\"widget-inp-bl form-ext-field form-ext-unique form-ext-type-"+fElement.type+" form-ext-req-"+fElement.required+" form-ext-send-form-on-action-"+fElement.sendFormIfAction+" form-ext-next-step-on-action-"+fElement.nextStepIfAction+" form-ext-field-"+fElement.type+"\" data-field=\""+fElement.idField+"\" data-id=\""+fElement.id+"\" style=\""+LGWGService.getFormExtWidthElement(fElement.widthValue, fElement.widthType.type)+"\">"+
									  "<div class=\"dd-input-class\">"+
										"<div class=\"form-ext-dropdown-wrapper\">"+
											"<div class=\"w-dropdown\" style=\"color:"+visualFormObj.mainSettings.colorTitleInputForm+"\">"+
												"<input readonly id=\"elementid"+fElement.id+"\" placeholder=\""+LGWGService.getFormExtPlaceholderMobile(fElement.placeholder)+"\" type=\"text\" data-number=\""+f+"\" class=\"form-control w-dropdown-input "+LGWGService.isFormBorder(visualFormObj.mainSettings)+"\" style=\""+inputStyle+"\">"+
												"<label for=\"elementid"+fElement.id+"\" style=\"color:"+visualFormObj.mainSettings.colorTitleInputForm+"\">"+fElement.placeholder+"</label>"+
												"<span class=\"caret\"></span>"+
											"</div>"+
										"</div>"+
									  "</div>"+
								  "</div>";
				}

				if (fElement.type === "date") {
					formMarkup += "<div class=\"widget-inp-bl form-ext-field form-ext-unique form-ext-type-"+fElement.type+" form-ext-req-"+fElement.required+" form-ext-field-"+fElement.type+"\" data-field=\""+fElement.idField+"\" data-id=\""+fElement.id+"\" style=\""+LGWGService.getFormExtWidthElement(fElement.widthValue, fElement.widthType.type)+"\">"+
									  "<div class=\"date-f-input-class\">"+
										"<div class=\"form-ext-date-wrapper\">"+
											"<div class=\"w-datepicker\">"+
												"<input id=\"elementid"+fElement.id+"\" placeholder=\""+LGWGService.getFormExtPlaceholderMobile(fElement.placeholder)+"\" type=\"text\" data-number=\""+f+"\" data-format=\""+fElement.dateType.value+"\" class=\"form-control w-datepicker-input "+LGWGService.isFormBorder(visualFormObj.mainSettings)+"\" style=\""+inputStyle+"\">"+
												"<label for=\"elementid"+fElement.id+"\" style=\"color:"+visualFormObj.mainSettings.colorTitleInputForm+"\">"+fElement.placeholder+"</label>"+
											"</div>"+
										"</div>"+
									  "</div>"+
								  "</div>";
				}

				if (fElement.type === "title") {
					formMarkup += "<div class=\"widget-inp-bl\" style=\""+LGWGService.getFormExtWidthElement(fElement.widthValue, fElement.widthType.type)+"\">"+
									  "<div class=\"title-f-input-class\">"+
										"<div class=\"form-ext-title-wrapper\">"+
											"<div class=\"title-main-new-dot "+LGWGService.isTextShadow(fElement)+"\" style=\"font-size:"+fElement.fontSize+"px;font-family:"+fElement.font.fontFamily+";text-shadow:"+fElement.textShadow.horiz+"px "+fElement.textShadow.vertical+"px "+fElement.textShadow.blur+"px "+LGWGService.getRGBAColor(fElement)+"\">"+fElement.textSummer+"</div>"+
										"</div>"+
									  "</div>"+
								  "</div>";
				}

				if (fElement.type === "term") {
					var termInputMarkup = function() {
			        	return fElement.checked ? "<input type=\"checkbox\" checked>" : "<input type=\"checkbox\">";
			        }
					formMarkup += "<div class=\"widget-inp-bl form-ext-field form-ext-field-term form-ext-req-"+fElement.required+"\" style=\""+LGWGService.getFormExtWidthElement(fElement.widthValue, fElement.widthType.type)+"\">"+
									  "<div class=\"term-input-class\">"+
										"<div class=\"form-ext-term-wrapper\">"+
											"<div class=\"form-ext-term-error-help-box\"></div>"+
											"<label class=\"form-ext-term-checkbox-container\">"+
                                                "<div class=\"form-ext-term-checkbox-container-help-cl\" style=\"background-color:"+LGWGService.getBGColor(visualFormObj.mainSettings)+";border-color:"+LGWGService.getBGColor(visualFormObj.mainSettings)+"\">"+
	                                                termInputMarkup()+
	                                                "<span class=\"form-ext-term-checkbox-checkmark\" style=\"background-color:"+visualFormObj.mainSettings.rgbaInputForm+";border-color:"+(visualFormObj.mainSettings.border.enable ? visualFormObj.mainSettings.border.color : 'transparent')+"\"></span>"+
                                                "</div>"+
                                                "<div class=\"title-main-new-dot "+LGWGService.isTextShadow(fElement)+"\" style=\"font-size:"+fElement.fontSize+"px;font-family:"+fElement.font.fontFamily+";text-shadow:"+fElement.textShadow.horiz+"px "+fElement.textShadow.vertical+"px "+fElement.textShadow.blur+"px "+LGWGService.getRGBAColor(fElement)+"\">"+fElement.textSummer+"</div>"+
                                            "</label>"+
										"</div>"+
									  "</div>"+
								  "</div>";
				}

				if (fElement.type === "button") {
					const buttonColorHover = LGWGService.getButtonHoverStyle(fElement);
					const btnStyle = "font-size:"+fElement.fontSize+"px;font-family:"+fElement.font.fontFamily+";background:"+fElement.colorBtn+";border-color:"+fElement.colorBtn+"!important;color:"+fElement.colorTextBtn+";border-radius:"+fElement.borderRadiusBtn+"px;--buttonColorHover:"+buttonColorHover;
					formMarkup += "<div class=\"widget-inp-bl\" style=\""+LGWGService.getFormExtWidthElement(fElement.widthValue, fElement.widthType.type)+"\">"+
									  "<button class=\"click-edit-cl button-send form-ext-button "+LGWGService.btnStyleSel(fElement)+" form-ext-button-type"+fElement.redirect.type.type+" form-ext-button-redirect-blank-"+fElement.redirect.blank+" form-ext-button-target-action-"+fElement.targetAction+"\" data-id=\""+fElement.id+"\" data-custom=\""+fElement.customUserValue+"\" data-service=\""+fElement.service+"\" data-url=\""+fElement.redirect.url+"\" style=\""+btnStyle+"\">"+
										"<div class=\"form-ext-btn-el-wr\"><div class=\"form-ext-btn-el-wr-cont\">"+LGWGService.getFormExtButtonMarkup(fElement)+"</div></div>"+
									  "</button>"+
								  "</div>";
				}
			}
			return formMarkup;
		},
        getFormExtListMarkupMultiStep: function(_stepData, _settings) {
            const parsedData = {
            	list: _stepData.list,
				mainSettings: _settings
			};
            return LGWGService.getFormExtListMarkup(parsedData, _stepData.stepId);
		},
        getMultiFormVertAlign: function(orientation) {
            if (!orientation) return "";
			switch (orientation) {
				case LeadCore.constants.fromCenterSide:
                    return "widget-form-multi__container--center";
				case LeadCore.constants.fromEndSide:
                    return "widget-form-multi__container--end";
				case LeadCore.constants.fromStartSide:
                    return "widget-form-multi__container--start";

				default:
                    return "";
			}
        },
        getFormExtListMarkupMultiSteps: function(steps, mainSettings) {
            let formMarkup = "<div class=\"widget-form-multi__container "+LGWGService.getMultiFormVertAlign(mainSettings.heightOrientation)+"\">";
            steps.forEach((_item, index) => {
                const hideClass = index > 0 ? 'hide-right' : '';
                formMarkup += "<div id=\"fMultiStep-"+_item.stepId+"\" class=\"widget-form-multi-step "+hideClass+"\">";
                formMarkup += LGWGService.getFormExtListMarkupMultiStep(_item, mainSettings);
                formMarkup += "</div>";
            });
            formMarkup += "</div>";
            return formMarkup;
        },
        getFormExtListMarkupMulti: function({model, steps}, progressBarMarkup) {
            let formMarkup = "";
            const { mainSettings } = model;

            if (steps.length > 1) {
                formMarkup += progressBarMarkup;
            }
            formMarkup += LGWGService.getFormExtListMarkupMultiSteps(steps, mainSettings);
            return formMarkup;
        },
		ratingInitProcess: function(ratings) {
			for (var i = 0; i < ratings.length; i++) {
			    var currentItem = ratings[i];
			    currentItem.onmousemove = function(e) {LGWGService.ratingStarMoved(e);};
			    currentItem.onmouseout = function(e) {LGWGService.ratingStarLeaved(e);};
			    currentItem.onclick = function(e) {LGWGService.ratingStarClicked(e);};
		  	}
		},
        ratingItemsInitProcess: function(ratings) {
            for (var i = 0; i < ratings.length; i++) {
                var currentItem = ratings[i];
                currentItem.onclick = function(e) {LGWGService.ratingItemClicked(e);};
            }
        },
        emojiItemsInitProcess: function(ratings) {
            for (var i = 0; i < ratings.length; i++) {
                const items = ratings[i].getElementsByClassName('rating-item');
                for (let k = 0; k < items.length; k++) {
                    const currentItem = items[k];
                    currentItem.onclick = function () {
                        LGWGService.emojiItemClicked(currentItem);
                    };
                }
            }
        },
		initTooltip: function(tooltipContainer, item) {
			if (!item) {
				return;
			}
            for (let k = 0; k < item.length; k++) {
                const items = item[k].getElementsByClassName('rating-item');
                for (let i = 0; i < items.length; i++) {
                    const currentItem = items[i];
                    currentItem.onmousemove = function() {
                        const text = currentItem.dataset['value'];

                        const viewPortItem = currentItem.getBoundingClientRect();
                        tooltipContainer.style.visibility = 'visible';
                        let xOffset = 5;
                        if (text === 'Плохо') {
                            xOffset = 2;
						} else if (text === 'Нормально') {
                            xOffset = 20;
                        } else if (text === 'Хорошо') {
                            xOffset = 7;
                        } else if (text === 'Отлично') {
                            xOffset = 10;
                        } else if (text === 'Нравится') {
                            xOffset = 3;
                        } else if (text === 'Не нравится') {
                            xOffset = 12;
                        }

                        tooltipContainer.style.left = `${viewPortItem.left - xOffset}px`;
                        tooltipContainer.style.top = `${viewPortItem.top - 32}px`;
                        tooltipContainer.innerHTML = text;
                    };
                    currentItem.onmouseout = function() {
                        tooltipContainer.style.visibility = 'hidden';
                        tooltipContainer.innerHTML = '';
                    };
                }
			}
		},
		datePickerInitProcess: function(datePickers, LGWGIframeLabelDiv, widgetLGWGNewPopupId, windowElement, widgetType) {
			var DP_HEIGHT = 245;
			var WIDGET_BOTTOM_PADDING = 40;
			
			for (var i = 0; i < datePickers.length; i++) {
			    var currentItem = datePickers[i];
			    currentItem.addEventListener('click', function(e) {
			    	var coordDP = e.target.getBoundingClientRect();
			    	var coordMainBL = LGWGIframeLabelDiv.getBoundingClientRect();

			    	var difH = coordMainBL.height - WIDGET_BOTTOM_PADDING - coordDP.bottom;

			    	var topPosition = (difH < DP_HEIGHT ? (coordMainBL.top + coordDP.bottom - DP_HEIGHT - coordDP.height) : (coordMainBL.top + coordDP.bottom));
  					var extraOffset = widgetType === 'float' ? 0 : (window.scrollY || document.body.scrollTop);
  					const mobileOffset = LeadCore.isMobile.any() && coordMainBL.y ? -coordMainBL.y : 0;
			    	
			    	// Datepicker request
					var dpData = {
						format: e.target.getAttribute('data-format'),
						dpTopPosition: topPosition + extraOffset + mobileOffset + 'px',
						dpLeftPosition: coordMainBL.left + coordDP.left + 'px',
			    		wId: widgetLGWGNewPopupId,
			    		name: 'datepicker',
			    		dpItemNumber: e.target.getAttribute('data-number'),
			    		offset: 100,
			    		position: widgetType
			    	};
			    	
			    	window.postMessage(dpData, windowElement.top.location);
			    });
		  	}

		  	// Datepicker response
		  	var onmessageDPLGWG = function(e) {
			  var data = e.data;
			  if (data.name === 'datepickerChanged' && data.wId === widgetLGWGNewPopupId) {
				  var currentDP;

				  for (var i = 0; i < datePickers.length; i++) {
				  	if (datePickers[i].getAttribute('data-number') === data.dpItemNumber) {
				  		currentDP = datePickers[i];
				  	}
				  }

				  currentDP.value = data.formattedDate;
				  currentDP.classList.add('filled');
			  }
			};
	 
			window.addEventListener('message', onmessageDPLGWG);
			LGWGService.setOutsideClickHandler(windowElement);
		},
		dropDownInitProcess: function(dropDowners, LGWGIframeLabelDiv, visualObjNewPopup, widgetLGWGNewPopupId, windowElement, widgetType) {
			var WIDGET_BOTTOM_PADDING = 40;
			
			for (var i = 0; i < dropDowners.length; i++) {
			    var currentItem = dropDowners[i];

			    currentItem.addEventListener('click', function(e) {
			    	var numberOfList = e.target.getAttribute('data-number');
			    	const ddId = e.target.id.replace('elementid', '');
			    	var sameData;
                    visualObjNewPopup.formExt.steps.some((_item) => {
                        sameData = _item.list.find((_el) => _el.type === 'dd' && _el.id === ddId);
                        return sameData;
                    });

			    	if (!sameData) return;

			    	var coordDD = e.target.getBoundingClientRect();
			    	var coordMainBL = LGWGIframeLabelDiv.getBoundingClientRect();
			    	var difH = coordMainBL.height - WIDGET_BOTTOM_PADDING - coordDD.bottom;
			    	
			    	// DropDown request
					var ddData = {
						variants: sameData.variants,
						difH: difH,
						coordDD: coordDD,
						coordMainBL: coordMainBL,
			    		wId: widgetLGWGNewPopupId,
			    		name: 'dropdown',
			    		ddItemNumber: numberOfList,
			    		position: widgetType
			    	};
			    	
			    	window.postMessage(ddData, windowElement.top.location);
			    });
		  	}

		  	// DropDown response
		  	var onmessageDDLGWG = function(e) {
			  var data = e.data;
			  if (data.name === 'dropdownChanged' && data.wId === widgetLGWGNewPopupId) {
				  var currentDD;

				  for (var i = 0; i < dropDowners.length; i++) {
				  	if (dropDowners[i].getAttribute('data-number') === data.ddItemNumber) {
				  		currentDD = dropDowners[i];
				  	}
				  }

				  currentDD.value = data.value;
				  currentDD.classList.add('filled');
				  if ("createEvent" in document) {
					var evt = document.createEvent("HTMLEvents");
					evt.initEvent("change", false, true);
					currentDD.dispatchEvent(evt);
				  } else {
					currentDD.fireEvent("onchange");
				  }
			  }
			};
	 
			window.addEventListener('message', onmessageDDLGWG);
			LGWGService.setOutsideClickHandler(windowElement);
		},
		validPhoneInput: function (input) {
		    var re = /^[\d\+\(\)\ -]{4,20}\d$/;
		    var valid = re.test(input);
		    return valid;
		},
		validEmailInput: function(input) {
		    var r = /^([a-z0-9_-]+\.)*[a-z0-9_-]+@[a-z0-9_-]+(\.[a-z0-9_-]+)*\.[a-z]{2,6}$/i;
		    var valid = r.test(input);
		    return valid;
		},
		validNMInputAuto: function(inputsArr) {
			if (inputsArr.value !== '') {
				var newStr = inputsArr.value.replace(/&/g, '/&');
				return newStr;
			}
			else {
				inputsArr.classList.add('form-control-error');
				return '';
			}
		},
		validNMNInputAuto: function(inputsArr) {
			if (inputsArr.value !== '') {
				var newStr = inputsArr.value.replace(/&/g, '/&');
				return newStr;
			}
			else {
				return '';
			}
		},
		validPhoneInputAuto: function(inputsArr) {
			if (LGWGService.validPhoneInput(inputsArr.value)) {
				return inputsArr.value;
			}
			else {
				inputsArr.classList.add('form-control-error');
				return '';
			}
		},
		validEmailInputAuto: function(inputsArr) {
			if (LGWGService.validEmailInput(inputsArr.value)) {
				return inputsArr.value;
			}
			else {
				inputsArr.classList.add('form-control-error');
				return '';
			}
		},
		validPhoneFormExtInput: function(inputsArrF) {
			var inputsArr = inputsArrF.querySelector('.form-control');
			if (LGWGService.validPhoneInput(inputsArr.value)) {
				return inputsArr.value;
			}
			else {
				inputsArrF.classList.add('form-control-error');
				return '';
			}
		},
		validEmailFormExtInput: function(inputsArrF) {
			var inputsArr = inputsArrF.querySelector('.form-control');
			if (LGWGService.validEmailInput(inputsArr.value)) {
				return inputsArr.value;
			}
			else {
				inputsArrF.classList.add('form-control-error');
				return '';
			}
		},
		validNMFormExtInput: function(inputsArrF, isReturnNull) {
			var inputText = inputsArrF.querySelector('.form-control');
			if (inputText.value !== '') {
				var newStr = inputText.value.replace(/&/g, '/&');
				return newStr;
			}
			else {
				inputsArrF.classList.add('form-control-error');
				return isReturnNull ? null : '';
			}
		},
		validNMNFormExtInput: function(inputsArrF, isReturnNull) {
			var inputText = inputsArrF.querySelector('.form-control');
			if (inputText.value !== '') {
				var newStr = inputText.value.replace(/&/g, '/&');
				return newStr;
			}
			else {
				return isReturnNull ? null : '';
			}
		},
		isInputFieldValid: function(inputsArrF, func) {
			var input = inputsArrF.querySelector('input[type="text"]') || inputsArrF.querySelector('input[type="tel"]');
			if (input.classList.contains('form-req-true') || input.value !== '') {
				return func(inputsArrF);
			} else {
				return null;
			}
		},
		isFormExtFieldValid: function(inputsArrF) {
			var isInputFieldRequired = inputsArrF.classList.contains('form-ext-req-true');
			var input = inputsArrF.querySelector('input[type="text"]') || inputsArrF.querySelector('input[type="tel"]');
			if (isInputFieldRequired && input.value === '') {
				inputsArrF.classList.add('form-control-error');
				return null;
			} else {
				return input.value || null;
			}
		},
		isRatingFieldValid: function(inputsArrF) {
			var isInputFieldRequired = inputsArrF.classList.contains('form-ext-req-true');
			var ratingContainer = inputsArrF.querySelector('.rating-click-container');
			var ratingValue = ratingContainer.getAttribute('data-cache-value');
			if (isInputFieldRequired && !ratingValue) {
				inputsArrF.classList.add('form-control-error');
				return null;
			} else {
				return ratingValue || null;
			}
		},
        getFormExtValue: function(inputsArrF) {
            const input = inputsArrF.querySelector('input[type="text"]') || inputsArrF.querySelector('input[type="tel"]');
            return input.value || null;
        },
        getRatingValue: function(inputsArrF) {
            const ratingContainer = inputsArrF.querySelector('.rating-click-container');
            const ratingValue = ratingContainer.getAttribute('data-cache-value');
            return ratingValue || null;
        },
		setRemoveErrorOnFocus: function(input) {
			input.addEventListener('focus', function() {
				this.closest('.form-ext-field').classList.remove('form-control-error');
			});
		},
		redirectIfOn: function(data, blank, url, closeWidget) {
			if (closeWidget) {
				closeWidget();
			}
			if (blank) {
				window.open(LGWGService.redirectParams(data, url), '_blank');
				return false;
			}
			else {
				window.location = LGWGService.redirectParams(data, url);
				return false;
			}
		},
		removeEmptyKeys: function(obj) {
			Object.keys(obj).forEach(function(k) {
				if(!obj[k] && obj[k] !== undefined) {
					delete obj[k];
				}
			});
			return obj;
		},
		parseFieldId: function(formExtData, widgetData) {
			formExtData.helpData = {};

            widgetData.formExt.steps.forEach(_step => {
                _step.list.forEach(formItem => {
                    if (!formItem.id || !formItem.idField) return;
                    formExtData.helpData[formItem.id] = formItem.idField;
                });
            });
		},
        storeRuleFields: function(formExtFields, stepId) {
		    const storedRules = [];
            formExtFields.forEach((inputsArrF) => {
                const currentId = inputsArrF.getAttribute("data-id");

                if (inputsArrF.classList.contains('form-ext-field-variants')) {
                    // Variants
                    if (inputsArrF.classList.contains('form-ext-multi-true')) {
                        //Checkboxes
                        const checkboxInputs = inputsArrF.querySelectorAll('input[type="checkbox"]:checked');
                        if (checkboxInputs.length) {
                            checkboxInputs.forEach(v => {
                                const closestContainer = v.closest('.form-ext-checkbox-container');
                                storedRules.push({type: 'variants', id: currentId, value: closestContainer.textContent || closestContainer.innerText});
                            });
                        }
                    } else {
                        //Radio
                        var radioInputs = inputsArrF.querySelectorAll('input[type="radio"]:checked');
                        if (radioInputs.length) {
                            radioInputs.forEach(v => {
                                const closestContainer = v.closest('.form-ext-checkbox-container');
                                storedRules.push({type: 'variants', id: currentId, value: closestContainer.textContent || closestContainer.innerText});
                            });
                        }
                    }
                } else if (inputsArrF.classList.contains('form-ext-field-dd')) {
                    // DropDown list
                    storedRules.push({type: 'dd', id: currentId, value: LGWGService.getFormExtValue(inputsArrF)});
                } else if (inputsArrF.classList.contains('form-ext-field-rating')) {
                    // Rating
                    storedRules.push({type: 'rating', id: currentId, value: LGWGService.getRatingValue(inputsArrF)});
                }
            });
            return storedRules;
        },
		checkFormExtFields: function(formExtFields, paramsToSend, content) {
			for (var i = 0; i < formExtFields.length; i++) {
				var inputsArrF = formExtFields[i];
				var currentId = inputsArrF.getAttribute("data-id");
				inputsArrF.classList.remove('form-control-error');

				var inputField = inputsArrF.querySelector('.form-control');
				if (inputField) {
					LGWGService.setRemoveErrorOnFocus(inputField);
				}

				var checkBoxesWr = inputsArrF.querySelector('.form-ext-checkbox-wrapper');
				if (checkBoxesWr) {
					var checkBoxInputs = checkBoxesWr.querySelectorAll('input');
					checkBoxInputs.forEach(function(item) {
						LGWGService.setRemoveErrorOnFocus(item);
					});
				}

				if (inputsArrF.classList.contains('form-ext-field-phone')) {
					paramsToSend.phone = LGWGService.isInputFieldValid(inputsArrF, LGWGService.validPhoneFormExtInput);
				}

				if (inputsArrF.classList.contains('form-ext-field-email')) {
					paramsToSend.email = LGWGService.isInputFieldValid(inputsArrF, LGWGService.validEmailFormExtInput);
				}

				if (inputsArrF.classList.contains('form-ext-field-name')) {
					var inputName = inputsArrF.querySelector('input[type="text"]');
					paramsToSend.firstName = inputName.classList.contains('form-req-true') ? LGWGService.validNMFormExtInput(inputsArrF, false) : LGWGService.validNMNFormExtInput(inputsArrF, false);
				}

				if (inputsArrF.classList.contains('form-ext-field-message')) {
					var inputComment = inputsArrF.querySelector('textarea[type="text"]');
					paramsToSend.comment = inputComment.classList.contains('form-req-true') ? LGWGService.validNMFormExtInput(inputsArrF, false) : LGWGService.validNMNFormExtInput(inputsArrF, false);
				}

				//Text input field
				if (inputsArrF.classList.contains('form-ext-field-text')) {
					var isTextInputFieldRequired = inputsArrF.classList.contains('form-ext-req-true');
					content[currentId] = isTextInputFieldRequired ? LGWGService.validNMFormExtInput(inputsArrF, true) : LGWGService.validNMNFormExtInput(inputsArrF, true);
				}

				if (inputsArrF.classList.contains('form-ext-field-variants')) {
					// Variants
					var isVariantInputFieldRequired = inputsArrF.classList.contains('form-ext-req-true');

					if (inputsArrF.classList.contains('form-ext-multi-true')) {
						//Checkboxes
						var checkboxInputs = inputsArrF.querySelectorAll('input[type="checkbox"]:checked');
						if (checkboxInputs.length) {
							var checkboxValues = '';
							checkboxInputs.forEach(function(v, index) {
								var closestContainer = v.closest('.form-ext-checkbox-container');
								checkboxValues += (index > 0 ? ", " : "") + (closestContainer.textContent || closestContainer.innerText);
							});
							content[currentId] = checkboxValues;
						} else if (isVariantInputFieldRequired) {
							inputsArrF.classList.add('form-control-error');
						}
					} else {
						//Radio
						var radioInputs = inputsArrF.querySelectorAll('input[type="radio"]:checked');
					
						if (radioInputs.length) {
							radioInputs.forEach(function(v) {
								var closestContainer = v.closest('.form-ext-checkbox-container');
								content[currentId] = closestContainer.textContent || closestContainer.innerText;
							});
						} else if (isVariantInputFieldRequired) {
							inputsArrF.classList.add('form-control-error');
						}
					}
				}

				if (inputsArrF.classList.contains('form-ext-field-dd')) {
					// DropDown list
					content[currentId] = LGWGService.isFormExtFieldValid(inputsArrF);
				}

				if (inputsArrF.classList.contains('form-ext-field-date')) {
					// Datepicker
					content[currentId] = LGWGService.isFormExtFieldValid(inputsArrF);
				}

				if (inputsArrF.classList.contains('form-ext-field-rating')) {
					// Rating
					content[currentId] = LGWGService.isRatingFieldValid(inputsArrF);
				}

				if (inputsArrF.classList.contains('form-ext-field-term')) {
					var isTermInputFieldRequired = inputsArrF.classList.contains('form-ext-req-true');
					var termCheckboxInput = inputsArrF.querySelectorAll('input[type="checkbox"]:checked');

					if (isTermInputFieldRequired && !termCheckboxInput.length) {
						inputsArrF.classList.add('form-control-error');
					}
				}

				if (inputsArrF.classList.contains('form-control-error')) {
					paramsToSend.error = true;
				}
			}
		},
		createHiddenFields: function(form, widgetId) {
			LeadCore.hidden[widgetId] = [];
			LeadCore.hidden[widgetId] = [
				document.createElement('input'), 
				document.createElement('input'), 
				document.createElement('input')
	  		];

			LeadCore.hidden[widgetId].forEach(input => {
				input.classList.add('hidden');
			});

			const [hiddenEmail, hiddenText, hiddenPhone] = LeadCore.hidden[widgetId];

			hiddenEmail.type = 'email';
			hiddenText.type = 'text';
			hiddenPhone.type = 'phone';

			form.append(hiddenEmail, hiddenText, hiddenPhone);		

		},
		checkForHidden: function(widgetId) {
			if (!LeadCore.hidden[widgetId] || (LeadCore.hidden[widgetId] && !LeadCore.hidden[widgetId].length)) {
				return false;
			}
			for (let i = 0; i < LeadCore.hidden[widgetId].length; i++) {
				 return LeadCore.hidden[widgetId][i].value !== '';
			}
		},
		parseCouponFields: function(coupons) {
			return coupons.map((item) => item.value).join();
		},
		sendRequestForm: function(data, serviceData, formType, btn) {
            let visualObjNewPopup = serviceData.widgetObj;
            let currentCouponValue = null;
            let roistatIdNew = LeadCore.getCookie("roistat_visit");
            if (roistatIdNew) {
                data.roistatId = roistatIdNew;
            }

            function callbackGood() {
                setTimeout(() => {
                    if (serviceData.targetData) {
                        LGWGService.checkTargetLock(serviceData.targetData.settings, serviceData.targetData.cookieLabel);
                    }
                    LGWGService.parseFieldId(data, serviceData.widgetObj);
                    if (serviceData.onTargetScript) {
                        var targetScript;
                        if (serviceData.jsInfo.enablePlaceholding) {
                            targetScript = LeadCoreExt.parseFieldsForWidgetScript(serviceData.onTargetScript, data);
                        }
                        LeadCoreExt.buildWidgetScript(targetScript || serviceData.onTargetScript);
                    }

                    if (btn) {
                        console.log('remove1 load-stripped');
                        btn.classList.remove('load-stripped');
                        btn.removeAttribute("disabled", "disabled");
                    }

                    if (serviceData.redirectData) {
                        LGWGService.redirectIfOn(data, serviceData.redirectData.blank, serviceData.redirectData.url, serviceData.WidgetDotOffandNoShowThank);
                    } else {
                        LeadCoreExt.isCouponAndPossibleToCloseWidget(visualObjNewPopup[formType]) ? serviceData.WidgetDotOffandNoShowThank() : serviceData.WidgetDotOffandShowThank();
                    }
                    LeadCoreExt.openCouponCallback(serviceData.widgetLGWGNewPopupId, visualObjNewPopup[formType], formType, currentCouponValue, serviceData.metrikaId, serviceData.onTargetScript);
                }, 900);
            }

            function callbackError() {
                if (btn) {
                    btn.classList.remove('load-stripped');
                    btn.removeAttribute("disabled", "disabled");
                }
            }

            LeadCore.sendAnalyticGlobal(serviceData.metrikaId);

            if (btn) {
                console.log('add load-stripped');
                btn.classList.add('load-stripped');
                btn.setAttribute("disabled", "disabled");
            }

            async function startCreationLead(couponCode, couponValue) {
                return new Promise(async (resolve) => {
                    currentCouponValue = couponValue;
                    if (couponCode && couponValue !== undefined) {
                        if (!LeadCoreExt.hiddenFieldCoupons[serviceData.metrikaId]) {
                            LeadCoreExt.hiddenFieldCoupons[serviceData.metrikaId] = [];
                        }
                        const couponCache = {
                            code: couponCode,
                            value: couponValue
                        };
                        LeadCoreExt.hiddenFieldCoupons[serviceData.metrikaId].push(couponCache);

                        if (data.customFields) {
                            for (const [key, value] of Object.entries(data.customFields)) {
                                if (value === 'COUPON_LIST_LGWG') {
                                    data.customFields[key] = LGWGService.parseCouponFields(LeadCoreExt.hiddenFieldCoupons[serviceData.metrikaId]);
                                }
                            }
                        }
                    } else {
                        if (data.customFields) {
                            for (const [key, value] of Object.entries(data.customFields)) {
                                if (value === 'COUPON_LIST_LGWG') {
                                    if (!LeadCoreExt.hiddenFieldCoupons[serviceData.metrikaId]) {
                                        LeadCoreExt.hiddenFieldCoupons[serviceData.metrikaId] = [];
                                    }
                                    if (LeadCoreExt.hiddenFieldCoupons[serviceData.metrikaId].length) {
                                        data.customFields[key] = LGWGService.parseCouponFields(LeadCoreExt.hiddenFieldCoupons[serviceData.metrikaId]);
                                    } else {
                                        delete data.customFields[key];
                                    }
                                }
                            }
                        }
                    }
                    if (LeadCoreExt.hiddenFieldCoupons[serviceData.metrikaId] && LeadCoreExt.hiddenFieldCoupons[serviceData.metrikaId].length) {
                        data.coupons = {};
                        LeadCoreExt.hiddenFieldCoupons[serviceData.metrikaId].forEach((item) => {
                            data.coupons[item.code] = item.value;
                        });
                    }

                    const serviceRedirect = serviceData.redirectData && serviceData.redirectData.blank;
                    await LeadCore.pushCreateLeadPromise(data, serviceRedirect).then(callbackGood, callbackError);
                    setTimeout(() => {
                        resolve();
                    }, 1000);
                });
            }

            return new Promise(async (resolve) => {
				setTimeout(async function() {
					if (LeadCoreExt.isItFormCallbackCoupon(visualObjNewPopup[formType])) {
						var couponCode = visualObjNewPopup[formType].couponCallback.coupon.coupon.code;
						var targetUrl = LeadCore.base + "/api/gate/sites/" + LeadCore.siteId + "/visits/" + LeadCore.currentVisitId + "/coupons/" + couponCode;

                        LeadCoreExt.getPromise(targetUrl).then(async function(response) {
							const result = JSON.parse(response).data;
							if (!result) {
                                resolve(await startCreationLead(null, "&nbsp;"));
							}
                            resolve(await startCreationLead(couponCode, result.value));
						}, async function(error) {
							resolve(await startCreationLead(null, "&nbsp;"));
						});
					} else {
						resolve(await startCreationLead(false, null));
					}
				}, 1000);
            });
		},
		formExtHrPosSelWholeForm: function(item) {
            var className = "";

            if (item.form_width_orientation_type.type === 0)
                className = "widget1-form-ext-w-hr-left";

            if (item.form_width_orientation_type.type === 1)
                className = "widget1-form-ext-w-hr-center";

            if (item.form_width_orientation_type.type === 2)
                className = "widget1-form-ext-w-hr-right";

            if (item.form_width_type.type === 0)
                className += " widget1-form-ext-w-hr-full-w";

            if (item.form_width_type.type === 1)
                className += " widget1-form-ext-w-hr-own";

            return className;
        },
        formExtGlobalAlignmentClass: function(item) {
            var className = "";

            if (item.orientation.type === 0) {
                className += " widget1-form-ext-bl-left";
            }

            if (item.orientation.type === 1) {
                className += " widget1-form-ext-bl-center";
            }

            if (item.orientation.type === 2) {
                className += " widget1-form-ext-bl-right";
            }

            return className;
        },
        setImageHeight: function(visualObjNewPopup, widgetImageLGWG, LGWGNewDotformBlock, LGWGNewDotButtonBlock, LGWGNewDotFormExtBlock, isPopup) {
	 		if ((visualObjNewPopup.image.enable === true) && 
	 			(visualObjNewPopup.button.enable || visualObjNewPopup.form.enable || (visualObjNewPopup.formExt && visualObjNewPopup.formExt.enable))) {

	 			var isFormToAllWidth = visualObjNewPopup.formExt && visualObjNewPopup.formExt.enable ? 
									 visualObjNewPopup.formExt.model.mainSettings.visual.type === 1 :
									 visualObjNewPopup.form.visual === LeadCore.constants.toAllWidth;

	 			if (visualObjNewPopup.image.place === LeadCore.constants.fromLeft && isFormToAllWidth) {
					widgetImageLGWG.style.height = LGWGService.getTopValueOfColorPod(LGWGNewDotformBlock, LGWGNewDotButtonBlock, visualObjNewPopup, LGWGNewDotFormExtBlock, isPopup) + 'px';
				}

				if (visualObjNewPopup.image.place === LeadCore.constants.fromRight && isFormToAllWidth) {
					widgetImageLGWG.style.height = LGWGService.getTopValueOfColorPod(LGWGNewDotformBlock, LGWGNewDotButtonBlock, visualObjNewPopup, LGWGNewDotFormExtBlock, isPopup) + 'px';
				}
	 		}
	 	},
		imageVideoOnMobile: function(imageSettings, widgetImageLGWG, fillVideoArray, LGWGWidgetAndCloseBlock, LGmainBlockDot) {
			if (!imageSettings.enable || (imageSettings.enable && imageSettings.typeBl === 'paddingBl') || (imageSettings.enable && !imageSettings.showOnMobile)) {
				return;
			}
			let isVideoContent = false;
			// Set image for mobile
			widgetImageLGWG.classList.remove('lgwg-none');
			const widgetWidth = LGWGWidgetAndCloseBlock.offsetWidth;
			const factor = widgetWidth / imageSettings.width;
            const imageBlockHeight = imageSettings.img_item_type === LeadCore.constants.alignToUserSize ? (factor * imageSettings.img_item_heightpx) + 15 : (imageSettings.height * factor);
			widgetImageLGWG.style.height = imageBlockHeight + 'px';
			widgetImageLGWG.style.background = "transparent";
            LGmainBlockDot.style.paddingTop = imageBlockHeight + 18 + 'px';

			const imageVideoSize = {
				width: factor * imageSettings.img_item_widthpx,
				height: factor * imageSettings.img_item_heightpx,
			};

			if (imageSettings.img_item_align) {
				let imageTemplate = "";
				if (imageSettings.typeBl === 'imageBl') {
					imageTemplate = "<div class=\"widget-image-item-block\" style=\"background: url("+imageSettings.url+") center no-repeat;background-size: cover;width:"+imageVideoSize.width+"px;height:"+imageVideoSize.height+"px\"></div>";
				} else if (imageSettings.typeBl === 'videoBl') {
					imageTemplate = "<div class=\"widget-video-item-block\" style=\"width:"+imageVideoSize.width+"px;height:"+imageVideoSize.height+"px\"><iframe data-auto=\""+imageSettings.autoplay+"\" allow=\"autoplay; encrypted-media\" class=\"video-element-ifrm\" src=\""+imageSettings.videoUrl+"\" frameborder=\"0\" allowfullscreen></iframe></div>";
					isVideoContent = true;
				}

				widgetImageLGWG.innerHTML = imageTemplate;

				if (imageSettings.img_item_type === LeadCore.constants.alignToAllSize) {
					widgetImageLGWG.classList.add('widget-image-has-full-wh');
				}

				if (imageSettings.img_item_type === LeadCore.constants.alignToUserSize) {
                    const itemContainer = widgetImageLGWG.querySelector('.widget-image-item-block');
                    if (itemContainer) {
                        itemContainer.style.borderRadius = LGWGService.getImageBorderRadius(imageSettings.borderRadius) + 'px';
                    }
					if (imageSettings.img_item_align === LeadCore.constants.alignOnCenter)
						widgetImageLGWG.classList.add('widget-image-has-center-orient');

					if (imageSettings.img_item_align === LeadCore.constants.alignOnTop)
						widgetImageLGWG.classList.add('widget-image-has-top-orient');

					if (imageSettings.img_item_align === LeadCore.constants.alignOnBottom)
						widgetImageLGWG.classList.add('widget-image-has-bottom-orient');
				}

				if (isVideoContent) {
					fillVideoArray();
				}
			}
		},
        imageStyle: function(visualObjNewPopup, LGWGLiFormBtn, LGWGLiFormExtBtn, LGWGNewColorPod, widgetImageLGWG, widgetMainWRLGWG, colorPodLGWG, isVideo, fillVideoArray) {
			if (visualObjNewPopup.form.enable || visualObjNewPopup.button.enable || (visualObjNewPopup.formExt && visualObjNewPopup.formExt.enable)) {
				LGWGNewColorPod.classList.remove('lgwg-none');
			}
			var isFormUnderContent = visualObjNewPopup.formExt && visualObjNewPopup.formExt.enable ? 
									 visualObjNewPopup.formExt.model.mainSettings.visual.type === 0 :
									 visualObjNewPopup.form.visual === LeadCore.constants.underContent;

			var isFormToAllWidth   = visualObjNewPopup.formExt && visualObjNewPopup.formExt.enable ? 
									 visualObjNewPopup.formExt.model.mainSettings.visual.type === 1 :
									 visualObjNewPopup.form.visual === LeadCore.constants.toAllWidth;

			if (visualObjNewPopup.image.enable === true) {
				widgetImageLGWG.classList.remove('lgwg-none');
				widgetImageLGWG.style.width = visualObjNewPopup.image.width + 'px';
				widgetImageLGWG.style.background = "url('" + visualObjNewPopup.image.url + "') center center / cover no-repeat";

				if(visualObjNewPopup.image.img_item_align) {
					widgetImageLGWG.style.background = "transparent";

					var imageTemplate = "";
					if (visualObjNewPopup.image.typeBl === 'imageBl') {
						imageTemplate = "<div class=\"widget-image-item-block\" style=\"background: url("+visualObjNewPopup.image.url+") center no-repeat;background-size: cover;width:"+visualObjNewPopup.image.img_item_widthpx+"px;height:"+visualObjNewPopup.image.img_item_heightpx+"px\"></div>";
					} else if (visualObjNewPopup.image.typeBl === 'videoBl') {
						imageTemplate = "<div class=\"widget-video-item-block\" style=\"width:"+visualObjNewPopup.image.img_item_widthpx+"px;height:"+visualObjNewPopup.image.img_item_heightpx+"px\"><iframe data-auto=\""+visualObjNewPopup.image.autoplay+"\" allow=\"autoplay; encrypted-media\" class=\"video-element-ifrm\" src=\""+visualObjNewPopup.image.videoUrl+"\" frameborder=\"0\" allowfullscreen></iframe></div>";
						isVideo = true;
					} else if (visualObjNewPopup.image.typeBl === 'paddingBl') {
						imageTemplate = "";
					}
			
					widgetImageLGWG.innerHTML = imageTemplate;

					if (visualObjNewPopup.image.img_item_type === LeadCore.constants.alignToAllSize) {
		                widgetImageLGWG.classList.add('widget-image-has-full-wh');
		            }

		            if (visualObjNewPopup.image.img_item_type === LeadCore.constants.alignToUserSize) {
						const itemContainer = widgetImageLGWG.querySelector('.widget-image-item-block');
						if (itemContainer) {
                            itemContainer.style.borderRadius = LGWGService.getImageBorderRadius(visualObjNewPopup.image.borderRadius) + 'px';
						}
		                if (visualObjNewPopup.image.img_item_align === LeadCore.constants.alignOnCenter)
		                	widgetImageLGWG.classList.add('widget-image-has-center-orient');

		                if (visualObjNewPopup.image.img_item_align === LeadCore.constants.alignOnTop)
		                	widgetImageLGWG.classList.add('widget-image-has-top-orient');

		                if (visualObjNewPopup.image.img_item_align === LeadCore.constants.alignOnBottom)
		                	widgetImageLGWG.classList.add('widget-image-has-bottom-orient');
		            }

		            if(isVideo) {
						fillVideoArray();
					}
				}


				if (visualObjNewPopup.image.place === LeadCore.constants.fromLeft && isFormUnderContent) {
					widgetImageLGWG.classList.add('widget-image-left');
					widgetMainWRLGWG.classList.add('widget-main-img-left');
					
					widgetMainWRLGWG.style.marginLeft  = visualObjNewPopup.image.width - 16 + 'px';
					widgetMainWRLGWG.style.marginRight = 0;
					
					var borderSlice = 0;
					if (visualObjNewPopup.bg.border && visualObjNewPopup.bg.border.enable && visualObjNewPopup.bg.border.thickness) {
						borderSlice = (2 * visualObjNewPopup.bg.border.thickness) - 1;
					}
					LGWGNewColorPod.style.width = (visualObjNewPopup.dhVisual.widget_width_nopx - visualObjNewPopup.image.width - borderSlice) + "px";
					LGWGNewColorPod.style.left = "auto";
					LGWGNewColorPod.style.right = "0";
				}

				if (visualObjNewPopup.image.place === LeadCore.constants.fromRight && isFormUnderContent) {
					widgetImageLGWG.classList.add('widget-image-right');
					widgetMainWRLGWG.classList.add('widget-main-img-right');
					
					widgetMainWRLGWG.style.marginRight  = visualObjNewPopup.image.width - 16 + 'px';
					widgetMainWRLGWG.style.marginLeft = 0;

					var borderSlice = 0;
					if (visualObjNewPopup.bg.border && visualObjNewPopup.bg.border.enable && visualObjNewPopup.bg.border.thickness) {
						borderSlice = (2 * visualObjNewPopup.bg.border.thickness) - 1;
					}

					LGWGNewColorPod.style.width = (visualObjNewPopup.dhVisual.widget_width_nopx - visualObjNewPopup.image.width - borderSlice) + "px";
					LGWGNewColorPod.style.left = "0";
					LGWGNewColorPod.style.right = "auto";
				}

				if (visualObjNewPopup.image.place === LeadCore.constants.fromTop) {
					widgetImageLGWG.classList.add('widget-image-top');
					widgetMainWRLGWG.classList.add('widget-main-img-top');
					
					widgetImageLGWG.style.width = '100%';
					widgetImageLGWG.style.height = visualObjNewPopup.image.height + 'px';
					widgetMainWRLGWG.style.marginLeft   = 0;
					widgetMainWRLGWG.style.marginRight  = 0;
					widgetMainWRLGWG.style.marginTop    = visualObjNewPopup.image.height + 'px';
					widgetMainWRLGWG.style.marginBottom = 0;
				}

				if (visualObjNewPopup.image.place === LeadCore.constants.fromBottom) {
					widgetImageLGWG.classList.add('widget-image-bottom');
					widgetMainWRLGWG.classList.add('widget-main-img-bottom');
					
					widgetImageLGWG.style.width = '100%';
					widgetImageLGWG.style.height = visualObjNewPopup.image.height + 'px';
					widgetMainWRLGWG.style.marginLeft   = 0;
					widgetMainWRLGWG.style.marginRight  = 0;
					widgetMainWRLGWG.style.marginTop    = 0;
					widgetMainWRLGWG.style.marginBottom = visualObjNewPopup.image.height + 'px';
				}

				if (visualObjNewPopup.image.place === LeadCore.constants.fromLeft && isFormToAllWidth) {
					widgetImageLGWG.classList.add('widget-image-left-all');
					widgetMainWRLGWG.classList.add('widget-main-img-left');
					
					widgetImageLGWG.style.height = visualObjNewPopup.image.height + 'px';
					widgetMainWRLGWG.style.marginLeft  = visualObjNewPopup.image.width - 16 + 'px';
					widgetMainWRLGWG.style.marginRight = 0;
					setStylesToFormBL(true);
					setStylesToFormExtBL(true);
				}

				if (visualObjNewPopup.image.place === LeadCore.constants.fromRight && isFormToAllWidth) {
					widgetImageLGWG.classList.add('widget-image-right-all');
					widgetMainWRLGWG.classList.add('widget-main-img-right');
					
					widgetImageLGWG.style.height = visualObjNewPopup.image.height + 'px';
					widgetMainWRLGWG.style.marginRight  = visualObjNewPopup.image.width - 16 + 'px';
					widgetMainWRLGWG.style.marginLeft = 0;
					setStylesToFormBL(false);
					setStylesToFormExtBL(false);
				}

				if ((!visualObjNewPopup.button.enable && !visualObjNewPopup.form.enable && (visualObjNewPopup.formExt && !visualObjNewPopup.formExt.enable)) && 
					(visualObjNewPopup.image.place === LeadCore.constants.fromRight || visualObjNewPopup.image.place === LeadCore.constants.fromLeft)) {
					
					widgetImageLGWG.style.height = "100%";
				}

				function getAllNextSiblings(element) {
				    var out = [];
				    while(element.nextSibling) {
				        out.push(element = element.nextSibling);
				    }

				    return out;
				}

				function setStylesToFormBL(isLeft) {
					if (LGWGLiFormBtn) {
						LGWGLiFormBtn.style.width = (visualObjNewPopup.dhVisual.CP_width - 95) + 'px';
						if (isLeft) {
							LGWGLiFormBtn.style.marginLeft = -visualObjNewPopup.image.width + 'px';
						} else {
							LGWGLiFormBtn.style.marginRight = -visualObjNewPopup.image.width + 'px';
						}

						var formSiblingsR = getAllNextSiblings(LGWGLiFormBtn);
						for(var i = 0; i < formSiblingsR.length; i++) {
							formSiblingsR[i].style.width = (visualObjNewPopup.dhVisual.CP_width - 95) + 'px';
							if (isLeft) {
								formSiblingsR[i].style.marginLeft = -visualObjNewPopup.image.width + 'px';
							} else {
								formSiblingsR[i].style.marginRight = -visualObjNewPopup.image.width + 'px';
							}
						}
					}
				}

				function setStylesToFormExtBL(isLeft) {
					if (LGWGLiFormExtBtn) {
						LGWGLiFormExtBtn.style.width = (visualObjNewPopup.dhVisual.CP_width - 95) + 'px';
						if (isLeft) {
							LGWGLiFormExtBtn.style.marginLeft = -visualObjNewPopup.image.width + 'px';
						} else {
							LGWGLiFormExtBtn.style.marginRight = -visualObjNewPopup.image.width + 'px';
						}

						var formSiblingsR = getAllNextSiblings(LGWGLiFormExtBtn);
						for(var i = 0; i < formSiblingsR.length; i++) {
							formSiblingsR[i].style.width = (visualObjNewPopup.dhVisual.CP_width - 95) + 'px';
							if (isLeft) {
								formSiblingsR[i].style.marginLeft = -visualObjNewPopup.image.width + 'px';
							} else {
								formSiblingsR[i].style.marginRight = -visualObjNewPopup.image.width + 'px';
							}
						}
					}
				}
			}
		},
		setOutsideClickHandler: function(windowElement, documentElement) {
			windowElement.onclick = function(event) {
				if(LGWGService.clearDatetime) {
					LGWGService.clearDatetime();
				}

				if(LGWGService.clearDropdown) {
					LGWGService.clearDropdown();
				}
			}
		},
		prepareHiddenFields: function(hiddenList, content) {
			hiddenList.forEach(hiddenField => {
				content[hiddenField.id] = this.checkHiddenTypes(hiddenField);
			});
		},
		checkHiddenTypes: function(field) {
			switch (field.fieldType.type) {
				case 'utm_source':
					return this.checkUtmTagRule('utm_source', !field.utmRefPage.currentPage);

				case 'utm_medium':
					return this.checkUtmTagRule('utm_medium', !field.utmRefPage.currentPage);

				case 'utm_campaign':
					return this.checkUtmTagRule('utm_campaign', !field.utmRefPage.currentPage);

				case 'utm_term':
					return this.checkUtmTagRule('utm_term', !field.utmRefPage.currentPage);

				case 'utm_content':
					return this.checkUtmTagRule('utm_content', !field.utmRefPage.currentPage);

				case 'referrer':
					return this.checkReferrerRule('referrer', !field.utmRefPage.currentPage);

				case 'page_url':
					return window.location.href;

				case 'custom_parameter':
					return this.getURLTag(field.customParamValue);

				case 'browser_language':
					return this.getBrowserLanguage();

				case 'device_type':
					return this.getDeviceType();

				case 'device_os':
					return this.getBrowserOS();

				case 'timezone':
					return this.getBrowserTimezone();

				case 'coupon':
					return 'COUPON_LIST_LGWG';

				case 'session_number':
					return '' + LeadCore.visit.visitInfo.visitNo;

				case 'pageviews':
					return '' + (LeadCore.visit.visitInfo.actionsCount + 1);

				case 'cookie':
					return this.getBrowserCookie(field.cookieValue);

				case 'user_value':
					return field.customUserValue;

				default:
            		return '';
			}
		},
		getDeviceType: function() {
			const ua = navigator.userAgent;
			if (/(tablet|ipad|playbook|silk)|(android(?!.*mobi))/i.test(ua)) {
				return 'tablet';
			}
			if (/Mobile|iP(hone|od)|Android|BlackBerry|IEMobile|Kindle|Silk-Accelerated|(hpw|web)OS|Opera M(obi|ini)/.test(ua)) {
				return 'mobile';
			}

			return 'desktop';
		},
		getBrowserLanguage: function() {
			return navigator.language || navigator.userLanguage; 
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
				os = 'iOS';
			} else if (windowsPlatforms.indexOf(platform) !== -1) {
				os = 'Windows';
			} else if (/Android/.test(userAgent)) {
				os = 'Android';
			} else if (!os && /Linux/.test(platform)) {
				os = 'Linux';
			}

			return os;
		},
		getBrowserTimezone: function() {
			const offset = new Date().getTimezoneOffset(), o = Math.abs(offset);
    		return 'UTC' + (offset < 0 ? "+" : "-") + ("00" + Math.floor(o / 60)).slice(-2) + ":" + ("00" + (o % 60)).slice(-2);
		},
		getBrowserCookie: function(cookieName) {
			return LeadCore.getCookie(cookieName);
		},
		checkReferrerRule: function(tag, isFirstPage) {
			if (isFirstPage) {
				const cookieName = tag + 'URL';
				return decodeURIComponent(this.getBrowserCookie(cookieName));
			} else {
				return document.referrer;
			}
		},
		checkUtmTagRule: function(tag, isFirstPage) {
			if (isFirstPage) {
				const cookieName = tag + 'URL';
				return decodeURIComponent(this.getBrowserCookie(cookieName));
			} else {
				return this.getURLTag(tag);
			}
		},
		getURLTag: function(tag) {
			const url = new URL(window.location.href);
			return url.searchParams.get(tag);
		},
		getHrFlexedPosSel: function(type) {
			var className = '';

            if (type === 0)
                className = 'align-flexed-pos-left';

            if (type === 1)
                className = 'align-flexed-pos-center';

            if (type === 2)
                className = 'align-flexed-pos-right';

            return className;
		},
		showHideDigits: function(nullData, daysWR, hoursWR, minutesWR) {
			if (!nullData.d) {
				daysWR.classList.add("hide-current-type");
			}
			if (!nullData.h) {
				hoursWR.classList.add("hide-current-type");
			}
			if (!nullData.m) {
				minutesWR.classList.add("hide-current-type");
			}
		},
		getTimerItemLabel: function(item, text) {
			return item.design.tempInterval.enable ? "<div class=\"timer-items_label\" style=\"width:"+((2 * item.design.bgWidth) + (item.design.bgWidth * 0.2))+"px;font-size:"+item.design.fontLabelSize+"px;font-family:"+item.design.fontLabel.fontFamily+";color:"+item.design.colorIntervalName+"\">"+text+"</div>" : "";
		},
		getTimerItemLabelSeconds: function(item, text) {
			return item.design.tempInterval.enable ? "<div class=\"timer-items_label\" style=\"font-size:"+item.design.fontLabelSize+"px;font-family:"+item.design.fontLabel.fontFamily+";color:"+item.design.colorIntervalName+"\">"+text+"</div>" : "";
		},
		getTimerItemBlock: function(item, text, type) {
			return  "<div id=\""+item.ids+"_"+item.counter+"_"+type+"\" class=\"timer-items_item\">"+
						"<div class=\"timer-items_item-bgs-wrapper\">"+
							"<div class=\"timer-items_item-bgs\" style=\"width:"+((2 * item.design.bgWidth) + (item.design.bgWidth * 0.2))+"px;font-size:"+item.design.fontNumberSize+"px;font-family:"+item.design.font.fontFamily+";color:"+item.design.colorText+"\">"+
								"<div class=\"timer-item-block\" style=\"width:"+item.design.bgWidth+"px;height:"+item.design.bgHeight+"px;background:"+LGWGService.getRGBAColorItems(item.design.colorBG, item.design.opacity)+";border-radius:"+item.design.radius+"px\">"+
									"<span style=\"line-height:"+item.design.bgHeight+"px\">0</span>"+
								"</div>"+
								"<div class=\"timer-item-block\" style=\"width:"+item.design.bgWidth+"px;height:"+item.design.bgHeight+"px;background:"+LGWGService.getRGBAColorItems(item.design.colorBG, item.design.opacity)+";border-radius:"+item.design.radius+"px\">"+
									"<span style=\"line-height:"+item.design.bgHeight+"px\">0</span>"+
								"</div>"+
							"</div>"+
							"<div class=\"timer-items_dots\" style=\"width:"+(0.5 * item.design.bgWidth)+"px; height:"+(0.5 * item.design.bgHeight)+"px\">"+
								"<div style=\"background:"+item.design.colorDevider+"\"></div>"+
								"<div style=\"background:"+item.design.colorDevider+"\"></div>"+
							"</div>"+
						"</div>"+
						this.getTimerItemLabel(item, text)+
					"</div>";
		},
		getTimerItemBlockSeconds: function(item, text) {
			return  "<div id=\""+item.ids+"_"+item.counter+"_secs\" class=\"timer-items_item\">"+
						"<div class=\"timer-items_item-bgs-wrapper\">"+
							"<div class=\"timer-items_item-bgs\" style=\"width:"+((2 * item.design.bgWidth) + (item.design.bgWidth * 0.2))+"px;font-size:"+item.design.fontNumberSize+"px;font-family:"+item.design.font.fontFamily+";color:"+item.design.colorText+"\">"+
								"<div class=\"timer-item-block\" style=\"width:"+item.design.bgWidth+"px;height:"+item.design.bgHeight+"px;background:"+LGWGService.getRGBAColorItems(item.design.colorBG, item.design.opacity)+";border-radius:"+item.design.radius+"px\">"+
									"<span style=\"line-height:"+item.design.bgHeight+"px\">0</span>"+
								"</div>"+
								"<div class=\"timer-item-block\" style=\"width:"+item.design.bgWidth+"px;height:"+item.design.bgHeight+"px;background:"+LGWGService.getRGBAColorItems(item.design.colorBG, item.design.opacity)+";border-radius:"+item.design.radius+"px\">"+
									"<span style=\"line-height:"+item.design.bgHeight+"px\">0</span>"+
								"</div>"+
							"</div>"+
						"</div>"+
						this.getTimerItemLabelSeconds(item, text)+
					"</div>";
		},
		//TIMER SERVICE
		getTimerMarkup: function(timerModel) {
			return "<div><div class=\"timer-wrapper "+this.getHrFlexedPosSel(timerModel.design.align.type)+"\">"+
						"<div class=\"timer-items\">"+
							this.getTimerItemBlock(timerModel, timerModel.design.tempInterval.dText, 'days')+
							this.getTimerItemBlock(timerModel, timerModel.design.tempInterval.hText, 'hours')+
							this.getTimerItemBlock(timerModel, timerModel.design.tempInterval.mText, 'mins')+
							this.getTimerItemBlockSeconds(timerModel, timerModel.design.tempInterval.sText)+
						"</div>"+
				  	"</div></div>";
		},
		isGMT: function(item) {
			return item.type.type === 0 && item.timezoneType === 'gmt';
		},
		getCountDownMS: function(model) {
			return (model.d * 86400000) + (model.h * 3600000) + (model.m * 60000) + (model.s * 1000);
		},
	    getTimeRemaining: function(endtime, offsetTZ) {
	    	const currentTime = new Date();
			const total = endtime.getTime() - currentTime.getTime() - offsetTZ;
			const seconds = Math.floor((total / 1000) % 60);
			const minutes = Math.floor((total / 1000 / 60) % 60);
			const hours = Math.floor((total / (1000 * 60 * 60)) % 24);
			const days = Math.floor(total / (1000 * 60 * 60 * 24));

			return {
				total,
				days,
				hours,
				minutes,
				seconds
			};
		},
		prepareItemTime: function(data) {
	    	return ('0' + data).slice(-2);
	    }
	};
})();

LGWGService.setOutsideClickHandler(window);

(function() {
	LeadCoreDotHunterUtils = {
	    appearAfterClose: false,
	    paused: false,
	    initDot: function(pointContent, point, signal1, signal2, signal3) {
	        LeadCoreDotHunterUtils.point = point;
	        LeadCoreDotHunterUtils.pointContent = pointContent;
	        LeadCoreDotHunterUtils.signal1 = signal1;
	        LeadCoreDotHunterUtils.signal2 = signal2;
	        LeadCoreDotHunterUtils.signal3 = signal3;
	        
	    },
	    stop: function () {
	        LeadCoreDotHunterUtils.pointContent.forEach(node => {
                if (node.nodeName === '#comment') return;
	            node.classList.add('lgwg-none-imp-animation');
	        });
	        LeadCoreDotHunterUtils.point.classList.add('lgwg-none-imp-animation');
	        LeadCoreDotHunterUtils.signal1.classList.add('lgwg-none-imp');
	        LeadCoreDotHunterUtils.signal2.classList.add('lgwg-none-imp');
	        LeadCoreDotHunterUtils.signal3.classList.add('lgwg-none-imp');
	    },
	    pause: function () {
	        LeadCoreDotHunterUtils.pointContent.forEach(node => {
                if (node.nodeName === '#comment') return;
	            node.style.animation = 'none';
	        });
	        LeadCoreDotHunterUtils.point.style.animation = 'none';
	        LeadCoreDotHunterUtils.signal1.style.animation = 'none';
	        LeadCoreDotHunterUtils.signal2.style.animation = 'none';
	        LeadCoreDotHunterUtils.signal3.style.animation = 'none';
	    },
	    play: function () {
	        LeadCoreDotHunterUtils.pointContent.forEach(node => {
                if (node.nodeName === '#comment') return;
	            node.style.animation = 'point__ico 5s 4s ease infinite';
	        });
	        LeadCoreDotHunterUtils.point.style.animation = 'point 5s 4s ease infinite';
	        LeadCoreDotHunterUtils.signal1.style.animation = 'point__signal__1 5s 5s linear infinite';
	        LeadCoreDotHunterUtils.signal2.style.animation = 'point__signal__2 5s 5.4s linear infinite';
	        LeadCoreDotHunterUtils.signal3.style.animation = 'point__signal__3 5s 5.8s linear infinite';
	    },
	    start: function () {
	        LeadCoreDotHunterUtils.paused = false;
	        LeadCoreDotHunterUtils.point.style.animation = `appear .6s ${this.appearAfterClose ? '0s' : '2s'} ease 1`;
	        LeadCoreDotHunterUtils.pointContent.forEach(node => {
                if (node.nodeName === '#comment') return;
	            node.style.animation = `point__ico 4s ${this.appearAfterClose ? '0s' : '2s'} ease 1`;
	        });
	        LeadCoreDotHunterUtils.signal1.style.animation = `point__signal__1 6s ${this.appearAfterClose ? '1s' : '4s'}  linear 1`;
	        LeadCoreDotHunterUtils.signal2.style.animation = `point__signal__2 6s ${this.appearAfterClose ? '1.4s' : '4.4s'} linear 1`;
	        LeadCoreDotHunterUtils.signal3.style.animation = `point__signal__3 6s ${this.appearAfterClose ? '1.8s' : '4.8s'} linear 1`;

	        setTimeout(() => {
	        	LeadCoreDotHunterUtils.point.classList.add('no-scale');
	        }, 2600);

	        setTimeout(() => {
	            !LeadCoreDotHunterUtils.paused && LeadCoreDotHunterUtils.pause();
	        }, 6000);

	        setTimeout(() => {
	            !LeadCoreDotHunterUtils.paused && LeadCoreDotHunterUtils.play();
	        }, 6100);

	        LeadCoreDotHunterUtils.appearAfterClose = true;
	    },
	    pauseMobile: function () {
	        LeadCoreDotHunterUtils.paused = true;
	        LeadCoreDotHunterUtils.pause();
	    }
	};
	LG_FA5Pack = [
		"fab fa-500px",
		"fab fa-accessible-icon",
		"fab fa-accusoft",
		"fab fa-acquisitions-incorporated",
		"fab fa-adn",
		"fab fa-adobe",
		"fab fa-adversal",
		"fab fa-affiliatetheme",
		"fab fa-airbnb",
		"fab fa-algolia",
		"fab fa-alipay",
		"fab fa-amazon",
		"fab fa-amazon-pay",
		"fab fa-amilia",
		"fab fa-android",
		"fab fa-angellist",
		"fab fa-angrycreative",
		"fab fa-angular",
		"fab fa-app-store",
		"fab fa-app-store-ios",
		"fab fa-apper",
		"fab fa-apple",
		"fab fa-apple-pay",
		"fab fa-artstation",
		"fab fa-asymmetrik",
		"fab fa-atlassian",
		"fab fa-audible",
		"fab fa-autoprefixer",
		"fab fa-avianex",
		"fab fa-aviato",
		"fab fa-aws",
		"fab fa-bandcamp",
		"fab fa-battle-net",
		"fab fa-behance",
		"fab fa-behance-square",
		"fab fa-bimobject",
		"fab fa-bitbucket",
		"fab fa-bitcoin",
		"fab fa-bity",
		"fab fa-black-tie",
		"fab fa-blackberry",
		"fab fa-blogger",
		"fab fa-blogger-b",
		"fab fa-bluetooth",
		"fab fa-bluetooth-b",
		"fab fa-bootstrap",
		"fab fa-btc",
		"fab fa-buffer",
		"fab fa-buromobelexperte",
		"fab fa-buy-n-large",
		"fab fa-buysellads",
		"fab fa-canadian-maple-leaf",
		"fab fa-cc-amazon-pay",
		"fab fa-cc-amex",
		"fab fa-cc-apple-pay",
		"fab fa-cc-diners-club",
		"fab fa-cc-discover",
		"fab fa-cc-jcb",
		"fab fa-cc-mastercard",
		"fab fa-cc-paypal",
		"fab fa-cc-stripe",
		"fab fa-cc-visa",
		"fab fa-centercode",
		"fab fa-centos",
		"fab fa-chrome",
		"fab fa-chromecast",
		"fab fa-cloudscale",
		"fab fa-cloudsmith",
		"fab fa-cloudversify",
		"fab fa-codepen",
		"fab fa-codiepie",
		"fab fa-confluence",
		"fab fa-connectdevelop",
		"fab fa-contao",
		"fab fa-cotton-bureau",
		"fab fa-cpanel",
		"fab fa-creative-commons",
		"fab fa-creative-commons-by",
		"fab fa-creative-commons-nc",
		"fab fa-creative-commons-nc-eu",
		"fab fa-creative-commons-nc-jp",
		"fab fa-creative-commons-nd",
		"fab fa-creative-commons-pd",
		"fab fa-creative-commons-pd-alt",
		"fab fa-creative-commons-remix",
		"fab fa-creative-commons-sa",
		"fab fa-creative-commons-sampling",
		"fab fa-creative-commons-sampling-plus",
		"fab fa-creative-commons-share",
		"fab fa-creative-commons-zero",
		"fab fa-critical-role",
		"fab fa-css3",
		"fab fa-css3-alt",
		"fab fa-cuttlefish",
		"fab fa-d-and-d",
		"fab fa-d-and-d-beyond",
		"fab fa-dailymotion",
		"fab fa-dashcube",
		"fab fa-delicious",
		"fab fa-deploydog",
		"fab fa-deskpro",
		"fab fa-dev",
		"fab fa-deviantart",
		"fab fa-dhl",
		"fab fa-diaspora",
		"fab fa-digg",
		"fab fa-digital-ocean",
		"fab fa-discord",
		"fab fa-discourse",
		"fab fa-dochub",
		"fab fa-docker",
		"fab fa-draft2digital",
		"fab fa-dribbble",
		"fab fa-dribbble-square",
		"fab fa-dropbox",
		"fab fa-drupal",
		"fab fa-dyalog",
		"fab fa-earlybirds",
		"fab fa-ebay",
		"fab fa-edge",
		"fab fa-elementor",
		"fab fa-ello",
		"fab fa-ember",
		"fab fa-empire",
		"fab fa-envira",
		"fab fa-erlang",
		"fab fa-ethereum",
		"fab fa-etsy",
		"fab fa-evernote",
		"fab fa-expeditedssl",
		"fab fa-facebook",
		"fab fa-facebook-f",
		"fab fa-facebook-messenger",
		"fab fa-facebook-square",
		"fab fa-fantasy-flight-games",
		"fab fa-fedex",
		"fab fa-fedora",
		"fab fa-figma",
		"fab fa-firefox",
		"fab fa-firefox-browser",
		"fab fa-first-order",
		"fab fa-first-order-alt",
		"fab fa-firstdraft",
		"fab fa-flickr",
		"fab fa-flipboard",
		"fab fa-fly",
		"fab fa-font-awesome",
		"fab fa-font-awesome-alt",
		"fab fa-font-awesome-flag",
		"fab fa-fonticons",
		"fab fa-fonticons-fi",
		"fab fa-fort-awesome",
		"fab fa-fort-awesome-alt",
		"fab fa-forumbee",
		"fab fa-foursquare",
		"fab fa-free-code-camp",
		"fab fa-freebsd",
		"fab fa-fulcrum",
		"fab fa-galactic-republic",
		"fab fa-galactic-senate",
		"fab fa-get-pocket",
		"fab fa-gg",
		"fab fa-gg-circle",
		"fab fa-git",
		"fab fa-git-alt",
		"fab fa-git-square",
		"fab fa-github",
		"fab fa-github-alt",
		"fab fa-github-square",
		"fab fa-gitkraken",
		"fab fa-gitlab",
		"fab fa-gitter",
		"fab fa-glide",
		"fab fa-glide-g",
		"fab fa-gofore",
		"fab fa-goodreads",
		"fab fa-goodreads-g",
		"fab fa-google",
		"fab fa-google-drive",
		"fab fa-google-play",
		"fab fa-google-plus",
		"fab fa-google-plus-g",
		"fab fa-google-plus-square",
		"fab fa-google-wallet",
		"fab fa-gratipay",
		"fab fa-grav",
		"fab fa-gripfire",
		"fab fa-grunt",
		"fab fa-gulp",
		"fab fa-hacker-news",
		"fab fa-hacker-news-square",
		"fab fa-hackerrank",
		"fab fa-hips",
		"fab fa-hire-a-helper",
		"fab fa-hooli",
		"fab fa-hornbill",
		"fab fa-hotjar",
		"fab fa-houzz",
		"fab fa-html5",
		"fab fa-hubspot",
		"fab fa-ideal",
		"fab fa-imdb",
		"fab fa-instagram",
		"fab fa-instagram-square",
		"fab fa-intercom",
		"fab fa-internet-explorer",
		"fab fa-invision",
		"fab fa-ioxhost",
		"fab fa-itch-io",
		"fab fa-itunes",
		"fab fa-itunes-note",
		"fab fa-java",
		"fab fa-jedi-order",
		"fab fa-jenkins",
		"fab fa-jira",
		"fab fa-joget",
		"fab fa-joomla",
		"fab fa-js",
		"fab fa-js-square",
		"fab fa-jsfiddle",
		"fab fa-kaggle",
		"fab fa-keybase",
		"fab fa-keycdn",
		"fab fa-kickstarter",
		"fab fa-kickstarter-k",
		"fab fa-korvue",
		"fab fa-laravel",
		"fab fa-lastfm",
		"fab fa-lastfm-square",
		"fab fa-leanpub",
		"fab fa-less",
		"fab fa-line",
		"fab fa-linkedin",
		"fab fa-linkedin-in",
		"fab fa-linode",
		"fab fa-linux",
		"fab fa-lyft",
		"fab fa-magento",
		"fab fa-mailchimp",
		"fab fa-mandalorian",
		"fab fa-markdown",
		"fab fa-mastodon",
		"fab fa-maxcdn",
		"fab fa-mdb",
		"fab fa-medapps",
		"fab fa-medium",
		"fab fa-medium-m",
		"fab fa-medrt",
		"fab fa-meetup",
		"fab fa-megaport",
		"fab fa-mendeley",
		"fab fa-microblog",
		"fab fa-microsoft",
		"fab fa-mix",
		"fab fa-mixcloud",
		"fab fa-mixer",
		"fab fa-mizuni",
		"fab fa-modx",
		"fab fa-monero",
		"fab fa-napster",
		"fab fa-neos",
		"fab fa-nimblr",
		"fab fa-node",
		"fab fa-node-js",
		"fab fa-npm",
		"fab fa-ns8",
		"fab fa-nutritionix",
		"fab fa-odnoklassniki",
		"fab fa-odnoklassniki-square",
		"fab fa-old-republic",
		"fab fa-opencart",
		"fab fa-openid",
		"fab fa-opera",
		"fab fa-optin-monster",
		"fab fa-orcid",
		"fab fa-osi",
		"fab fa-page4",
		"fab fa-pagelines",
		"fab fa-palfed",
		"fab fa-patreon",
		"fab fa-paypal",
		"fab fa-penny-arcade",
		"fab fa-periscope",
		"fab fa-phabricator",
		"fab fa-phoenix-framework",
		"fab fa-phoenix-squadron",
		"fab fa-php",
		"fab fa-pied-piper",
		"fab fa-pied-piper-alt",
		"fab fa-pied-piper-hat",
		"fab fa-pied-piper-pp",
		"fab fa-pied-piper-square",
		"fab fa-pinterest",
		"fab fa-pinterest-p",
		"fab fa-pinterest-square",
		"fab fa-playstation",
		"fab fa-product-hunt",
		"fab fa-pushed",
		"fab fa-python",
		"fab fa-qq",
		"fab fa-quinscape",
		"fab fa-quora",
		"fab fa-r-project",
		"fab fa-raspberry-pi",
		"fab fa-ravelry",
		"fab fa-react",
		"fab fa-reacteurope",
		"fab fa-readme",
		"fab fa-rebel",
		"fab fa-red-river",
		"fab fa-reddit",
		"fab fa-reddit-alien",
		"fab fa-reddit-square",
		"fab fa-redhat",
		"fab fa-renren",
		"fab fa-replyd",
		"fab fa-researchgate",
		"fab fa-resolving",
		"fab fa-rev",
		"fab fa-rocketchat",
		"fab fa-rockrms",
		"fab fa-safari",
		"fab fa-salesforce",
		"fab fa-sass",
		"fab fa-schlix",
		"fab fa-scribd",
		"fab fa-searchengin",
		"fab fa-sellcast",
		"fab fa-sellsy",
		"fab fa-servicestack",
		"fab fa-shirtsinbulk",
		"fab fa-shopify",
		"fab fa-shopware",
		"fab fa-simplybuilt",
		"fab fa-sistrix",
		"fab fa-sith",
		"fab fa-sketch",
		"fab fa-skyatlas",
		"fab fa-skype",
		"fab fa-slack",
		"fab fa-slack-hash",
		"fab fa-slideshare",
		"fab fa-snapchat",
		"fab fa-snapchat-ghost",
		"fab fa-snapchat-square",
		"fab fa-soundcloud",
		"fab fa-sourcetree",
		"fab fa-speakap",
		"fab fa-speaker-deck",
		"fab fa-spotify",
		"fab fa-squarespace",
		"fab fa-stack-exchange",
		"fab fa-stack-overflow",
		"fab fa-stackpath",
		"fab fa-staylinked",
		"fab fa-steam",
		"fab fa-steam-square",
		"fab fa-steam-symbol",
		"fab fa-sticker-mule",
		"fab fa-strava",
		"fab fa-stripe",
		"fab fa-stripe-s",
		"fab fa-studiovinari",
		"fab fa-stumbleupon",
		"fab fa-stumbleupon-circle",
		"fab fa-superpowers",
		"fab fa-supple",
		"fab fa-suse",
		"fab fa-swift",
		"fab fa-symfony",
		"fab fa-teamspeak",
		"fab fa-telegram",
		"fab fa-telegram-plane",
		"fab fa-tencent-weibo",
		"fab fa-the-red-yeti",
		"fab fa-themeco",
		"fab fa-themeisle",
		"fab fa-think-peaks",
		"fab fa-trade-federation",
		"fab fa-trello",
		"fab fa-tripadvisor",
		"fab fa-tumblr",
		"fab fa-tumblr-square",
		"fab fa-twitch",
		"fab fa-twitter",
		"fab fa-twitter-square",
		"fab fa-typo3",
		"fab fa-uber",
		"fab fa-ubuntu",
		"fab fa-uikit",
		"fab fa-umbraco",
		"fab fa-uniregistry",
		"fab fa-unity",
		"fab fa-untappd",
		"fab fa-ups",
		"fab fa-usb",
		"fab fa-usps",
		"fab fa-ussunnah",
		"fab fa-vaadin",
		"fab fa-viacoin",
		"fab fa-viadeo",
		"fab fa-viadeo-square",
		"fab fa-viber",
		"fab fa-vimeo",
		"fab fa-vimeo-square",
		"fab fa-vimeo-v",
		"fab fa-vine",
		"fab fa-vk",
		"fab fa-vnv",
		"fab fa-vuejs",
		"fab fa-waze",
		"fab fa-weebly",
		"fab fa-weibo",
		"fab fa-weixin",
		"fab fa-whatsapp",
		"fab fa-whatsapp-square",
		"fab fa-whmcs",
		"fab fa-wikipedia-w",
		"fab fa-windows",
		"fab fa-wix",
		"fab fa-wizards-of-the-coast",
		"fab fa-wolf-pack-battalion",
		"fab fa-wordpress",
		"fab fa-wordpress-simple",
		"fab fa-wpbeginner",
		"fab fa-wpexplorer",
		"fab fa-wpforms",
		"fab fa-wpressr",
		"fab fa-xbox",
		"fab fa-xing",
		"fab fa-xing-square",
		"fab fa-y-combinator",
		"fab fa-yahoo",
		"fab fa-yammer",
		"fab fa-yandex",
		"fab fa-yandex-international",
		"fab fa-yarn",
		"fab fa-yelp",
		"fab fa-yoast",
		"fab fa-youtube",
		"fab fa-youtube-square",
		"fab fa-zhihu",
		"far fa-address-book",
		"far fa-address-card",
		"far fa-angry",
		"far fa-arrow-alt-circle-down",
		"far fa-arrow-alt-circle-left",
		"far fa-arrow-alt-circle-right",
		"far fa-arrow-alt-circle-up",
		"far fa-bell",
		"far fa-bell-slash",
		"far fa-bookmark",
		"far fa-building",
		"far fa-calendar",
		"far fa-calendar-alt",
		"far fa-calendar-check",
		"far fa-calendar-minus",
		"far fa-calendar-plus",
		"far fa-calendar-times",
		"far fa-caret-square-down",
		"far fa-caret-square-left",
		"far fa-caret-square-right",
		"far fa-caret-square-up",
		"far fa-chart-bar",
		"far fa-check-circle",
		"far fa-check-square",
		"far fa-circle",
		"far fa-clipboard",
		"far fa-clock",
		"far fa-clone",
		"far fa-closed-captioning",
		"far fa-comment",
		"far fa-comment-alt",
		"far fa-comment-dots",
		"far fa-comments",
		"far fa-compass",
		"far fa-copy",
		"far fa-copyright",
		"far fa-credit-card",
		"far fa-dizzy",
		"far fa-dot-circle",
		"far fa-edit",
		"far fa-envelope",
		"far fa-envelope-open",
		"far fa-eye",
		"far fa-eye-slash",
		"far fa-file",
		"far fa-file-alt",
		"far fa-file-archive",
		"far fa-file-audio",
		"far fa-file-code",
		"far fa-file-excel",
		"far fa-file-image",
		"far fa-file-pdf",
		"far fa-file-powerpoint",
		"far fa-file-video",
		"far fa-file-word",
		"far fa-flag",
		"far fa-flushed",
		"far fa-folder",
		"far fa-folder-open",
		"far fa-frown",
		"far fa-frown-open",
		"far fa-futbol",
		"far fa-gem",
		"far fa-grimace",
		"far fa-grin",
		"far fa-grin-alt",
		"far fa-grin-beam",
		"far fa-grin-beam-sweat",
		"far fa-grin-hearts",
		"far fa-grin-squint",
		"far fa-grin-squint-tears",
		"far fa-grin-stars",
		"far fa-grin-tears",
		"far fa-grin-tongue",
		"far fa-grin-tongue-squint",
		"far fa-grin-tongue-wink",
		"far fa-grin-wink",
		"far fa-hand-lizard",
		"far fa-hand-paper",
		"far fa-hand-peace",
		"far fa-hand-point-down",
		"far fa-hand-point-left",
		"far fa-hand-point-right",
		"far fa-hand-point-up",
		"far fa-hand-pointer",
		"far fa-hand-rock",
		"far fa-hand-scissors",
		"far fa-hand-spock",
		"far fa-handshake",
		"far fa-hdd",
		"far fa-heart",
		"far fa-hospital",
		"far fa-hourglass",
		"far fa-id-badge",
		"far fa-id-card",
		"far fa-image",
		"far fa-images",
		"far fa-keyboard",
		"far fa-kiss",
		"far fa-kiss-beam",
		"far fa-kiss-wink-heart",
		"far fa-laugh",
		"far fa-laugh-beam",
		"far fa-laugh-squint",
		"far fa-laugh-wink",
		"far fa-lemon",
		"far fa-life-ring",
		"far fa-lightbulb",
		"far fa-list-alt",
		"far fa-map",
		"far fa-meh",
		"far fa-meh-blank",
		"far fa-meh-rolling-eyes",
		"far fa-minus-square",
		"far fa-money-bill-alt",
		"far fa-moon",
		"far fa-newspaper",
		"far fa-object-group",
		"far fa-object-ungroup",
		"far fa-paper-plane",
		"far fa-pause-circle",
		"far fa-play-circle",
		"far fa-plus-square",
		"far fa-question-circle",
		"far fa-registered",
		"far fa-sad-cry",
		"far fa-sad-tear",
		"far fa-save",
		"far fa-share-square",
		"far fa-smile",
		"far fa-smile-beam",
		"far fa-smile-wink",
		"far fa-snowflake",
		"far fa-square",
		"far fa-star",
		"far fa-star-half",
		"far fa-sticky-note",
		"far fa-stop-circle",
		"far fa-sun",
		"far fa-surprise",
		"far fa-thumbs-down",
		"far fa-thumbs-up",
		"far fa-times-circle",
		"far fa-tired",
		"far fa-trash-alt",
		"far fa-user",
		"far fa-user-circle",
		"far fa-window-close",
		"far fa-window-maximize",
		"far fa-window-minimize",
		"far fa-window-restore",
		"fas fa-ad",
		"fas fa-address-book",
		"fas fa-address-card",
		"fas fa-adjust",
		"fas fa-air-freshener",
		"fas fa-align-center",
		"fas fa-align-justify",
		"fas fa-align-left",
		"fas fa-align-right",
		"fas fa-allergies",
		"fas fa-ambulance",
		"fas fa-american-sign-language-interpreting",
		"fas fa-anchor",
		"fas fa-angle-double-down",
		"fas fa-angle-double-left",
		"fas fa-angle-double-right",
		"fas fa-angle-double-up",
		"fas fa-angle-down",
		"fas fa-angle-left",
		"fas fa-angle-right",
		"fas fa-angle-up",
		"fas fa-angry",
		"fas fa-ankh",
		"fas fa-apple-alt",
		"fas fa-archive",
		"fas fa-archway",
		"fas fa-arrow-alt-circle-down",
		"fas fa-arrow-alt-circle-left",
		"fas fa-arrow-alt-circle-right",
		"fas fa-arrow-alt-circle-up",
		"fas fa-arrow-circle-down",
		"fas fa-arrow-circle-left",
		"fas fa-arrow-circle-right",
		"fas fa-arrow-circle-up",
		"fas fa-arrow-down",
		"fas fa-arrow-left",
		"fas fa-arrow-right",
		"fas fa-arrow-up",
		"fas fa-arrows-alt",
		"fas fa-arrows-alt-h",
		"fas fa-arrows-alt-v",
		"fas fa-assistive-listening-systems",
		"fas fa-asterisk",
		"fas fa-at",
		"fas fa-atlas",
		"fas fa-atom",
		"fas fa-audio-description",
		"fas fa-award",
		"fas fa-baby",
		"fas fa-baby-carriage",
		"fas fa-backspace",
		"fas fa-backward",
		"fas fa-bacon",
		"fas fa-bahai",
		"fas fa-balance-scale",
		"fas fa-balance-scale-left",
		"fas fa-balance-scale-right",
		"fas fa-ban",
		"fas fa-band-aid",
		"fas fa-barcode",
		"fas fa-bars",
		"fas fa-baseball-ball",
		"fas fa-basketball-ball",
		"fas fa-bath",
		"fas fa-battery-empty",
		"fas fa-battery-full",
		"fas fa-battery-half",
		"fas fa-battery-quarter",
		"fas fa-battery-three-quarters",
		"fas fa-bed",
		"fas fa-beer",
		"fas fa-bell",
		"fas fa-bell-slash",
		"fas fa-bezier-curve",
		"fas fa-bible",
		"fas fa-bicycle",
		"fas fa-biking",
		"fas fa-binoculars",
		"fas fa-biohazard",
		"fas fa-birthday-cake",
		"fas fa-blender",
		"fas fa-blender-phone",
		"fas fa-blind",
		"fas fa-blog",
		"fas fa-bold",
		"fas fa-bolt",
		"fas fa-bomb",
		"fas fa-bone",
		"fas fa-bong",
		"fas fa-book",
		"fas fa-book-dead",
		"fas fa-book-medical",
		"fas fa-book-open",
		"fas fa-book-reader",
		"fas fa-bookmark",
		"fas fa-border-all",
		"fas fa-border-none",
		"fas fa-border-style",
		"fas fa-bowling-ball",
		"fas fa-box",
		"fas fa-box-open",
		"fas fa-box-tissue",
		"fas fa-boxes",
		"fas fa-braille",
		"fas fa-brain",
		"fas fa-bread-slice",
		"fas fa-briefcase",
		"fas fa-briefcase-medical",
		"fas fa-broadcast-tower",
		"fas fa-broom",
		"fas fa-brush",
		"fas fa-bug",
		"fas fa-building",
		"fas fa-bullhorn",
		"fas fa-bullseye",
		"fas fa-burn",
		"fas fa-bus",
		"fas fa-bus-alt",
		"fas fa-business-time",
		"fas fa-calculator",
		"fas fa-calendar",
		"fas fa-calendar-alt",
		"fas fa-calendar-check",
		"fas fa-calendar-day",
		"fas fa-calendar-minus",
		"fas fa-calendar-plus",
		"fas fa-calendar-times",
		"fas fa-calendar-week",
		"fas fa-camera",
		"fas fa-camera-retro",
		"fas fa-campground",
		"fas fa-candy-cane",
		"fas fa-cannabis",
		"fas fa-capsules",
		"fas fa-car",
		"fas fa-car-alt",
		"fas fa-car-battery",
		"fas fa-car-crash",
		"fas fa-car-side",
		"fas fa-caravan",
		"fas fa-caret-down",
		"fas fa-caret-left",
		"fas fa-caret-right",
		"fas fa-caret-square-down",
		"fas fa-caret-square-left",
		"fas fa-caret-square-right",
		"fas fa-caret-square-up",
		"fas fa-caret-up",
		"fas fa-carrot",
		"fas fa-cart-arrow-down",
		"fas fa-cart-plus",
		"fas fa-cash-register",
		"fas fa-cat",
		"fas fa-certificate",
		"fas fa-chair",
		"fas fa-chalkboard",
		"fas fa-chalkboard-teacher",
		"fas fa-charging-station",
		"fas fa-chart-area",
		"fas fa-chart-bar",
		"fas fa-chart-line",
		"fas fa-chart-pie",
		"fas fa-check",
		"fas fa-check-circle",
		"fas fa-check-double",
		"fas fa-check-square",
		"fas fa-cheese",
		"fas fa-chess",
		"fas fa-chess-bishop",
		"fas fa-chess-board",
		"fas fa-chess-king",
		"fas fa-chess-knight",
		"fas fa-chess-pawn",
		"fas fa-chess-queen",
		"fas fa-chess-rook",
		"fas fa-chevron-circle-down",
		"fas fa-chevron-circle-left",
		"fas fa-chevron-circle-right",
		"fas fa-chevron-circle-up",
		"fas fa-chevron-down",
		"fas fa-chevron-left",
		"fas fa-chevron-right",
		"fas fa-chevron-up",
		"fas fa-child",
		"fas fa-church",
		"fas fa-circle",
		"fas fa-circle-notch",
		"fas fa-city",
		"fas fa-clinic-medical",
		"fas fa-clipboard",
		"fas fa-clipboard-check",
		"fas fa-clipboard-list",
		"fas fa-clock",
		"fas fa-clone",
		"fas fa-closed-captioning",
		"fas fa-cloud",
		"fas fa-cloud-download-alt",
		"fas fa-cloud-meatball",
		"fas fa-cloud-moon",
		"fas fa-cloud-moon-rain",
		"fas fa-cloud-rain",
		"fas fa-cloud-showers-heavy",
		"fas fa-cloud-sun",
		"fas fa-cloud-sun-rain",
		"fas fa-cloud-upload-alt",
		"fas fa-cocktail",
		"fas fa-code",
		"fas fa-code-branch",
		"fas fa-coffee",
		"fas fa-cog",
		"fas fa-cogs",
		"fas fa-coins",
		"fas fa-columns",
		"fas fa-comment",
		"fas fa-comment-alt",
		"fas fa-comment-dollar",
		"fas fa-comment-dots",
		"fas fa-comment-medical",
		"fas fa-comment-slash",
		"fas fa-comments",
		"fas fa-comments-dollar",
		"fas fa-compact-disc",
		"fas fa-compass",
		"fas fa-compress",
		"fas fa-compress-alt",
		"fas fa-compress-arrows-alt",
		"fas fa-concierge-bell",
		"fas fa-cookie",
		"fas fa-cookie-bite",
		"fas fa-copy",
		"fas fa-copyright",
		"fas fa-couch",
		"fas fa-credit-card",
		"fas fa-crop",
		"fas fa-crop-alt",
		"fas fa-cross",
		"fas fa-crosshairs",
		"fas fa-crow",
		"fas fa-crown",
		"fas fa-crutch",
		"fas fa-cube",
		"fas fa-cubes",
		"fas fa-cut",
		"fas fa-database",
		"fas fa-deaf",
		"fas fa-democrat",
		"fas fa-desktop",
		"fas fa-dharmachakra",
		"fas fa-diagnoses",
		"fas fa-dice",
		"fas fa-dice-d20",
		"fas fa-dice-d6",
		"fas fa-dice-five",
		"fas fa-dice-four",
		"fas fa-dice-one",
		"fas fa-dice-six",
		"fas fa-dice-three",
		"fas fa-dice-two",
		"fas fa-digital-tachograph",
		"fas fa-directions",
		"fas fa-disease",
		"fas fa-divide",
		"fas fa-dizzy",
		"fas fa-dna",
		"fas fa-dog",
		"fas fa-dollar-sign",
		"fas fa-dolly",
		"fas fa-dolly-flatbed",
		"fas fa-donate",
		"fas fa-door-closed",
		"fas fa-door-open",
		"fas fa-dot-circle",
		"fas fa-dove",
		"fas fa-download",
		"fas fa-drafting-compass",
		"fas fa-dragon",
		"fas fa-draw-polygon",
		"fas fa-drum",
		"fas fa-drum-steelpan",
		"fas fa-drumstick-bite",
		"fas fa-dumbbell",
		"fas fa-dumpster",
		"fas fa-dumpster-fire",
		"fas fa-dungeon",
		"fas fa-edit",
		"fas fa-egg",
		"fas fa-eject",
		"fas fa-ellipsis-h",
		"fas fa-ellipsis-v",
		"fas fa-envelope",
		"fas fa-envelope-open",
		"fas fa-envelope-open-text",
		"fas fa-envelope-square",
		"fas fa-equals",
		"fas fa-eraser",
		"fas fa-ethernet",
		"fas fa-euro-sign",
		"fas fa-exchange-alt",
		"fas fa-exclamation",
		"fas fa-exclamation-circle",
		"fas fa-exclamation-triangle",
		"fas fa-expand",
		"fas fa-expand-alt",
		"fas fa-expand-arrows-alt",
		"fas fa-external-link-alt",
		"fas fa-external-link-square-alt",
		"fas fa-eye",
		"fas fa-eye-dropper",
		"fas fa-eye-slash",
		"fas fa-fan",
		"fas fa-fast-backward",
		"fas fa-fast-forward",
		"fas fa-faucet",
		"fas fa-fax",
		"fas fa-feather",
		"fas fa-feather-alt",
		"fas fa-female",
		"fas fa-fighter-jet",
		"fas fa-file",
		"fas fa-file-alt",
		"fas fa-file-archive",
		"fas fa-file-audio",
		"fas fa-file-code",
		"fas fa-file-contract",
		"fas fa-file-csv",
		"fas fa-file-download",
		"fas fa-file-excel",
		"fas fa-file-export",
		"fas fa-file-image",
		"fas fa-file-import",
		"fas fa-file-invoice",
		"fas fa-file-invoice-dollar",
		"fas fa-file-medical",
		"fas fa-file-medical-alt",
		"fas fa-file-pdf",
		"fas fa-file-powerpoint",
		"fas fa-file-prescription",
		"fas fa-file-signature",
		"fas fa-file-upload",
		"fas fa-file-video",
		"fas fa-file-word",
		"fas fa-fill",
		"fas fa-fill-drip",
		"fas fa-film",
		"fas fa-filter",
		"fas fa-fingerprint",
		"fas fa-fire",
		"fas fa-fire-alt",
		"fas fa-fire-extinguisher",
		"fas fa-first-aid",
		"fas fa-fish",
		"fas fa-fist-raised",
		"fas fa-flag",
		"fas fa-flag-checkered",
		"fas fa-flag-usa",
		"fas fa-flask",
		"fas fa-flushed",
		"fas fa-folder",
		"fas fa-folder-minus",
		"fas fa-folder-open",
		"fas fa-folder-plus",
		"fas fa-font",
		"fas fa-football-ball",
		"fas fa-forward",
		"fas fa-frog",
		"fas fa-frown",
		"fas fa-frown-open",
		"fas fa-funnel-dollar",
		"fas fa-futbol",
		"fas fa-gamepad",
		"fas fa-gas-pump",
		"fas fa-gavel",
		"fas fa-gem",
		"fas fa-genderless",
		"fas fa-ghost",
		"fas fa-gift",
		"fas fa-gifts",
		"fas fa-glass-cheers",
		"fas fa-glass-martini",
		"fas fa-glass-martini-alt",
		"fas fa-glass-whiskey",
		"fas fa-glasses",
		"fas fa-globe",
		"fas fa-globe-africa",
		"fas fa-globe-americas",
		"fas fa-globe-asia",
		"fas fa-globe-europe",
		"fas fa-golf-ball",
		"fas fa-gopuram",
		"fas fa-graduation-cap",
		"fas fa-greater-than",
		"fas fa-greater-than-equal",
		"fas fa-grimace",
		"fas fa-grin",
		"fas fa-grin-alt",
		"fas fa-grin-beam",
		"fas fa-grin-beam-sweat",
		"fas fa-grin-hearts",
		"fas fa-grin-squint",
		"fas fa-grin-squint-tears",
		"fas fa-grin-stars",
		"fas fa-grin-tears",
		"fas fa-grin-tongue",
		"fas fa-grin-tongue-squint",
		"fas fa-grin-tongue-wink",
		"fas fa-grin-wink",
		"fas fa-grip-horizontal",
		"fas fa-grip-lines",
		"fas fa-grip-lines-vertical",
		"fas fa-grip-vertical",
		"fas fa-guitar",
		"fas fa-h-square",
		"fas fa-hamburger",
		"fas fa-hammer",
		"fas fa-hamsa",
		"fas fa-hand-holding",
		"fas fa-hand-holding-heart",
		"fas fa-hand-holding-medical",
		"fas fa-hand-holding-usd",
		"fas fa-hand-holding-water",
		"fas fa-hand-lizard",
		"fas fa-hand-middle-finger",
		"fas fa-hand-paper",
		"fas fa-hand-peace",
		"fas fa-hand-point-down",
		"fas fa-hand-point-left",
		"fas fa-hand-point-right",
		"fas fa-hand-point-up",
		"fas fa-hand-pointer",
		"fas fa-hand-rock",
		"fas fa-hand-scissors",
		"fas fa-hand-sparkles",
		"fas fa-hand-spock",
		"fas fa-hands",
		"fas fa-hands-helping",
		"fas fa-hands-wash",
		"fas fa-handshake",
		"fas fa-handshake-alt-slash",
		"fas fa-handshake-slash",
		"fas fa-hanukiah",
		"fas fa-hard-hat",
		"fas fa-hashtag",
		"fas fa-hat-cowboy",
		"fas fa-hat-cowboy-side",
		"fas fa-hat-wizard",
		"fas fa-hdd",
		"fas fa-head-side-cough",
		"fas fa-head-side-cough-slash",
		"fas fa-head-side-mask",
		"fas fa-head-side-virus",
		"fas fa-heading",
		"fas fa-headphones",
		"fas fa-headphones-alt",
		"fas fa-headset",
		"fas fa-heart",
		"fas fa-heart-broken",
		"fas fa-heartbeat",
		"fas fa-helicopter",
		"fas fa-highlighter",
		"fas fa-hiking",
		"fas fa-hippo",
		"fas fa-history",
		"fas fa-hockey-puck",
		"fas fa-holly-berry",
		"fas fa-home",
		"fas fa-horse",
		"fas fa-horse-head",
		"fas fa-hospital",
		"fas fa-hospital-alt",
		"fas fa-hospital-symbol",
		"fas fa-hospital-user",
		"fas fa-hot-tub",
		"fas fa-hotdog",
		"fas fa-hotel",
		"fas fa-hourglass",
		"fas fa-hourglass-end",
		"fas fa-hourglass-half",
		"fas fa-hourglass-start",
		"fas fa-house-damage",
		"fas fa-house-user",
		"fas fa-hryvnia",
		"fas fa-i-cursor",
		"fas fa-ice-cream",
		"fas fa-icicles",
		"fas fa-icons",
		"fas fa-id-badge",
		"fas fa-id-card",
		"fas fa-id-card-alt",
		"fas fa-igloo",
		"fas fa-image",
		"fas fa-images",
		"fas fa-inbox",
		"fas fa-indent",
		"fas fa-industry",
		"fas fa-infinity",
		"fas fa-info",
		"fas fa-info-circle",
		"fas fa-italic",
		"fas fa-jedi",
		"fas fa-joint",
		"fas fa-journal-whills",
		"fas fa-kaaba",
		"fas fa-key",
		"fas fa-keyboard",
		"fas fa-khanda",
		"fas fa-kiss",
		"fas fa-kiss-beam",
		"fas fa-kiss-wink-heart",
		"fas fa-kiwi-bird",
		"fas fa-landmark",
		"fas fa-language",
		"fas fa-laptop",
		"fas fa-laptop-code",
		"fas fa-laptop-house",
		"fas fa-laptop-medical",
		"fas fa-laugh",
		"fas fa-laugh-beam",
		"fas fa-laugh-squint",
		"fas fa-laugh-wink",
		"fas fa-layer-group",
		"fas fa-leaf",
		"fas fa-lemon",
		"fas fa-less-than",
		"fas fa-less-than-equal",
		"fas fa-level-down-alt",
		"fas fa-level-up-alt",
		"fas fa-life-ring",
		"fas fa-lightbulb",
		"fas fa-link",
		"fas fa-lira-sign",
		"fas fa-list",
		"fas fa-list-alt",
		"fas fa-list-ol",
		"fas fa-list-ul",
		"fas fa-location-arrow",
		"fas fa-lock",
		"fas fa-lock-open",
		"fas fa-long-arrow-alt-down",
		"fas fa-long-arrow-alt-left",
		"fas fa-long-arrow-alt-right",
		"fas fa-long-arrow-alt-up",
		"fas fa-low-vision",
		"fas fa-luggage-cart",
		"fas fa-lungs",
		"fas fa-lungs-virus",
		"fas fa-magic",
		"fas fa-magnet",
		"fas fa-mail-bulk",
		"fas fa-male",
		"fas fa-map",
		"fas fa-map-marked",
		"fas fa-map-marked-alt",
		"fas fa-map-marker",
		"fas fa-map-marker-alt",
		"fas fa-map-pin",
		"fas fa-map-signs",
		"fas fa-marker",
		"fas fa-mars",
		"fas fa-mars-double",
		"fas fa-mars-stroke",
		"fas fa-mars-stroke-h",
		"fas fa-mars-stroke-v",
		"fas fa-mask",
		"fas fa-medal",
		"fas fa-medkit",
		"fas fa-meh",
		"fas fa-meh-blank",
		"fas fa-meh-rolling-eyes",
		"fas fa-memory",
		"fas fa-menorah",
		"fas fa-mercury",
		"fas fa-meteor",
		"fas fa-microchip",
		"fas fa-microphone",
		"fas fa-microphone-alt",
		"fas fa-microphone-alt-slash",
		"fas fa-microphone-slash",
		"fas fa-microscope",
		"fas fa-minus",
		"fas fa-minus-circle",
		"fas fa-minus-square",
		"fas fa-mitten",
		"fas fa-mobile",
		"fas fa-mobile-alt",
		"fas fa-money-bill",
		"fas fa-money-bill-alt",
		"fas fa-money-bill-wave",
		"fas fa-money-bill-wave-alt",
		"fas fa-money-check",
		"fas fa-money-check-alt",
		"fas fa-monument",
		"fas fa-moon",
		"fas fa-mortar-pestle",
		"fas fa-mosque",
		"fas fa-motorcycle",
		"fas fa-mountain",
		"fas fa-mouse",
		"fas fa-mouse-pointer",
		"fas fa-mug-hot",
		"fas fa-music",
		"fas fa-network-wired",
		"fas fa-neuter",
		"fas fa-newspaper",
		"fas fa-not-equal",
		"fas fa-notes-medical",
		"fas fa-object-group",
		"fas fa-object-ungroup",
		"fas fa-oil-can",
		"fas fa-om",
		"fas fa-otter",
		"fas fa-outdent",
		"fas fa-pager",
		"fas fa-paint-brush",
		"fas fa-paint-roller",
		"fas fa-palette",
		"fas fa-pallet",
		"fas fa-paper-plane",
		"fas fa-paperclip",
		"fas fa-parachute-box",
		"fas fa-paragraph",
		"fas fa-parking",
		"fas fa-passport",
		"fas fa-pastafarianism",
		"fas fa-paste",
		"fas fa-pause",
		"fas fa-pause-circle",
		"fas fa-paw",
		"fas fa-peace",
		"fas fa-pen",
		"fas fa-pen-alt",
		"fas fa-pen-fancy",
		"fas fa-pen-nib",
		"fas fa-pen-square",
		"fas fa-pencil-alt",
		"fas fa-pencil-ruler",
		"fas fa-people-arrows",
		"fas fa-people-carry",
		"fas fa-pepper-hot",
		"fas fa-percent",
		"fas fa-percentage",
		"fas fa-person-booth",
		"fas fa-phone",
		"fas fa-phone-alt",
		"fas fa-phone-slash",
		"fas fa-phone-square",
		"fas fa-phone-square-alt",
		"fas fa-phone-volume",
		"fas fa-photo-video",
		"fas fa-piggy-bank",
		"fas fa-pills",
		"fas fa-pizza-slice",
		"fas fa-place-of-worship",
		"fas fa-plane",
		"fas fa-plane-arrival",
		"fas fa-plane-departure",
		"fas fa-plane-slash",
		"fas fa-play",
		"fas fa-play-circle",
		"fas fa-plug",
		"fas fa-plus",
		"fas fa-plus-circle",
		"fas fa-plus-square",
		"fas fa-podcast",
		"fas fa-poll",
		"fas fa-poll-h",
		"fas fa-poo",
		"fas fa-poo-storm",
		"fas fa-poop",
		"fas fa-portrait",
		"fas fa-pound-sign",
		"fas fa-power-off",
		"fas fa-pray",
		"fas fa-praying-hands",
		"fas fa-prescription",
		"fas fa-prescription-bottle",
		"fas fa-prescription-bottle-alt",
		"fas fa-print",
		"fas fa-procedures",
		"fas fa-project-diagram",
		"fas fa-pump-medical",
		"fas fa-pump-soap",
		"fas fa-puzzle-piece",
		"fas fa-qrcode",
		"fas fa-question",
		"fas fa-question-circle",
		"fas fa-quidditch",
		"fas fa-quote-left",
		"fas fa-quote-right",
		"fas fa-quran",
		"fas fa-radiation",
		"fas fa-radiation-alt",
		"fas fa-rainbow",
		"fas fa-random",
		"fas fa-receipt",
		"fas fa-record-vinyl",
		"fas fa-recycle",
		"fas fa-redo",
		"fas fa-redo-alt",
		"fas fa-registered",
		"fas fa-remove-format",
		"fas fa-reply",
		"fas fa-reply-all",
		"fas fa-republican",
		"fas fa-restroom",
		"fas fa-retweet",
		"fas fa-ribbon",
		"fas fa-ring",
		"fas fa-road",
		"fas fa-robot",
		"fas fa-rocket",
		"fas fa-route",
		"fas fa-rss",
		"fas fa-rss-square",
		"fas fa-ruble-sign",
		"fas fa-ruler",
		"fas fa-ruler-combined",
		"fas fa-ruler-horizontal",
		"fas fa-ruler-vertical",
		"fas fa-running",
		"fas fa-rupee-sign",
		"fas fa-sad-cry",
		"fas fa-sad-tear",
		"fas fa-satellite",
		"fas fa-satellite-dish",
		"fas fa-save",
		"fas fa-school",
		"fas fa-screwdriver",
		"fas fa-scroll",
		"fas fa-sd-card",
		"fas fa-search",
		"fas fa-search-dollar",
		"fas fa-search-location",
		"fas fa-search-minus",
		"fas fa-search-plus",
		"fas fa-seedling",
		"fas fa-server",
		"fas fa-shapes",
		"fas fa-share",
		"fas fa-share-alt",
		"fas fa-share-alt-square",
		"fas fa-share-square",
		"fas fa-shekel-sign",
		"fas fa-shield-alt",
		"fas fa-shield-virus",
		"fas fa-ship",
		"fas fa-shipping-fast",
		"fas fa-shoe-prints",
		"fas fa-shopping-bag",
		"fas fa-shopping-basket",
		"fas fa-shopping-cart",
		"fas fa-shower",
		"fas fa-shuttle-van",
		"fas fa-sign",
		"fas fa-sign-in-alt",
		"fas fa-sign-language",
		"fas fa-sign-out-alt",
		"fas fa-signal",
		"fas fa-signature",
		"fas fa-sim-card",
		"fas fa-sitemap",
		"fas fa-skating",
		"fas fa-skiing",
		"fas fa-skiing-nordic",
		"fas fa-skull",
		"fas fa-skull-crossbones",
		"fas fa-slash",
		"fas fa-sleigh",
		"fas fa-sliders-h",
		"fas fa-smile",
		"fas fa-smile-beam",
		"fas fa-smile-wink",
		"fas fa-smog",
		"fas fa-smoking",
		"fas fa-smoking-ban",
		"fas fa-sms",
		"fas fa-snowboarding",
		"fas fa-snowflake",
		"fas fa-snowman",
		"fas fa-snowplow",
		"fas fa-soap",
		"fas fa-socks",
		"fas fa-solar-panel",
		"fas fa-sort",
		"fas fa-sort-alpha-down",
		"fas fa-sort-alpha-down-alt",
		"fas fa-sort-alpha-up",
		"fas fa-sort-alpha-up-alt",
		"fas fa-sort-amount-down",
		"fas fa-sort-amount-down-alt",
		"fas fa-sort-amount-up",
		"fas fa-sort-amount-up-alt",
		"fas fa-sort-down",
		"fas fa-sort-numeric-down",
		"fas fa-sort-numeric-down-alt",
		"fas fa-sort-numeric-up",
		"fas fa-sort-numeric-up-alt",
		"fas fa-sort-up",
		"fas fa-spa",
		"fas fa-space-shuttle",
		"fas fa-spell-check",
		"fas fa-spider",
		"fas fa-spinner",
		"fas fa-splotch",
		"fas fa-spray-can",
		"fas fa-square",
		"fas fa-square-full",
		"fas fa-square-root-alt",
		"fas fa-stamp",
		"fas fa-star",
		"fas fa-star-and-crescent",
		"fas fa-star-half",
		"fas fa-star-half-alt",
		"fas fa-star-of-david",
		"fas fa-star-of-life",
		"fas fa-step-backward",
		"fas fa-step-forward",
		"fas fa-stethoscope",
		"fas fa-sticky-note",
		"fas fa-stop",
		"fas fa-stop-circle",
		"fas fa-stopwatch",
		"fas fa-stopwatch-20",
		"fas fa-store",
		"fas fa-store-alt",
		"fas fa-store-alt-slash",
		"fas fa-store-slash",
		"fas fa-stream",
		"fas fa-street-view",
		"fas fa-strikethrough",
		"fas fa-stroopwafel",
		"fas fa-subscript",
		"fas fa-subway",
		"fas fa-suitcase",
		"fas fa-suitcase-rolling",
		"fas fa-sun",
		"fas fa-superscript",
		"fas fa-surprise",
		"fas fa-swatchbook",
		"fas fa-swimmer",
		"fas fa-swimming-pool",
		"fas fa-synagogue",
		"fas fa-sync",
		"fas fa-sync-alt",
		"fas fa-syringe",
		"fas fa-table",
		"fas fa-table-tennis",
		"fas fa-tablet",
		"fas fa-tablet-alt",
		"fas fa-tablets",
		"fas fa-tachometer-alt",
		"fas fa-tag",
		"fas fa-tags",
		"fas fa-tape",
		"fas fa-tasks",
		"fas fa-taxi",
		"fas fa-teeth",
		"fas fa-teeth-open",
		"fas fa-temperature-high",
		"fas fa-temperature-low",
		"fas fa-tenge",
		"fas fa-terminal",
		"fas fa-text-height",
		"fas fa-text-width",
		"fas fa-th",
		"fas fa-th-large",
		"fas fa-th-list",
		"fas fa-theater-masks",
		"fas fa-thermometer",
		"fas fa-thermometer-empty",
		"fas fa-thermometer-full",
		"fas fa-thermometer-half",
		"fas fa-thermometer-quarter",
		"fas fa-thermometer-three-quarters",
		"fas fa-thumbs-down",
		"fas fa-thumbs-up",
		"fas fa-thumbtack",
		"fas fa-ticket-alt",
		"fas fa-times",
		"fas fa-times-circle",
		"fas fa-tint",
		"fas fa-tint-slash",
		"fas fa-tired",
		"fas fa-toggle-off",
		"fas fa-toggle-on",
		"fas fa-toilet",
		"fas fa-toilet-paper",
		"fas fa-toilet-paper-slash",
		"fas fa-toolbox",
		"fas fa-tools",
		"fas fa-tooth",
		"fas fa-torah",
		"fas fa-torii-gate",
		"fas fa-tractor",
		"fas fa-trademark",
		"fas fa-traffic-light",
		"fas fa-trailer",
		"fas fa-train",
		"fas fa-tram",
		"fas fa-transgender",
		"fas fa-transgender-alt",
		"fas fa-trash",
		"fas fa-trash-alt",
		"fas fa-trash-restore",
		"fas fa-trash-restore-alt",
		"fas fa-tree",
		"fas fa-trophy",
		"fas fa-truck",
		"fas fa-truck-loading",
		"fas fa-truck-monster",
		"fas fa-truck-moving",
		"fas fa-truck-pickup",
		"fas fa-tshirt",
		"fas fa-tty",
		"fas fa-tv",
		"fas fa-umbrella",
		"fas fa-umbrella-beach",
		"fas fa-underline",
		"fas fa-undo",
		"fas fa-undo-alt",
		"fas fa-universal-access",
		"fas fa-university",
		"fas fa-unlink",
		"fas fa-unlock",
		"fas fa-unlock-alt",
		"fas fa-upload",
		"fas fa-user",
		"fas fa-user-alt",
		"fas fa-user-alt-slash",
		"fas fa-user-astronaut",
		"fas fa-user-check",
		"fas fa-user-circle",
		"fas fa-user-clock",
		"fas fa-user-cog",
		"fas fa-user-edit",
		"fas fa-user-friends",
		"fas fa-user-graduate",
		"fas fa-user-injured",
		"fas fa-user-lock",
		"fas fa-user-md",
		"fas fa-user-minus",
		"fas fa-user-ninja",
		"fas fa-user-nurse",
		"fas fa-user-plus",
		"fas fa-user-secret",
		"fas fa-user-shield",
		"fas fa-user-slash",
		"fas fa-user-tag",
		"fas fa-user-tie",
		"fas fa-user-times",
		"fas fa-users",
		"fas fa-users-cog",
		"fas fa-utensil-spoon",
		"fas fa-utensils",
		"fas fa-vector-square",
		"fas fa-venus",
		"fas fa-venus-double",
		"fas fa-venus-mars",
		"fas fa-vial",
		"fas fa-vials",
		"fas fa-video",
		"fas fa-video-slash",
		"fas fa-vihara",
		"fas fa-virus",
		"fas fa-virus-slash",
		"fas fa-viruses",
		"fas fa-voicemail",
		"fas fa-volleyball-ball",
		"fas fa-volume-down",
		"fas fa-volume-mute",
		"fas fa-volume-off",
		"fas fa-volume-up",
		"fas fa-vote-yea",
		"fas fa-vr-cardboard",
		"fas fa-walking",
		"fas fa-wallet",
		"fas fa-warehouse",
		"fas fa-water",
		"fas fa-wave-square",
		"fas fa-weight",
		"fas fa-weight-hanging",
		"fas fa-wheelchair",
		"fas fa-wifi",
		"fas fa-wind",
		"fas fa-window-close",
		"fas fa-window-maximize",
		"fas fa-window-minimize",
		"fas fa-window-restore",
		"fas fa-wine-bottle",
		"fas fa-wine-glass",
		"fas fa-wine-glass-alt",
		"fas fa-won-sign",
		"fas fa-wrench",
		"fas fa-x-ray",
		"fas fa-yen-sign",
		"fas fa-yin-yang"
	];
})();



