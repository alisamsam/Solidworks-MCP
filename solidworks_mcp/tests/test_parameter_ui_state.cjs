const {test} = require('node:test');
const assert = require('node:assert/strict');
const {ParameterEditBuffer} = require('../workspace/parameter_ui_state.js');
const parameter = {id:'height', value_type:'number', role:'input', has_draft:false, draft_value:null, observed_value:100};

test('unsaved values survive fresh snapshots, filtering and other field saves', () => {
  const state = new ParameterEditBuffer();
  state.stage('project', parameter, '125');
  const other = {...parameter, id:'width'};
  const saved = state.stage('project', other, '900');
  state.clearIf('project', other.id, saved);
  assert.equal(state.value('project', {...parameter}), '125');
  assert.equal(state.conflicts('project', {...parameter}), false);
});
test('same names across projects keep separate local inputs', () => {
  const state = new ParameterEditBuffer();
  state.stage('a', parameter, '125');
  state.stage('b', parameter, '150');
  assert.equal(state.value('a', parameter), '125');
  assert.equal(state.value('b', parameter), '150');
});
test('remote updates are visible as conflict without discarding user input', () => {
  const state = new ParameterEditBuffer();
  state.stage('project', parameter, '125');
  const changed = {...parameter, observed_value:110};
  assert.equal(state.conflicts('project', changed), true);
  assert.equal(state.value('project', changed), '125');
  state.discard('project', parameter.id);
  assert.equal(state.value('project', changed), '110');
});
test('acknowledging earlier save cannot remove newer typing', () => {
  const state = new ParameterEditBuffer();
  const old = state.stage('project', parameter, '125');
  state.stage('project', parameter, '130');
  state.clearIf('project', parameter.id, old);
  assert.equal(state.value('project', parameter), '130');
});
test('explicit empty draft does not show an old observation', () => {
  const state = new ParameterEditBuffer();
  assert.equal(state.value('project', {...parameter, has_draft:true}), '');
});
