/* Orbit: procedural, local Canvas 2D face. No media or microphone ownership. */
(function(root) {
  'use strict';
  class Face {
    constructor(canvas) {
      this.canvas=canvas; this.ctx=canvas.getContext('2d');
      if(!this.ctx) throw new Error('Orbit requires Canvas 2D');
      this.energy=0; this.awake=1; this.last=0;
      let seed=71; const rand=()=>((seed=(Math.imul(seed,1664525)+1013904223)>>>0)/4294967296);
      this.stars=Array.from({length:420},()=>({x:rand(),y:rand(),r:.3+rand()*1.2,p:rand()*6.28}));
    }
    draw(now,level=0,state='IDLE',reduced=false) {
      const c=this.canvas,g=this.ctx,w=c.clientWidth,h=c.clientHeight;
      if(!w||!h) return;
      const dpr=Math.min(root.devicePixelRatio||1,1.5);
      if(c.width!==Math.round(w*dpr)||c.height!==Math.round(h*dpr)){c.width=Math.round(w*dpr);c.height=Math.round(h*dpr);}
      const dt=Math.min(.1,Math.max(0,(now-this.last)/1000));this.last=now;
      const asleep=/SLEEP|OFFLINE|DISCONNECTED/.test(state);
      this.awake+=(Number(!asleep)-this.awake)*(1-Math.exp(-dt*4));
      const target=asleep?0:Math.max(0,Math.min(1,Number(level)||0));
      this.energy+=(target-this.energy)*(1-Math.exp(-dt*12));
      const t=reduced?0:now/1000,a=this.awake,e=this.energy,s=Math.min(w,h);
      g.setTransform(dpr,0,0,dpr,0,0);g.fillStyle='#020710';g.fillRect(0,0,w,h);
      const glow=g.createRadialGradient(w/2,h*.48,0,w/2,h*.48,s*.6);
      glow.addColorStop(0,`rgba(0,100,130,${.13+a*.16})`);glow.addColorStop(1,'rgba(0,0,0,0)');g.fillStyle=glow;g.fillRect(0,0,w,h);
      for(const p of this.stars){g.globalAlpha=(.2+.5*a)*(.65+.35*Math.sin(t*.45+p.p));g.fillStyle='#a9edff';g.beginPath();g.arc(p.x*w,p.y*h,p.r,0,Math.PI*2);g.fill();}g.globalAlpha=1;
      g.save();g.translate(w/2,h*.48);g.scale(s,s);
      g.strokeStyle=`rgba(66,223,255,${.18+.55*a})`;g.lineWidth=.001;
      for(let k=0;k<3;k++){g.save();g.rotate((k-1)*.62+t*.025*(k%2?1:-1));g.beginPath();g.ellipse(0,0,.38+k*.025,.15+k*.04,0,0,Math.PI*2);g.stroke();const q=t*.25+k*2;g.fillStyle='#b4f8ff';g.beginPath();g.arc(Math.cos(q)*(.38+k*.025),Math.sin(q)*(.15+k*.04),.004,0,7);g.fill();g.restore();}
      // Latitude circuits form the silhouette of a luminous head.
      g.shadowColor='#17dfff';g.shadowBlur=8*a;
      for(let j=0;j<29;j++){
        const y=-.29+j*.019,span=.19*Math.sqrt(Math.max(0,1-(y/.31)**2))*(y>0?1-y*.9:1);
        g.beginPath();
        for(let i=0;i<=32;i++){const x=-span+i*span/16;const z=Math.sqrt(Math.max(0,1-(x/(span||1))**2));const yy=y-z*.014+Math.sin(i*.7+j+t)*e*.002; i?g.lineTo(x,yy):g.moveTo(x,yy);}
        g.globalAlpha=(.18+.48*a)*(j%3===0?1:.5);g.stroke();
      }
      g.globalAlpha=.25+.75*a;g.strokeStyle=state==='ERROR'?'#ff9675':'#8df6ff';g.lineWidth=.003;
      const blink=asleep?0:(reduced?1:Math.min(1,Math.abs((t%5)-4.7)*12));
      for(const x of [-.075,.075]){g.beginPath();g.ellipse(x,-.055,.036,.002+.01*blink*a,0,0,7);g.stroke();}
      g.beginPath();g.moveTo(0,-.025);g.lineTo(-.014,.047);g.lineTo(.014,.047);g.stroke();
      g.beginPath();g.ellipse(0,.115,.048+e*.015,.002+e*.035,0,0,7);g.stroke();
      g.shadowBlur=0;g.globalAlpha=.45;g.beginPath();g.moveTo(-.08,.265);g.lineTo(-.085,.32);g.lineTo(-.24,.37);g.moveTo(.08,.265);g.lineTo(.085,.32);g.lineTo(.24,.37);g.stroke();g.restore();g.globalAlpha=1;
    }
  }
  root.OrbitFace={Face};
  if(typeof module!=='undefined')module.exports={Face};
})(typeof window!=='undefined'?window:globalThis);
