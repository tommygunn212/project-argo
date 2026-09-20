/* Local audio-driven expressions with optional silent video as source art. */
(function (root) {
  'use strict';
  const clamp = (n, a = 0, b = 1) => Math.min(b, Math.max(a, Number(n) || 0));
  const mix = (a, b, t) => a + (b - a) * clamp(t);
  const maleVoices = new Set([
    'openai:ash', 'openai:ballad', 'openai:cedar', 'openai:echo', 'openai:fable', 'openai:onyx', 'openai:verse',
    'edge:ryan', 'edge:abeo', 'edge:guy', 'edge:davis', 'azure:az-guy', 'azure:az-davis', 'azure:az-ryan',
    'piper:piper-danny',
  ]);
  const femaleVoices = new Set([
    'openai:nova', 'openai:marin', 'openai:coral', 'openai:sage', 'openai:shimmer',
    'edge:libby', 'edge:natasha', 'edge:jenny', 'edge:aria', 'azure:az-jenny', 'azure:az-aria', 'azure:az-sonia',
    'piper:piper-amy', 'piper:piper-lessac',
  ]);
  function avatarForVoice(voice, previous = 'cortana') {
    if (maleVoices.has(voice)) return 'cyber_male';
    if (femaleVoices.has(voice)) return 'cortana';
    return previous === 'cyber_male' ? 'cyber_male' : 'cortana';
  }
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
    uniform vec3 mouthLandmark;
    uniform vec4 eyeLandmarks;
    uniform float frameZoom;
    uniform float mouth, jaw, blink, time, motion, breath;
    uniform float shapeWide, shapeRound;
    void main() {
      float scale = max(screenSize.x/imageSize.x, screenSize.y/imageSize.y);
      vec2 uv = (screenUV*screenSize + (imageSize*scale-screenSize)*0.5)/(imageSize*scale);
      vec2 pivot = vec2(0.51,0.59);
      float alive = motion*(0.62+0.38*mouth);
      float angle = alive*(sin(time*0.47)*0.0045 + sin(time*0.19+1.4)*0.0035 + mouth*sin(time*2.2)*0.0025);
      mat2 rotate = mat2(cos(angle),-sin(angle),sin(angle),cos(angle));
      uv = rotate*(uv-pivot)/(frameZoom + breath*0.004 + mouth*0.002)+pivot;
      uv.y += alive*(sin(time*0.72)*0.0022 + breath*0.0025);
      uv.x += alive*sin(time*0.31+0.7)*0.0018;
      float mx = (uv.x-mouthLandmark.x)/mouthLandmark.z;
      float seam = mouthLandmark.y - 0.0065*mx*mx - 0.0022*mx + sin(time*7.1+mx*2.4)*mouth*0.0014;
      float widthSpan = 1.12 + shapeWide*0.28 - shapeRound*0.20;
      float width = 1.0-smoothstep(0.06,max(0.3,widthSpan),abs(mx));
      float speech = pow(mouth,0.72) * (1.0 + shapeRound*0.5 - shapeWide*0.18);
      float asymmetric = 1.0 + 0.10*sin(time*9.0) + 0.06*sin(time*13.0+mx);
      float dy = uv.y-seam;
      float mouthRegion = exp(-pow(abs(dy)/0.115,2.0))*width;
      // Stretch the source lips and mouth interior, retaining their own texture.
      uv.y = seam + dy/(1.0+speech*0.90*mouthRegion*asymmetric);
      uv.y -= jaw*0.004*mouthRegion;
      uv.x += mx*speech*0.005*mouthRegion;
      float xWarp = 1.0 - shapeWide*0.22 + shapeRound*0.26;
      uv.x = mouthLandmark.x + mx*mouthLandmark.z*mix(1.0, xWarp, mouthRegion);

      // Compress and nudge the original eye texture; retain the portrait's own shading.
      for (int i=0;i<2;i++) {
        vec2 eye = i==0 ? eyeLandmarks.xy : eyeLandmarks.zw;
        vec2 d = uv-eye;
        float eyeOval = exp(-pow(abs(d.x)/0.047,4.0)*1.5) * exp(-pow(abs(d.y)/0.039,4.0)*1.7);
        uv -= gaze*eyeOval;
        d = uv-eye;
        float weight = 1.0-smoothstep(0.028,0.065,abs(d.x));
        float halfEye = 0.020;
        float extent = 0.058;
        float lid = halfEye*(1.0-blink*weight*0.94);
        float ay = abs(d.y);
        // A monotonic remap closes the eye without folding/repeating its texture.
        if (ay < extent) {
          float sourceY = ay < lid ? ay*halfEye/lid
            : halfEye+(ay-lid)*(extent-halfEye)/(extent-lid);
          uv.y = eye.y+sign(d.y)*sourceY;
        }
      }
      vec4 color = texture2D(portrait,uv);
      float faceLight = 1.0-smoothstep(0.16,0.84,length((screenUV-vec2(0.51,0.43))*vec2(1.0,1.25)));
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
      this.profile = 'portrait';
      this.texture = null;
      canvas.addEventListener('webglcontextlost', event => {
        event.preventDefault(); this.lost = true; this.ready = false;
        canvas.closest('.avatar-stage')?.classList.remove('local-animated');
      });
      canvas.addEventListener('webglcontextrestored', () => {
        this.texture = null;
        this.program = null;
        this.init();
      });
      this.setImageSource(imageUrl);
    }
    setImageSource(imageUrl) {
      if (!imageUrl || this.imageUrl === imageUrl) return;
      this.imageUrl = imageUrl;
      this.profile = 'portrait';
      this.ready = false;
      this.canvas.closest('.avatar-stage')?.classList.remove('local-animated');
      const image = new Image();
      this.image = image;
      image.onload = () => {
        if (this.image === image) this.init();
      };
      image.src = imageUrl;
    }
    setMediaSource(media, profile) {
      if (this.image === media) return;
      this.imageUrl = '';
      this.image = media;
      this.profile = profile;
      this.ready = false;
      this.init();
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
        if (this.program) gl.deleteProgram(this.program);
        if (this.buffer) gl.deleteBuffer(this.buffer);
        const program = gl.createProgram();
        gl.attachShader(program,compile(gl.VERTEX_SHADER,vertex));
        gl.attachShader(program,compile(gl.FRAGMENT_SHADER,fragment));
        gl.linkProgram(program);
        if (!gl.getProgramParameter(program,gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(program));
        gl.useProgram(program);
        const buffer = gl.createBuffer();
        this.buffer = buffer;
        gl.bindBuffer(gl.ARRAY_BUFFER,buffer);
        gl.bufferData(gl.ARRAY_BUFFER,new Float32Array([-1,-1,1,-1,-1,1,1,1]),gl.STATIC_DRAW);
        const position = gl.getAttribLocation(program,'position');
        gl.enableVertexAttribArray(position); gl.vertexAttribPointer(position,2,gl.FLOAT,false,0,0);
        const texture = this.texture || gl.createTexture();
        this.texture = texture;
        gl.bindTexture(gl.TEXTURE_2D,texture);
        gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_S,gl.CLAMP_TO_EDGE);
        gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_T,gl.CLAMP_TO_EDGE);
        gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MIN_FILTER,gl.LINEAR);
        gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MAG_FILTER,gl.LINEAR);
        gl.texImage2D(gl.TEXTURE_2D,0,gl.RGBA,gl.RGBA,gl.UNSIGNED_BYTE,this.image);
        this.gl=gl; this.program=program;
        this.uniforms = Object.fromEntries(['imageSize','screenSize','gaze','mouthLandmark','eyeLandmarks','frameZoom','mouth','jaw','blink','time','motion','breath','shapeWide','shapeRound']
          .map(name=>[name,gl.getUniformLocation(program,name)]));
        this.ready=true; this.lost=false;
        const stage = this.canvas.closest('.avatar-stage');
        if (!stage?.querySelector('.avatar-local-media') || this.image === stage.querySelector('.avatar-local-media')) {
          stage?.classList.add('local-animated');
        }
      } catch(error) {
        console.warn('Local portrait renderer unavailable',error);
      }
    }
    draw(now, mouth, reducedMotion = false, shape) {
      if (!this.ready || this.lost || !this.canvas.clientWidth || !this.canvas.clientHeight) return;
      const gl=this.gl, u=this.uniforms;
      const dpr=Math.min(window.devicePixelRatio||1,1.5);
      const w=Math.round(this.canvas.clientWidth*dpr),h=Math.round(this.canvas.clientHeight*dpr);
      if(this.canvas.width!==w || this.canvas.height!==h){this.canvas.width=w;this.canvas.height=h;}
      gl.viewport(0,0,w,h); gl.useProgram(this.program);
      if (this.image.tagName === 'VIDEO' && this.image.readyState >= 2 && this.texture) {
        gl.bindTexture(gl.TEXTURE_2D,this.texture);
        gl.texImage2D(gl.TEXTURE_2D,0,gl.RGBA,gl.RGBA,gl.UNSIGNED_BYTE,this.image);
      }
      const t=now/1000, phase=t%4.7;
      const m = clamp(mouth);
      const blinkA = Math.max(0,1-Math.abs(phase-4.3)/0.095);
      const blinkB = Math.max(0,1-Math.abs(phase-4.47)/0.075) * (Math.sin(Math.floor(t/4.7)*2.7) > 0.25 ? 1 : 0);
      const blink = reducedMotion ? 0 : clamp(Math.max(blinkA,blinkB));
      const jaw = reducedMotion ? m * 0.35 : clamp(mix(m*0.32,m,Math.sin(t*10.5)*0.5+0.5));
      const gazeX = reducedMotion ? 0 : Math.sin(t*0.29)*0.004 + Math.sin(t*0.11+1.7)*0.003;
      const gazeY = reducedMotion ? 0 : Math.sin(t*0.23+0.8)*0.0025 - m*0.0015;
      const breath = reducedMotion ? 0 : (0.5 + 0.5*Math.sin(t*0.82));
      gl.uniform2f(u.imageSize,this.image.videoWidth || this.image.naturalWidth,this.image.videoHeight || this.image.naturalHeight);
      const halo = this.profile === 'halo';
      const male = this.profile === 'cyber_male';
      gl.uniform1f(u.frameZoom,halo?1.10:1.014);
      gl.uniform3f(u.mouthLandmark,halo?0.488:male?0.491:0.512,halo?0.609:male?0.613:0.543,halo?0.076:male?0.082:0.052);
      gl.uniform4f(u.eyeLandmarks,halo?0.377:male?0.397:0.447,halo?0.270:male?0.400:0.344,halo?0.596:male?0.589:0.577,halo?0.267:male?0.398:0.344);
      gl.uniform2f(u.screenSize,w,h);
      gl.uniform2f(u.gaze,gazeX,gazeY);
      const shapeWide=(shape&&shape.wide)||0, shapeRound=(shape&&shape.round)||0;
      gl.uniform1f(u.mouth,m);gl.uniform1f(u.jaw,jaw);gl.uniform1f(u.blink,blink);
      gl.uniform1f(u.shapeWide,shapeWide);gl.uniform1f(u.shapeRound,shapeRound);
      gl.uniform1f(u.time,t);gl.uniform1f(u.motion,reducedMotion?0:1);gl.uniform1f(u.breath,breath);
      gl.drawArrays(gl.TRIANGLE_STRIP,0,4);
    }
  }
  root.CortanaAvatar={Envelope,Portrait,avatarForVoice};
  if(typeof module!=='undefined') module.exports={Envelope,avatarForVoice};
})(typeof window!=='undefined'?window:globalThis);
