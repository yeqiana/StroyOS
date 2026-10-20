import assert from 'node:assert/strict';
import {sortWorks, galleryColumns, galleryPageCapacity} from '../src/api/workCatalogSorting.ts';
const v=[
  {key:'older',updated:'2026-01-01T00:00:00Z',statusRank:1,completionPercent:14},
  {key:'newer',updated:'2026-09-01T00:00:00Z',statusRank:6,completionPercent:86},
  {key:'uncertain',updated:'invalid',statusRank:null,completionPercent:null},
  {key:'draft',updated:'2026-07-01T00:00:00Z',statusRank:0,completionPercent:null},
];
const keys=(items)=>items.map(x=>x.key).join(',');
assert.equal(keys(sortWorks(v,'updated','desc')),'newer,draft,older,uncertain');
assert.equal(keys(sortWorks(v,'updated','asc')),'older,draft,newer,uncertain');
assert.equal(keys(sortWorks(v,'status','desc')),'newer,older,draft,uncertain');
assert.equal(keys(sortWorks(v,'status','asc')),'draft,older,newer,uncertain');
assert.equal(keys(sortWorks(v,'completion','desc')),'newer,older,draft,uncertain');
assert.equal(keys(sortWorks(v,'completion','asc')),'older,newer,draft,uncertain');
assert.equal(v[0].key,'older','input order must not be mutated');
assert.equal(galleryColumns(1300),4);
assert.equal(galleryColumns(1100),3);
assert.equal(galleryColumns(800),2);
assert.equal(galleryColumns(600),1);
assert.equal(galleryPageCapacity(1440,3),12);
assert.equal(galleryPageCapacity(1150,4),12);
assert.equal(galleryPageCapacity(800,3),6);
assert.equal(galleryPageCapacity(540,3),3);
assert.equal(galleryPageCapacity(1440,0),8);
assert.equal(galleryPageCapacity(1440,99),24);
console.log('PASS: 17 sorting and responsive gallery layout scenarios');
