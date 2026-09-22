/*
 * Count formatting for the admin console: one implementation, so a screen can
 * never mix scales.
 *
 * Before this file the console had five formatters and three answers for the
 * same number: `formatNumber` concatenated 'M' above 10M, `formatTokenCount`
 * used 'k', `formatDownloads` used 'K', and the usage tables asked
 * `Intl.NumberFormat(undefined, …)` — which follows the *browser* language, not
 * the console language, so a Chinese browser showed "1.9万" next to "1.1M".
 *
 * Rules, per locale:
 *   zh          below 10,000    exact, grouped ("9,999")
 *               below 10^8      万 ("1.9万", "1,914.3万")
 *               below 10^12     亿 ("1.2亿")
 *               10^12 and above 万亿 ("1.2万亿")
 *   zh-TW       the same ladder with 萬 / 億 / 兆
 *   every other locale           K / M / B / T, one decimal, ".0" dropped
 *
 * Parameter counts are a unit rather than a count (nobody writes "80亿" for an
 * 8B model), so they keep the SI ladder in every language: formatParams().
 */
(function (global) {
    'use strict';

    var WAN = 10000;
    var YI = 100000000;
    var WANYI = 1000000000000;
    var DASH = '—';

    function resolveLocale(locale) {
        if (locale) return locale;
        if (global.__omlxLang) return global.__omlxLang;
        if (global.document && global.document.documentElement) {
            var lang = global.document.documentElement.getAttribute('lang');
            if (lang) return lang;
        }
        return 'en';
    }

    function isNumber(value) {
        return value !== null && value !== undefined && value !== '' && !isNaN(Number(value));
    }

    function trimZero(text) {
        return text.replace(/\.0$/, '');
    }

    /* A mantissa keeps its group separators — the Chinese ladder reads
       "1,914.3万", so the digits before the unit are grouped like any other
       count. The fraction is whatever the caller rounded to. */
    function groupMantissa(text, locale) {
        var parts = text.split('.');
        var whole = Number(parts[0]).toLocaleString(locale);
        return parts.length > 1 ? whole + '.' + parts[1] : whole;
    }

    function compact(value, locale, notation) {
        // The platform's own compact notation: it knows that zh keeps 万/亿 and
        // en keeps K/M/B/T, and it gets the rounding right.
        return new Intl.NumberFormat(locale, {
            notation: notation,
            maximumFractionDigits: 1,
        }).format(value);
    }

    function formatCount(value, locale) {
        if (!isNumber(value)) return DASH;
        var resolved = resolveLocale(locale);
        var number = Number(value);
        var negative = number < 0;
        var magnitude = Math.abs(number);
        var out;

        if (resolved === 'zh' || resolved === 'zh-TW') {
            // Spelled out rather than left to Intl: engines disagree about the
            // top of the Chinese ladder (some stop at 亿), and the console must
            // read the same in every browser it is opened in.
            var big = resolved === 'zh-TW' ? ['萬', '億', '兆'] : ['万', '亿', '万亿'];
            if (magnitude >= WANYI) {
                out = groupMantissa(trimZero((magnitude / WANYI).toFixed(1)), resolved) + big[2];
            } else if (magnitude >= YI) {
                out = groupMantissa(trimZero((magnitude / YI).toFixed(1)), resolved) + big[1];
            } else if (magnitude >= WAN) {
                out = groupMantissa(trimZero((magnitude / WAN).toFixed(1)), resolved) + big[0];
            } else {
                out = Math.round(magnitude).toLocaleString(resolved);
            }
        } else {
            out = magnitude >= 1000 ? compact(magnitude, resolved, 'compact') : String(Math.round(magnitude));
        }
        return negative ? '-' + out : out;
    }

    /* The exact figure, for titles and tooltips that must not be rounded. */
    function formatCountExact(value, locale) {
        if (!isNumber(value)) return DASH;
        return Math.round(Number(value)).toLocaleString(resolveLocale(locale));
    }

    /* Model parameter counts: SI ladder in every language. */
    function formatParams(value) {
        if (!isNumber(value)) return DASH;
        var number = Number(value);
        if (number >= 1e12) return trimZero((number / 1e12).toFixed(1)) + 'T';
        if (number >= 1e9) return trimZero((number / 1e9).toFixed(1)) + 'B';
        if (number >= 1e6) return trimZero((number / 1e6).toFixed(1)) + 'M';
        return String(number);
    }

    /* A measured performance figure (tok/s, seconds, …). Until something has
       been measured it reads as an em dash, never "0.0": a fresh stats object
       holds zeros, and "0.0 tok/s" states a measurement that was never taken.
       Every metric cell in the console goes through this one function so a new
       one cannot reintroduce the zero. */
    function formatMetric(value, digits) {
        var number = Number(value);
        if (!isFinite(number) || number <= 0) return DASH;
        return number.toFixed(digits === undefined ? 1 : digits);
    }

    global.formatCount = formatCount;
    global.formatCountExact = formatCountExact;
    global.formatParams = formatParams;
    global.formatMetric = formatMetric;

    if (typeof module !== 'undefined' && module.exports) {
        module.exports = {
            formatCount: formatCount,
            formatCountExact: formatCountExact,
            formatParams: formatParams,
            formatMetric: formatMetric,
        };
    }
})(typeof window !== 'undefined' ? window : globalThis);
