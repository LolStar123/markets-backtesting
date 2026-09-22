import test from 'node:test';
import assert from 'node:assert/strict';
import * as m from './model.mjs';
test('workflow invariants and boundary cases',()=>{
const a=m.backtest(m.defaults),p=[...m.defaults.prices];for(let i=110;i<p.length;i++)p[i]*=1.5;const b=m.backtest({...m.defaults,prices:p});assert.deepEqual(a.folds[0],b.folds[0]);assert.ok(a.folds.every(f=>f.trainEnd<f.testStart));assert.ok(m.backtest({...m.defaults,costBps:0}).equity>m.backtest({...m.defaults,costBps:100}).equity);assert.throws(()=>m.backtest({...m.defaults,prices:[0,1]}));
});
