// SPDX-License-Identifier: Apache-2.0
/*
 * The Settings tab's in-page navigation: which sections a sub-tab has, which
 * of them a search matches, what the deep link for a section is, and which one
 * the reader is currently looking at.
 *
 * The section list itself is data (the template renders it as JSON and reads
 * it back, so the titles come from the i18n catalogue). This file holds the
 * four pure rules behind the rail so they can be tested without a browser —
 * tests/admin_settings_nav.test.cjs — and so dashboard.js stays a view model.
 */

(function (global) {
    'use strict';

    // A sticky top bar plus a margin: a section counts as "current" once its
    // top edge is within this many pixels of the viewport top.
    const ACTIVE_OFFSET = 120;

    /*
     * Sections whose title, description or keyword list contains the query.
     * A query made only of whitespace matches everything, and case is ignored
     * for the Latin listings while CJK keywords match literally.
     */
    function filterSections(sections, query) {
        const needle = String(query == null ? '' : query).trim().toLowerCase();
        if (!needle) return sections.slice();
        return sections.filter((section) => {
            const haystack = [
                section.id,
                section.title,
                section.description,
                (section.keywords || []).join(' '),
            ];
            return haystack.some(
                (value) => value != null && String(value).toLowerCase().includes(needle)
            );
        });
    }

    /* The shareable link to a section: origin + path + its anchor. */
    function sectionAnchor(origin, pathname, sectionId) {
        return origin + pathname + '#' + sectionId;
    }

    /*
     * The section a scroll position is inside, from the measured top offsets
     * (document coordinates, in the same order as `sections`). Before the first
     * section starts, the first one stays current so the rail is never empty;
     * past the last one, the last stays current.
     */
    function activeSection(offsets, scrollTop, sections) {
        if (!sections.length) return null;
        const threshold = scrollTop + ACTIVE_OFFSET;
        let current = sections[0].id;
        for (let index = 0; index < sections.length; index += 1) {
            if (offsets[index] <= threshold) current = sections[index].id;
            else break;
        }
        return current;
    }

    /* The anchors a section list can be deep-linked to, in rail order. */
    function sectionAnchors(sections) {
        return sections.map((section) => section.id);
    }

    global.OMLXSettingsNav = {
        ACTIVE_OFFSET,
        filterSections,
        sectionAnchor,
        activeSection,
        sectionAnchors,
    };
})(typeof window === 'undefined' ? globalThis : window);
