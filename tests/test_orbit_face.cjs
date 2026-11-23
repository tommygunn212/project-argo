const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');const vm=require('node:vm');
const {Face}=require('../frontend-v2/assets/orbit-face.js');
function fixture(){let calls=0;const ctx=new Proxy({createRadialGradient(){return {addColorStop(){}}}}, {get(o,k){return k in o?o[k]:(...args)=>{calls++;for(const a of args)if(typeof a==='number')assert.ok(Number.isFinite(a),k);}},set(o,k,v){o[k]=v;return true;}});const canvas={clientWidth:390,clientHeight:500,getContext:()=>ctx};return {face:new Face(canvas),canvas,calls:()=>calls};}
test('renders and resizes finite geometry, including small screens',()=>{const f=fixture();for(const state of ['IDLE','LISTENING','THINKING','SPEAKING','SLEEPING','ERROR'])f.face.draw(1000,.8,state);assert.ok(f.calls()>1000);assert.equal(f.canvas.width,390);f.canvas.clientWidth=200;f.face.draw(1100,NaN);assert.equal(f.canvas.width,200);});
test('sleep suppresses even loud input and wake restores face',()=>{const {face}=fixture();for(let t=100;t<=3000;t+=100)face.draw(t,1,'SLEEPING');assert.ok(face.awake<.001);assert.equal(face.energy,0);for(let t=3100;t<=6000;t+=100)face.draw(t,1,'SPEAKING');assert.ok(face.awake>.99);assert.ok(face.energy>.99);});
test('missing canvas context fails rather than claiming success',()=>assert.throws(()=>new Face({getContext:()=>null}),/Canvas 2D/));
test('dashboard and demo inline scripts parse from disk',()=>{for(const name of ['index.html','orbit-demo.html']){const source=fs.readFileSync(require('node:path').join(__dirname,'../frontend-v2',name),'utf8');for(const match of source.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/g))new vm.Script(match[1]);}});
