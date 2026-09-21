// SPDX-License-Identifier: Apache-2.0
// Runtime behaviour of the Status tab: the KPI sparkline math, the memory
// watermark percentages and the "unload all" loop. Run with:
// node --test tests/admin_dashboard.test.cjs
const assert = require('assert/strict');
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const { test } = require('node:test');

const root = path.resolve(__dirname, '..');
const context = {
    localStorage: { getItem: () => null },
    window: { t: key => key },
    console,
    alert: message => { throw Error(message); },
};
vm.createContext(context);
vm.runInContext(
    fs.readFileSync(path.join(root, 'omlx/admin/static/js/dashboard.js'), 'utf8'),
    context
);
const app = context.dashboard();

test('sparkline needs two samples and normalises to the card box', () => {
    assert.equal(app.sparkPath('requests'), '', 'one sample has no shape');
    app.kpiHistory.requests = [10, 20];
    assert.equal(app.sparkPath('requests'), 'M0.00,22.00 L100.00,2.00');
    assert.equal(app.sparkIsEmpty('requests'), false);
    assert.equal(app.sparkIsEmpty('prompt'), true);
});

test('a flat series draws a flat line instead of dividing by zero', () => {
    app.kpiHistory.cache = [42, 42, 42];
    assert.equal(app.sparkPath('cache'), 'M0.00,12.00 L50.00,12.00 L100.00,12.00');
});

test('history is capped and keeps the newest sample', () => {
    app.kpiHistoryLimit = 3;
    app.stats = { total_requests: 1, total_prompt_tokens: 2, total_cached_tokens: 3, cache_efficiency: 4 };
    app.statsScope = 'session';
    for (const value of [1, 2, 3, 4]) {
        app.stats.total_requests = value;
        app.recordKpiHistory();
    }
    assert.deepEqual(app.kpiHistory.requests, [2, 3, 4]);
    app.kpiHistoryLimit = 40;
});

test('the watermark measures against the hard limit', () => {
    app.stats = {
        active_models: {
            models: [{ estimated_size: 4e9 }, { estimated_size: 2e9 }],
            memory_pressure: { enabled: true, current_bytes: 5e9, soft_bytes: 8e9, hard_bytes: 10e9 },
        },
    };
    const watermark = app.memoryWatermark;
    assert.equal(watermark.hard, 10e9);
    assert.equal(watermark.actual, 5e9);
    assert.equal(watermark.estimated, 6e9);
    assert.equal(watermark.actualPercent, 50);
    assert.equal(watermark.estimatedPercent, 60);
    assert.equal(watermark.softPercent, 80);
    assert.equal(app.watermarkBarStyle(50), 'width: 50%;');
    assert.equal(app.watermarkMarkerStyle(80), 'left: 80%;');
});

test('a disabled enforcer still reports the resident footprint', () => {
    app.stats = {
        active_models: {
            models: [{ estimated_size: 2e9 }],
            model_memory_used: 3e9,
            model_memory_max: 6e9,
            memory_pressure: { enabled: false, current_bytes: 0, soft_bytes: 0, hard_bytes: 0 },
        },
    };
    const watermark = app.memoryWatermark;
    assert.equal(watermark.enabled, false);
    assert.equal(watermark.hard, 6e9, 'falls back to the pool ceiling');
    assert.equal(watermark.actual, 3e9);
    assert.equal(watermark.actualPercent, 50);
});

test('uptime reads from minutes to days', () => {
    assert.equal(app.formatUptime(0), '0m');
    assert.equal(app.formatUptime(90), '1m');
    assert.equal(app.formatUptime(7265), '2h 1m');
    assert.equal(app.formatUptime(200000), '2d 7h');
    assert.equal(app.formatUptime(null), '—');
});

test('unload all only touches loaded models and reuses the model endpoint', async () => {
    const unloaded = [];
    app.stats = { active_models: { models: [{ id: 'a' }, { id: 'b', is_loading: true }] } };
    app.unloadModel = async id => { unloaded.push(id); return true; };
    context.window.confirm = () => true;
    await app.unloadAllModels();
    assert.deepEqual(unloaded, ['a'], 'a loading model is not unloaded');
});

test('unload all asks first and stops when declined', async () => {
    const unloaded = [];
    app.stats = { active_models: { models: [{ id: 'a' }] } };
    app.unloadModel = async id => { unloaded.push(id); };
    context.window.confirm = () => false;
    await app.unloadAllModels();
    assert.deepEqual(unloaded, []);
});
