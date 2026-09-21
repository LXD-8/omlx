// SPDX-License-Identifier: Apache-2.0
// Runtime behaviour of the Status tab: the KPI sparkline math, the memory
// watermark percentages and the "unload all" loop; and of the Models page's
// shared status tone map, memory cell and filter-slider read-out. Run with:
// node --test tests/admin_dashboard.test.cjs
const assert = require('assert/strict');
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const { test } = require('node:test');

const root = path.resolve(__dirname, '..');
// base.html loads the shared formatter before the dashboard, so the component
// can reach window.formatCount / window.formatParams.
const { formatCount, formatParams } = require(
    path.join(root, 'omlx/admin/static/js/format.js')
);
const context = {
    localStorage: { getItem: () => null },
    window: { t: key => key, formatCount, formatParams },
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

// --- Models page: one status vocabulary, one memory cell -------------------

test('one tone map answers for every model table', () => {
    assert.equal(app.statusTone('loaded'), 'green');
    assert.equal(app.statusTone('Completed'), 'green', 'case does not matter');
    assert.equal(app.statusTone('failed'), 'red');
    assert.equal(app.statusTone('error'), 'red');
    assert.equal(app.statusTone('cancelled'), 'orange');
    assert.equal(app.statusTone('partial'), 'orange');
    assert.equal(app.statusTone('downloading'), 'blue');
    assert.equal(app.statusTone('pending'), 'blue');
    assert.equal(app.statusTone('quantizing'), 'blue');
    assert.equal(app.statusTone(''), 'neutral');
    assert.equal(app.statusTone(undefined), 'neutral');
    assert.equal(app.statusTone('something-new'), 'neutral');
    assert.equal(app.statusTone('constructor'), 'neutral', 'inherited keys are not statuses');
});

test('a status label comes from the catalogue, an unknown one verbatim', () => {
    const catalogue = JSON.parse(
        fs.readFileSync(path.join(root, 'omlx/admin/i18n/en.json'), 'utf8')
    );
    const previous = context.window.t;
    context.window.t = key => (catalogue[key] !== undefined ? catalogue[key] : key);
    try {
        assert.equal(app.statusLabel('downloading'), 'Downloading');
        assert.equal(app.statusLabel('LOADED'), 'Loaded');
        assert.equal(app.statusLabel('mystery'), 'mystery');
    } finally {
        context.window.t = previous;
    }
});

test('a manager row knows whether it is resident', () => {
    app.models = [
        { id: 'resident', loaded: true },
        { id: 'starting', loaded: true, is_loading: true },
        { id: 'idle', loaded: false },
    ];
    assert.equal(app.managerModelStatus('resident'), 'loaded');
    assert.equal(app.isModelLoaded('resident'), true);
    assert.equal(app.managerModelStatus('starting'), 'loading');
    assert.equal(app.isModelLoaded('starting'), false, 'still loading is not resident');
    assert.equal(app.managerModelStatus('idle'), 'unloaded');
    assert.equal(app.managerModelStatus('gone'), 'unknown');
});

test('the memory cell leads with the measurement', () => {
    app.models = [
        { id: 'a', loaded: true, actual_size_formatted: '5.2 GB', estimated_size_formatted: '6.1 GB' },
        { id: 'b', loaded: false, estimated_size_formatted: '6.1 GB' },
        { id: 'c', is_loading: true, actual_size_formatted: '5.2 GB', estimated_size_formatted: '6.1 GB' },
        { id: 'd', loaded: false },
    ];
    const measured = app.modelMemoryCell('a');
    assert.equal(measured.footprint, '~5.2 GB', 'the measured footprint is a rough delta');
    assert.equal(measured.observed, true);
    assert.match(measured.estimate, /6\.1 GB$/, 'the estimate is the secondary line');
    const estimated = app.modelMemoryCell('b');
    assert.equal(estimated.footprint, '6.1 GB', 'nothing measured: the estimate is the value');
    assert.equal(estimated.estimate, '', 'and there is no second line to show');
    const loading = app.modelMemoryCell('c');
    assert.equal(loading.observed, false, 'a model still loading has measured nothing');
    assert.equal(loading.footprint, '6.1 GB');
    assert.equal(app.modelMemoryCell('d').footprint, '—');
    assert.equal(app.modelMemoryCell('missing').footprint, '—');
});

test('a filter slider reads its own magnitude back', () => {
    assert.equal(app.filterSliderLabel('min_params', 7), '≥ ' + formatParams(7e9));
    assert.equal(app.filterSliderLabel('min_params', 7), '≥ 7B');
    assert.equal(app.filterSliderLabel('max_params', 32), '≤ 32B');
    assert.equal(app.filterSliderLabel('min_size', 12), '≥ 12GB');
    assert.equal(app.filterSliderLabel('max_size', 512), '≤ 512GB');
    // Zero is the off position, not "at least nothing".
    for (const kind of ['min_params', 'max_params', 'min_size', 'max_size']) {
        assert.equal(app.filterSliderLabel(kind, 0), 'models.search.filter.any', kind);
    }
    assert.equal(app.filterSliderLabel('min_size', ''), 'models.search.filter.any');
});

test('an empty sampling field shows what it inherits', () => {
    const previous = context.window.t;
    context.window.t = key => key;
    try {
        assert.equal(app.samplingInherited('temperature'), '1');
        assert.equal(app.samplingInherited('top_p'), '0.95');
        assert.equal(app.samplingInherited('max_context_window'), '32768');
        // min_p and presence_penalty have no global value to show.
        assert.equal(app.samplingInherited('min_p'), 'modal.model_settings.inherit_global_value');
        assert.equal(app.samplingInherited('presence_penalty'), 'modal.model_settings.inherit_global_value');
    } finally {
        context.window.t = previous;
    }
});

// === Benchmark presets and group helpers (PR 7) ===

// The app lives in its own vm realm, so arrays it creates have a different
// prototype than the ones here: copy through the outer realm before comparing.
function selectedKeys(selection) {
    const keys = Object.keys(selection.benchmarks).filter(key => selection.benchmarks[key]);
    return keys.sort();
}

const catalogueKeys = Array.from(
    app.accBenchmarkGroups.flatMap(group => group.benchmarks.map(b => b.key))
).sort();

test('every preset expands to a complete, non-empty selection', () => {
    for (const preset of ['quick', 'standard', 'full']) {
        const selection = app.accPresetSelection(preset);
        assert.deepEqual(
            Object.keys(selection.sampleSizes).sort(), catalogueKeys,
            `${preset} must cover the whole catalogue`
        );
        assert.deepEqual(
            Object.keys(selection.benchmarks).sort(), catalogueKeys,
            `${preset} must decide every benchmark`
        );
        const selected = selectedKeys(selection);
        assert.ok(selected.length > 0, `${preset} leaves the form empty`);
        for (const key of selected) {
            assert.ok(catalogueKeys.includes(key), `${preset} names an unknown benchmark`);
            assert.ok(Number.isFinite(selection.sampleSizes[key]), `${preset}/${key} has no size`);
        }
    }
});

test('quick is a small subset, standard is the default set, full is everything', () => {
    const quick = app.accPresetSelection('quick');
    assert.deepEqual(selectedKeys(quick), ['arc_challenge', 'gsm8k', 'mmlu']);
    assert.equal(quick.sampleSizes.mmlu, 100);
    assert.equal(quick.sampleSizes.gsm8k, 100);

    const standard = app.accPresetSelection('standard');
    assert.deepEqual(selectedKeys(standard), ['humaneval', 'mmlu', 'truthfulqa']);
    assert.equal(standard.sampleSizes.mmlu, 1000);

    const full = app.accPresetSelection('full');
    assert.deepEqual(selectedKeys(full), catalogueKeys);
    assert.equal(Object.keys(full.benchmarks).length, catalogueKeys.length);
    assert.equal(Object.values(full.sampleSizes).every(size => size === 0), true,
        '0 means the benchmark\'s own full dataset');
});

test('an unknown preset falls back to the default instead of an empty form', () => {
    const selection = app.accPresetSelection('nonsense');
    assert.deepEqual(selectedKeys(selection), ['humaneval', 'mmlu', 'truthfulqa']);
});

test('applying a preset is recognisable as that preset', () => {
    const benchmarks = { ...app.accBenchmarks };
    const sampleSizes = { ...app.accSampleSizes };
    app.accBenchmarks = { mmlu: true };
    app.accSampleSizes = { mmlu: 30 };
    for (const preset of ['quick', 'standard', 'full']) {
        app.applyAccPreset(preset);
        assert.equal(app.accActivePreset, preset, `${preset} must round-trip`);
    }
    app.applyAccPreset('quick');
    app.accBenchmarks.mmlu = false;
    assert.equal(app.accActivePreset, 'custom', 'a hand-picked selection is not a preset');
    app.accBenchmarks = benchmarks;
    app.accSampleSizes = sampleSizes;
});

test('the group Full option takes the whole group at full size', () => {
    const benchmarks = { ...app.accBenchmarks };
    const sampleSizes = { ...app.accSampleSizes };
    const group = app.accBenchmarkGroups.find(g => g.key === 'math');
    app.applyGroupFull(group);
    for (const benchmark of group.benchmarks) {
        assert.equal(app.accBenchmarks[benchmark.key], true);
        assert.equal(app.accSampleSizes[benchmark.key], 0);
    }
    assert.equal(
        app.accGroupSamples(group),
        group.benchmarks.reduce((total, b) => total + b.fullSize, 0)
    );
    app.accBenchmarks = benchmarks;
    app.accSampleSizes = sampleSizes;
});

test('a selected group counts its samples and falls back to the full dataset', () => {
    const group = app.accBenchmarkGroups.find(g => g.key === 'math');
    app.accBenchmarks = { gsm8k: true, mathqa: false };
    app.accSampleSizes = { gsm8k: 100, mathqa: 0 };
    assert.deepEqual(Array.from(app.accGroupSelected(group), b => b.key), ['gsm8k']);
    assert.equal(app.accGroupSamples(group), 100);
    app.accSampleSizes = { gsm8k: 0, mathqa: 0 };
    assert.equal(app.accGroupSamples(group), group.benchmarks[0].fullSize);
});

test('the context target list is the reachable set with k labels', () => {
    app.models = [{ id: 'm', model_context_length: 40000 }];
    app.ctxBenchModelId = 'm';
    const choices = Array.from(app.ctxBenchTargetChoices(), c => [c.value, c.label]);
    assert.deepEqual(choices, [[16384, '16k'], [32768, '32k']]);
    assert.deepEqual([...app.ctxBenchTargetOptions()], [16384, 32768]);
});

test('an external benchmark run skips the destructive confirmation', async () => {
    app.accExternalEnabled = true;
    let queued = 0;
    app.addToAccQueue = async () => { queued += 1; };
    app.requestBenchConfirm('accuracy');
    assert.equal(queued, 1, 'an external endpoint never unloads local models');
    assert.equal(app.benchConfirm, null);

    app.benchExternalEnabled = true;
    let started = 0;
    app.startBenchmark = async () => { started += 1; };
    app.requestBenchConfirm('throughput');
    assert.equal(started, 1);
    assert.equal(app.benchConfirm, null);
});

test('a local benchmark run waits for the confirmation', () => {
    app.accExternalEnabled = false;
    app.benchExternalEnabled = false;
    let queued = 0;
    app.addToAccQueue = async () => { queued += 1; };
    app.requestBenchConfirm('accuracy');
    assert.equal(queued, 0, 'nothing runs before the alert is confirmed');
    assert.equal(app.benchConfirm, 'accuracy');
    app.cancelBenchConfirm();
    assert.equal(app.benchConfirm, null, 'cancel leaves nothing pending');
    assert.equal(queued, 0);
});

