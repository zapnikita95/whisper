            if (window['ct'] && typeof window['ct'] === 'function') {
            window['ct']('create_session', {
                sessionId: 940015844,
                siteId: 49951,
                modId: 'ze6wa34l',
                setCookie: true,
                endSessionTime: 1774268938,
                domain: 'freshauto.ru',
                setCtCookie: '2100000000547157212',
                setLkCookie: null,
                denialTime: 15,
                phones: {"231187":{"subPoolName":"","phoneId":"716968","phoneNumber":"","phoneCode":"","phoneBody":""}},
                emails: [],
                ecommerceGa4Enabled: false,
                ecommerceTimeout: 1000,
                calltouchDnsHost: '',
                dataGoEnabled: false,
                GA4: ["G-WE1D49ZJ17"],
                quietMediaEnabled: false,
                fields: '',
                isGtagEcom: false,
                cookieHash: '',
                firstPartyUrl: ''
            });
                        window['ct']('session_data', {"mod_id":"ze6wa34l","source":"(direct)","medium":"(none)","utm_source":"","utm_medium":"","utm_campaign":"","utm_content":"","utm_term":"","keyword":"(not set)","city":"moscow","region":"moskva","country":"","url":"https:\/\/freshauto.ru\/","deviceType":"desktop"});
                        } else {
            var xmlHttp = new XMLHttpRequest();
            xmlHttp.open( "GET", 'https://mod.calltouch.ru/set_attrs_by_get.php?siteId=49951&sessionId=940015844&attrs={"clientError_NO_CT_CREATE_SESSION": 1}', true );
            xmlHttp.send( null );
            }
            
window.ctw = {};
window.ctw.clientFormConfig = {}
window.ctw.clientFormConfig.getClientFormsSettingsUrl = "//mod.calltouch.ru/callback_widget_user_form_find.php";
window.ctw.clientFormConfig.sendClientFormsRequestUrl = "//mod.calltouch.ru/callback_request_user_form_create.php";
(function (targetWindow, nameSpace, params){
!function(){var e={6396:function(e){e.exports=function(e,t,r){return t in e?Object.defineProperty(e,t,{value:r,enumerable:!0,configurable:!0,writable:!0}):e[t]=r,e}}},t={};function r(n){var o=t[n];if(void 0!==o)return o.exports;var c=t[n]={exports:{}};return e[n](c,c.exports,r),c.exports}r.n=function(e){var t=e&&e.__esModule?function(){return e.default}:function(){return e};return r.d(t,{a:t}),t},r.d=function(e,t){for(var n in t)r.o(t,n)&&!r.o(e,n)&&Object.defineProperty(e,n,{enumerable:!0,get:t[n]})},r.o=function(e,t){return Object.prototype.hasOwnProperty.call(e,t)},function(){"use strict";var e=r(6396),t=r.n(e);function n(e,t){var r=Object.keys(e);if(Object.getOwnPropertySymbols){var n=Object.getOwnPropertySymbols(e);t&&(n=n.filter(function(t){return Object.getOwnPropertyDescriptor(e,t).enumerable})),r.push.apply(r,n)}return r}function o(e){for(var r=1;r<arguments.length;r++){var o=null!=arguments[r]?arguments[r]:{};r%2?n(Object(o),!0).forEach(function(r){t()(e,r,o[r])}):Object.getOwnPropertyDescriptors?Object.defineProperties(e,Object.getOwnPropertyDescriptors(o)):n(Object(o)).forEach(function(t){Object.defineProperty(e,t,Object.getOwnPropertyDescriptor(o,t))})}return e}function c(e,t,r,n){try{var c=Boolean(window.event&&window.event.target&&"A"===window.event.target.nodeName),a=Boolean(window.event&&(window.event.target&&"submit"===window.event.target.type||"submit"===window.event.type)),i=function(){var e;if(e||"undefined"==typeof XMLHttpRequest)try{e=new ActiveXObject("Msxml2.XMLHTTP")}catch(t){try{e=new ActiveXObject("Microsoft.XMLHTTP")}catch(t){e=!1}}else e=new XMLHttpRequest;return e}(),s=t?"POST":"GET";i.open(s,e,!c&&!a&&!n),c||a||n||(i.timeout=6e4),i.setRequestHeader("Content-type","application/json"),i.onreadystatechange=function(){if(4===i.readyState&&r)if(200===i.status){var e=function(e){var t;try{t=JSON.parse(e)}catch(e){}return t}(i.response);e?e.data?r(!0,o({},e.data)):e.error?r(!1,o({},e.error)):r(!1,{type:"unknown_error",message:"Unknown JSON format",details:{}}):r(!1,{type:"unknown_error",message:"JSON parse error",details:{}})}else 0===i.status?r(!1,{type:"unknown_error",message:"Request timeout exceeded or connection reset",details:{}}):r(!1,{type:"unknown_error",message:"Unexpected HTTP code: ".concat(i.statusText),details:{}})},i.send(t)}catch(e){r&&r(!1,{type:"unknown_error",message:"Unexpected js exception",details:{}})}}function a(e,t){var r=Object.keys(e);if(Object.getOwnPropertySymbols){var n=Object.getOwnPropertySymbols(e);t&&(n=n.filter(function(t){return Object.getOwnPropertyDescriptor(e,t).enumerable})),r.push.apply(r,n)}return r}function i(e){for(var r=1;r<arguments.length;r++){var n=null!=arguments[r]?arguments[r]:{};r%2?a(Object(n),!0).forEach(function(r){t()(e,r,n[r])}):Object.getOwnPropertyDescriptors?Object.defineProperties(e,Object.getOwnPropertyDescriptors(n)):a(Object(n)).forEach(function(t){Object.defineProperty(e,t,Object.getOwnPropertyDescriptor(n,t))})}return e}!function(e,t,r){var n=e||window,o=t||"window.ctw";n[o]||(n[o]={});var a=n[o].clientFormConfig||{},s=a.getClientFormsSettingsUrl,u=a.sendClientFormsRequestUrl;n[o].getRouteKeyData=function(e,t){var n=1e6*Math.random(),o="".concat(s,"?siteId=").concat(r.siteId,"&routeKey=").concat(e,"&pageUrl=").concat(r.pageUrl,"&sessionId=").concat(r.sessionId);c("".concat(o,"&rand=").concat(Math.floor(n)),null,t)};var d=function(e,t,n,o){var a=arguments.length>4&&void 0!==arguments[4]?arguments[4]:null,s=arguments.length>5&&void 0!==arguments[5]?arguments[5]:[],d=arguments.length>6&&void 0!==arguments[6]?arguments[6]:null,p=arguments.length>7?arguments[7]:void 0,f="boolean"==typeof p&&p,l=Array.isArray(p)&&p,w=1e6*Math.random(),y={siteId:r.siteId,sessionId:r.sessionId,workMode:1,pageUrl:r.pageUrl,tags:s,phone:t,routeKey:e,fields:n,scheduleTime:a,unitId:d};l&&(y.customFields=l),c("".concat(u,"?rand=").concat(Math.floor(w)),JSON.stringify(y),function(e,r){if(e||"two_factor_error"!==r.type)return o(e,r);var n=document.querySelector("#CalltouchWidgetFrame");if(n&&n.contentWindow&&r.context){var a=r.context.widgetId;n&&n.contentWindow.openTwoFactorForm(t,a,function(e,t){var r=e.twoFactorCode,n=e.reqUuid;c("".concat(u,"?rand=2f").concat(Math.floor(w)),JSON.stringify(i(i({},y),{},{twoFactorCode:r,reqUuid:n})),function(e,r){t(e,r),e&&o(e,r)},f)})}},f)};n[o].createRequest=d,n[o+"_"+r.modId]={createRequest:d}}(targetWindow,nameSpace,params)}()}();
})(window, "ctw", {"siteId":49951,"sessionId":940015844,"pageUrl":"https:\/\/freshauto.ru\/?digiSearch=true&term=niva travel&params=|sort=DEFAULT","modId":"ze6wa34l"})
        if (window['ct']) {
            ct('modules', 'widgets', 'init', {"siteId":49951,"sessionId":940015844,"sessionData":{"id":940015844,"url":"https:\/\/freshauto.ru\/?digiSearch=true&term=niva travel&params=|sort=DEFAULT","source":"(direct)","medium":"(none)","utmCampaign":"","deviceType":"desktop","pools":[{"subPoolId":231187,"phoneId":716968}],"geoCity":"moscow","geoRegion":"moskva","geoCountry":"ru","daysSinceLastVisit":null,"geoTimezone":"Europe\/Moscow"},"widgetTypes":["callback","wheel-fortune","promo-banner"],"isMobileDevice":false});
        }
        if (typeof window['ct']) {window['ct']('modules','widgets','goalObserver','achievedGoal','wss://ws.calltouch.ru/client/subscription/81896d288018adc18902b2cb6f22a4f2');}            var call_value = '940015844';
            var call_value_ze6wa34l = call_value;
            if(window.onSessionCallValue) {
            onSessionCallValue('940015844', '');
            }
            