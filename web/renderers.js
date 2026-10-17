import {extendedSRGB, rgba} from './mapping.js';

const WGSL = `
struct Params { mapping: vec4f, view: vec4f, size: vec4f }
@group(0) @binding(0) var source: texture_2d<f32>;
@group(0) @binding(1) var<uniform> p: Params;
@vertex fn vertex(@builtin(vertex_index) i: u32) -> @builtin(position) vec4f {
  var points = array<vec2f, 3>(vec2f(-1., -1.), vec2f(3., -1.), vec2f(-1., 3.));
  return vec4f(points[i], 0., 1.);
}
fn encode(c: vec3f) -> vec3f {
  return select(12.92 * c, 1.055 * pow(max(c, vec3f(0.)), vec3f(1. / 2.4)) - 0.055, c > vec3f(0.0031308));
}
@fragment fn fragment(@builtin(position) pos: vec4f) -> @location(0) vec4f {
  let uv = (pos.xy / p.size.xy - vec2f(0.5)) / p.view.z + p.view.xy;
  if (any(uv < vec2f(0.)) || any(uv >= vec2f(1.))) { return vec4f(0., 0., 0., 1.); }
  let pixel = vec2i(uv * p.size.xy);
  var c = textureLoad(source, pixel, 0).rgb * p.mapping.x;
  // Declared preview basis is linear BT.709/sRGB, converted to Display P3 D65.
  c = vec3f(0.8224619687*c.r + 0.1775380313*c.g,
    0.0331941989*c.r + 0.9668058011*c.g,
    0.0170826307*c.r + 0.0723974407*c.g + 0.9105199286*c.b);
  c = clamp(c, vec3f(0.), vec3f(p.mapping.y));
  // Older display-p3 canvases expect transfer-encoded values, even in float16.
  if (p.mapping.w > 0.5) { c = encode(c); }
  return vec4f(c, 1.);
}`;

class GPURenderer {
  constructor(canvas, device, colorSpace) {
    this.canvas = canvas; this.device = device;
    this.context = canvas.getContext('webgpu');
    if (!this.context) throw new Error('WebGPU canvas unavailable');
    this.context.configure({device, format:'rgba16float', colorSpace,
      alphaMode:'opaque', toneMapping:{mode:'extended'}});
    const actual = this.context.getConfiguration?.();
    if (!actual || actual.format !== 'rgba16float' || actual.colorSpace !== colorSpace || actual.toneMapping?.mode !== 'extended') {
      throw new Error('Extended WebGPU canvas configuration was not retained');
    }
    this.encoded = colorSpace === 'display-p3';
    const shader = device.createShaderModule({code: WGSL});
    this.layout = device.createBindGroupLayout({entries:[
      {binding:0, visibility:GPUShaderStage.FRAGMENT, texture:{sampleType:'unfilterable-float'}},
      {binding:1, visibility:GPUShaderStage.FRAGMENT, buffer:{type:'uniform'}}]});
    this.pipeline = device.createRenderPipeline({
      layout: device.createPipelineLayout({bindGroupLayouts:[this.layout]}),
      vertex:{module:shader, entryPoint:'vertex'},
      fragment:{module:shader,entryPoint:'fragment',targets:[{format:'rgba16float'}]},
      primitive:{topology:'triangle-list'}});
    this.uniform = device.createBuffer({size:48, usage:GPUBufferUsage.UNIFORM | GPUBufferUsage.COPY_DST});
  }
  upload(rgb, width, height) {
    const {device} = this;
    if (this.canvas.width !== width || this.canvas.height !== height || !this.texture) {
      this.canvas.width = width; this.canvas.height = height;
      this.texture?.destroy();
      this.texture = device.createTexture({size:[width,height],format:'rgba32float',usage:GPUTextureUsage.TEXTURE_BINDING | GPUTextureUsage.COPY_DST});
      this.bindGroup = device.createBindGroup({layout:this.layout,entries:[
        {binding:0,resource:this.texture.createView()}, {binding:1,resource:{buffer:this.uniform}}]});
    }
    device.queue.writeTexture({texture:this.texture}, rgba(rgb), {bytesPerRow:width*16}, [width,height]);
  }
  draw({gain=1,ceiling=1,zoom=1,centerX=.5,centerY=.5}) {
    const {device} = this;
    device.queue.writeBuffer(this.uniform,0,new Float32Array([gain,ceiling,1,Number(this.encoded),centerX,centerY,zoom,0,this.canvas.width,this.canvas.height,0,0]));
    const commands = device.createCommandEncoder();
    const pass = commands.beginRenderPass({colorAttachments:[{view:this.context.getCurrentTexture().createView(),loadOp:'clear',storeOp:'store',clearValue:{r:0,g:0,b:0,a:1}}]});
    pass.setPipeline(this.pipeline); pass.setBindGroup(0,this.bindGroup); pass.draw(3); pass.end();
    device.queue.submit([commands.finish()]);
  }
  dispose() {this.texture?.destroy(); this.uniform.destroy(); this.context.unconfigure();}
}

const VERTEX = `#version 300 es
void main() { vec2 p[3]=vec2[3](vec2(-1.,-1.),vec2(3.,-1.),vec2(-1.,3.)); gl_Position=vec4(p[gl_VertexID],0.,1.); }`;
const FRAGMENT = `#version 300 es
precision highp float;
uniform sampler2D source;
uniform vec2 size;
uniform vec4 mapping;
uniform vec3 view;
out vec4 color;
vec3 encode(vec3 c) {return mix(12.92*c,1.055*pow(max(c,vec3(0.)),vec3(1./2.4))-.055,greaterThan(c,vec3(.0031308)));}
void main() {
  vec2 uv=(vec2(gl_FragCoord.x/size.x,1.-gl_FragCoord.y/size.y)-.5)/view.z+view.xy;
  if(any(lessThan(uv,vec2(0.))) || any(greaterThanEqual(uv,vec2(1.)))) {color=vec4(0.,0.,0.,1.); return;}
  vec3 c=texelFetch(source,ivec2(uv*size),0).rgb*mapping.x;
  color=vec4(encode(clamp(c,0.,min(mapping.y,1.))),1.);
}`;

class GLRenderer {
  constructor(canvas) {
    this.canvas = canvas;
    this.gl = canvas.getContext('webgl2',{alpha:false,antialias:false,depth:false,stencil:false,preserveDrawingBuffer:true});
    if (!this.gl) throw new Error('WebGL2 unavailable');
    const gl = this.gl;
    if ('drawingBufferColorSpace' in gl) gl.drawingBufferColorSpace = 'srgb';
    const shader = (kind, text) => {
      const s = gl.createShader(kind); gl.shaderSource(s,text); gl.compileShader(s);
      if (!gl.getShaderParameter(s,gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(s));
      return s;
    };
    this.program = gl.createProgram();
    gl.attachShader(this.program,shader(gl.VERTEX_SHADER,VERTEX));
    gl.attachShader(this.program,shader(gl.FRAGMENT_SHADER,FRAGMENT)); gl.linkProgram(this.program);
    if (!gl.getProgramParameter(this.program,gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(this.program));
    this.texture = gl.createTexture();
    gl.bindTexture(gl.TEXTURE_2D,this.texture);
    gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MIN_FILTER,gl.NEAREST);
    gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MAG_FILTER,gl.NEAREST);
    this.locations = Object.fromEntries(['source','size','mapping','view'].map(x=>[x,gl.getUniformLocation(this.program,x)]));
    this.vao = gl.createVertexArray();
    canvas.addEventListener('webglcontextlost',e=>{e.preventDefault(); window.dispatchEvent(new CustomEvent('tv-renderer-lost',{detail:`WebGL2 context lost: ${e.statusMessage || 'driver reset'}`}));});
  }
  upload(rgb, width, height) {
    const gl = this.gl;
    this.canvas.width = width; this.canvas.height = height;
    gl.bindTexture(gl.TEXTURE_2D,this.texture);
    gl.texImage2D(gl.TEXTURE_2D,0,gl.RGBA32F,width,height,0,gl.RGBA,gl.FLOAT,rgba(rgb));
  }
  draw({gain=1,ceiling=1,zoom=1,centerX=.5,centerY=.5}) {
    const gl = this.gl;
    gl.viewport(0,0,this.canvas.width,this.canvas.height); gl.useProgram(this.program);
    gl.bindVertexArray(this.vao); gl.activeTexture(gl.TEXTURE0); gl.bindTexture(gl.TEXTURE_2D,this.texture);
    gl.uniform1i(this.locations.source,0); gl.uniform2f(this.locations.size,this.canvas.width,this.canvas.height);
    gl.uniform4f(this.locations.mapping,gain,Math.min(ceiling,1),0,0); gl.uniform3f(this.locations.view,centerX,centerY,zoom);
    gl.drawArrays(gl.TRIANGLES,0,3);
  }
  dispose() {this.gl.getExtension('WEBGL_lose_context')?.loseContext();}
}

class SDR2DRenderer {
  constructor(canvas) {this.canvas=canvas;this.context=canvas.getContext('2d',{alpha:false,colorSpace:'srgb'});if(!this.context)throw new Error('No canvas renderer available');}
  upload(rgb,width,height) {this.rgb=rgb;this.canvas.width=width;this.canvas.height=height;}
  draw({gain=1,ceiling=1,zoom=1,centerX=.5,centerY=.5}) {
    const w=this.canvas.width,h=this.canvas.height,data=this.context.createImageData(w,h);
    for(let y=0;y<h;y++) for(let x=0;x<w;x++) {
      const u=((x+.5)/w-.5)/zoom+centerX,v=((y+.5)/h-.5)/zoom+centerY;
      const target=(y*w+x)*4;
      if(u>=0 && u<1 && v>=0 && v<1) {
        const source=(Math.floor(v*h)*w+Math.floor(u*w))*3;
        for(let c=0;c<3;c++) data.data[target+c]=Math.round(255*extendedSRGB(Math.min(1,ceiling,Math.max(0,this.rgb[source+c]*gain))));
      }
      data.data[target+3]=255;
    }
    this.context.putImageData(data,0,0);
  }
  dispose() {}
}

// A canvas cannot switch context types: replace it after an unsuccessful probe.
function replaceCanvas(canvas) {const next=canvas.cloneNode(false);canvas.replaceWith(next);return next;}
export async function createRenderers(ids, forcedBackend = null) {
  let canvases=ids.map(id=>document.getElementById(id));
  const failures=[];
  const forced=forcedBackend || new URLSearchParams(location.search).get('renderer');
  if (navigator.gpu && forced !== 'gl2' && forced !== '2d') {
    let device;
    try {
      const adapter=await navigator.gpu.requestAdapter();
      if(!adapter) throw new Error('No WebGPU adapter');
      device=await adapter.requestDevice();
      for(const colorSpace of ['display-p3-linear','display-p3']) {
        const instances=[];
        device.pushErrorScope('validation');
        let failure;
        try {for(const canvas of canvases) instances.push(new GPURenderer(canvas,device,colorSpace));}
        catch(error) {failure=error;}
        const validation=await device.popErrorScope();
        if(!failure && !validation) {
          device.lost.then(info=>window.dispatchEvent(new CustomEvent('tv-renderer-lost',{detail:`WebGPU device lost: ${info.reason} ${info.message}`})));
          return {instances,kind:'webgpu',extended:true,colorSpace,label:`WebGPU · P3 ${colorSpace.endsWith('linear')?'linear':'encoded'} · float16 · extended`,failures};
        }
        failures.push(`${colorSpace}: ${failure?.message || validation?.message}`);
        instances.forEach(r=>r.dispose()); canvases=canvases.map(replaceCanvas);
      }
      device.destroy();
    } catch(error) {failures.push(`WebGPU: ${error.message}`);device?.destroy();canvases=canvases.map(replaceCanvas);}
  }
  if(forced !== '2d') {
    const instances=[];
    try {
      for(const canvas of canvases)instances.push(new GLRenderer(canvas));
      return {instances,kind:'gl2',extended:false,colorSpace:'srgb',label:'WebGL2 · sRGB · SDR',failures};
    }catch(error){failures.push(`WebGL2: ${error.message}`);instances.forEach(r=>r.dispose());canvases=canvases.map(replaceCanvas);}
  }
  return {instances:canvases.map(canvas=>new SDR2DRenderer(canvas)),kind:'2d',extended:false,colorSpace:'srgb',label:'Canvas2D · sRGB · SDR emergency fallback',failures};
}
