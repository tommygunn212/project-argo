/* Local audio-driven portrait. No recording, network inference, or canned speech loop. */
(function (root) {
  'use strict';
  const clamp = (n, a = 0, b = 1) => Math.min(b, Math.max(a, Number(n) || 0));
  const mix = (a, b, t) => a + (b - a) * clamp(t);
  class Envelope {
    constructor() {
      this.value = 0;
      this.fast = 0;
      this.slow = 0;
      this.syllablePhase = 0;
    }
    update(rms, dt) {
      const frameDt = clamp(dt, 0, 0.1);
      let raw = clamp((rms - 0.006) * 8.5);
      if (raw < 0.02) raw = 0;
      const fastTau = raw > this.fast ? 0.026 : 0.055;
      const slowTau = raw > this.slow ? 0.075 : 0.18;
      this.fast += (raw - this.fast) * (1 - Math.exp(-frameDt / fastTau));
      this.slow += (raw - this.slow) * (1 - Math.exp(-frameDt / slowTau));
      if (raw > 0.035) {
        this.syllablePhase += frameDt * mix(9, 17, raw);
      }
      const syllable = raw > 0.035 ? mix(0.74, 1.0, (Math.sin(this.syllablePhase) + 1) * 0.5) : 0.0;
      const target = clamp((this.fast * syllable) + (this.slow * 0.34));
      const tau = target > this.value ? 0.032 : 0.08;
      this.value += (target - this.value) * (1 - Math.exp(-frameDt / tau));
      if (raw === 0 && this.value < 0.018) this.value = 0;
      return this.value;
    }
  }
  const vertex = `attribute vec2 position; varying vec2 screenUV;
    void main(){ screenUV = vec2((position.x+1.0)*0.5, (1.0-position.y)*0.5);
      gl_Position = vec4(position,0.0,1.0); }`;
  const fragment = `precision highp float;
    varying vec2 screenUV;
    uniform sampler2D portrait;
    uniform vec2 imageSize, screenSize;
    uniform vec2 gaze;
    uniform float mouth, jaw, blink, time, motion, breath;
    void main() {
      float scale = max(screenSize.x/imageSize.x, screenSize.y/imageSize.y);
      vec2 uv = (screenUV*screenSize + (imageSize*scale-screenSize)*0.5)/(imageSize*scale);
      vec2 pivot = vec2(0.51,0.59);
      float alive = motion*(0.62+0.38*mouth);
      float angle = alive*(sin(time*0.47)*0.0045 + sin(time*0.19+1.4)*0.0035 + mouth*sin(time*2.2)*0.0025);
      mat2 rotate = mat2(cos(angle),-sin(angle),sin(angle),cos(angle));
      uv = rotate*(uv-pivot)/(1.014 + breath*0.004 + mouth*0.002)+pivot;
      uv.y += alive*(sin(time*0.72)*0.0022 + breath*0.0025);
      uv.x += alive*sin(time*0.31+0.7)*0.0018;
      vec2 original = uv;

      // Landmark coordinates belong to the bundled 1536 x 1024 Cortana portrait.
      float mx = (uv.x-0.512)/0.052;
      float seam = 0.543 - 0.0065*mx*mx - 0.0022*mx + sin(time*7.1+mx*2.4)*mouth*0.0014;
      float width = smoothstep(1.12,0.06,abs(mx));
      float speech = pow(mouth,0.72);
      float asymmetric = 1.0 + 0.10*sin(time*9.0) + 0.06*sin(time*13.0+mx);
      float opening = speech*0.017*width*asymmetric;
      float dy = uv.y-seam;
      float mouthRegion = exp(-pow(abs(dy)/0.115,2.0))*width;
      float chinRegion = exp(-pow(abs(uv.y-0.62)/0.12,2.0))*smoothstep(1.25,0.0,abs(mx));
      uv.y -= max(0.0,dy)*speech*0.22*mouthRegion;
      uv.y += jaw*0.010*chinRegion;
      uv.x += mx*speech*0.0022*mouthRegion;

      // Compress and nudge the original eye texture; retain the portrait's own shading.
      for (int i=0;i<2;i++) {
        vec2 eye = i==0 ? vec2(0.447,0.344) : vec2(0.577,0.344);
        vec2 d = uv-eye;
        float eyeOval = exp(-pow(abs(d.x)/0.047,4.0)*1.5) * exp(-pow(abs(d.y)/0.039,4.0)*1.7);
        uv -= gaze*eyeOval;
        d = uv-eye;
        float weight = exp(-pow(abs(d.x)/0.041,4.0)*1.8);
        float region = 1.0-smoothstep(0.024,0.050,abs(d.y));
        float compressed = 1.0-blink*weight*region*0.92;
        uv.y = eye.y+d.y/max(0.08,compressed);
      }
      vec4 color = texture2D(portrait,uv);
      if (mouth>0.010 && abs(mx)<1.08) {
        float upper = seam-opening*0.28;
        float lower = seam+opening*0.86;
        float edge = 0.0012;
        float inside = smoothstep(upper-edge,upper+edge,original.y)
                     * (1.0-smoothstep(lower-edge,lower+edge,original.y));
        inside *= smoothstep(0.0,0.002,opening);
        inside *= smoothstep(1.08,0.72,abs(mx));
        float depth = clamp((original.y-upper)/max(opening,0.0001),0.0,1.0);
        vec3 cavity = mix(vec3(0.030,0.044,0.090),vec3(0.11,0.12,0.22),depth);
        float teeth = (1.0-smoothstep(0.12,0.24,depth))*smoothstep(0.28,0.72,mouth);
        cavity = mix(cavity,vec3(0.56,0.64,0.78),teeth*0.38);
        color.rgb = mix(color.rgb,cavity,inside*0.92);
      }
      float faceLight = smoothstep(0.84,0.16,length((screenUV-vec2(0.51,0.43))*vec2(1.0,1.25)));
      float holo = sin(screenUV.y*96.0 + time*2.0)*0.004 + sin((screenUV.x+screenUV.y)*38.0-time*1.4)*0.003;
      color.rgb += vec3(0.025,0.055,0.09)*(breath+mouth*0.55+holo)*faceLight*motion;
      color.rgb *= 1.0 + mouth*0.035*faceLight;
      gl_FragColor = color;
    }`;

  class Portrait {
    constructor(canvas, imageUrl) {
      this.canvas = canvas;
      this.ready = false;
      this.lost = false;
      this.image = new Image();
      this.image.onload = () => this.init();
      canvas.addEventListener('webglcontextlost', event => {
        event.preventDefault(); this.lost = true; this.ready = false;
        canvas.closest('.avatar-stage')?.classList.remove('local-animated');
      });
      canvas.addEventListener('webglcontextrestored', () => this.init());
      this.image.src = imageUrl;
    }
    init() {
      const gl = this.canvas.getContext('webgl', { alpha: false, antialias: false, depth: false });
      if (!gl) return;
      try {
        const compile = (type, source) => {
          const shader = gl.createShader(type);
          gl.shaderSource(shader,source); gl.compileShader(shader);
          if (!gl.getShaderParameter(shader,gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(shader));
          return shader;
        };
        const program = gl.createProgram();
        gl.attachShader(program,compile(gl.VERTEX_SHADER,vertex));
        gl.attachShader(program,compile(gl.FRAGMENT_SHADER,fragment));
        gl.linkProgram(program);
        if (!gl.getProgramParameter(program,gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(program));
        gl.useProgram(program);
        const buffer = gl.createBuffer();
        gl.bindBuffer(gl.ARRAY_BUFFER,buffer);
        gl.bufferData(gl.ARRAY_BUFFER,new Float32Array([-1,-1,1,-1,-1,1,1,1]),gl.STATIC_DRAW);
        const position = gl.getAttribLocation(program,'position');
        gl.enableVertexAttribArray(position); gl.vertexAttribPointer(position,2,gl.FLOAT,false,0,0);
        const texture = gl.createTexture();
        gl.bindTexture(gl.TEXTURE_2D,texture);
        gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_S,gl.CLAMP_TO_EDGE);
        gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_T,gl.CLAMP_TO_EDGE);
        gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MIN_FILTER,gl.LINEAR);
        gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MAG_FILTER,gl.LINEAR);
        gl.texImage2D(gl.TEXTURE_2D,0,gl.RGBA,gl.RGBA,gl.UNSIGNED_BYTE,this.image);
        this.gl=gl; this.program=program;
        this.uniforms = Object.fromEntries(['imageSize','screenSize','gaze','mouth','jaw','blink','time','motion','breath']
          .map(name=>[name,gl.getUniformLocation(program,name)]));
        this.ready=true; this.lost=false;
        this.canvas.closest('.avatar-stage')?.classList.add('local-animated');
      } catch(error) {
        console.warn('Local portrait renderer unavailable',error);
      }
    }
    draw(now, mouth, reducedMotion = false) {
      if (!this.ready || this.lost || !this.canvas.clientWidth || !this.canvas.clientHeight) return;
      const gl=this.gl, u=this.uniforms;
      const dpr=Math.min(window.devicePixelRatio||1,1.5);
      const w=Math.round(this.canvas.clientWidth*dpr),h=Math.round(this.canvas.clientHeight*dpr);
      if(this.canvas.width!==w || this.canvas.height!==h){this.canvas.width=w;this.canvas.height=h;}
      gl.viewport(0,0,w,h); gl.useProgram(this.program);
      const t=now/1000, phase=t%4.7;
      const m = clamp(mouth);
      const blinkA = Math.max(0,1-Math.abs(phase-4.3)/0.095);
      const blinkB = Math.max(0,1-Math.abs(phase-4.47)/0.075) * (Math.sin(Math.floor(t/4.7)*2.7) > 0.25 ? 1 : 0);
      const blink = reducedMotion ? 0 : clamp(Math.max(blinkA,blinkB));
      const jaw = reducedMotion ? m * 0.35 : clamp(mix(m*0.32,m,Math.sin(t*10.5)*0.5+0.5));
      const gazeX = reducedMotion ? 0 : Math.sin(t*0.29)*0.004 + Math.sin(t*0.11+1.7)*0.003;
      const gazeY = reducedMotion ? 0 : Math.sin(t*0.23+0.8)*0.0025 - m*0.0015;
      const breath = reducedMotion ? 0 : (0.5 + 0.5*Math.sin(t*0.82));
      gl.uniform2f(u.imageSize,this.image.naturalWidth,this.image.naturalHeight);
      gl.uniform2f(u.screenSize,w,h);
      gl.uniform2f(u.gaze,gazeX,gazeY);
      gl.uniform1f(u.mouth,m);gl.uniform1f(u.jaw,jaw);gl.uniform1f(u.blink,blink);
      gl.uniform1f(u.time,t);gl.uniform1f(u.motion,reducedMotion?0:1);gl.uniform1f(u.breath,breath);
      gl.drawArrays(gl.TRIANGLE_STRIP,0,4);
    }
  }
  root.CortanaAvatar={Envelope,Portrait};
  if(typeof module!=='undefined') module.exports={Envelope};
})(typeof window!=='undefined'?window:globalThis);
