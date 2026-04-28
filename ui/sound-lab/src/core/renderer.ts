import * as THREE from 'three';
import type { ParticleDrive } from './controller';

const VS = /* glsl */ `
precision highp float;
attribute vec3 instancePos;
attribute float instanceSeed;
attribute vec2 uv;
uniform mat4 modelMatrix;
uniform mat4 modelViewMatrix;
uniform mat4 projectionMatrix;
uniform vec3 uCameraPos;
uniform float uTime;
uniform float u_coherence;
uniform float u_energy;
uniform float u_dispersion;

varying float vAlpha;
varying vec3 vColor;
varying vec2 vUv;

vec3 mod289(vec3 x){return x-floor(x*(1./289.))*289.;}
vec4 mod289(vec4 x){return x-floor(x*(1./289.))*289.;}
vec4 permute(vec4 x){return mod289(((x*34.)+1.)*x);}
vec4 taylorInvSqrt(vec4 r){return 1.79284291400159-0.85373472095314*r;}

float snoise(vec3 v){
  const vec2 C=vec2(1./6.,1./3.);
  const vec4 D=vec4(0.,.5,1.,2.);
  vec3 i=floor(v+dot(v,C.yyy));
  vec3 x0=v-i+dot(i,C.xxx);
  vec3 g=step(x0.yzx,x0.xyz);
  vec3 l=1.-g;
  vec3 i1=min(g.xyz,l.zxy);
  vec3 i2=max(g.xyz,l.zxy);
  vec3 x1=x0-i1+C.xxx;
  vec3 x2=x0-i2+C.yyy;
  vec3 x3=x0-D.yyy;
  i=mod289(i);
  vec4 p=permute(permute(permute(i.z+vec4(0.,i1.z,i2.z,1.))+i.y+vec4(0.,i1.y,i2.y,1.))+i.x+vec4(0.,i1.x,i2.x,1.));
  float n_=.142857142857;
  vec3 ns=n_*D.wyz-D.xzx;
  vec4 j=p-49.*floor(p*ns.z*ns.z);
  vec4 x_=floor(j*ns.z);
  vec4 y_=floor(j-7.*x_);
  vec4 x=x_*ns.x+ns.yyyy;
  vec4 y=y_*ns.x+ns.yyyy;
  vec4 h=1.-abs(x)-abs(y);
  vec4 b0=vec4(x.xy,y.xy);
  vec4 b1=vec4(x.zw,y.zw);
  vec4 s0=floor(b0)*2.+1.;
  vec4 s1=floor(b1)*2.+1.;
  vec4 sh=-step(h,vec4(0.));
  vec4 a0=b0.xzyw+s0.xzyw*sh.xxyy;
  vec4 a1=b1.xzyw+s1.xzyw*sh.zzww;
  vec3 p0=vec3(a0.xy,h.x);
  vec3 p1=vec3(a0.zw,h.y);
  vec3 p2=vec3(a1.xy,h.z);
  vec3 p3=vec3(a1.zw,h.w);
  vec4 norm=taylorInvSqrt(vec4(dot(p0,p0),dot(p1,p1),dot(p2,p2),dot(p3,p3)));
  p0*=norm.x;p1*=norm.y;p2*=norm.z;p3*=norm.w;
  vec4 m=max(.6-vec4(dot(x0,x0),dot(x1,x1),dot(x2,x2),dot(x3,x3)),0.);
  m=m*m;
  return 42.*dot(m*m,vec4(dot(p0,x0),dot(p1,x1),dot(p2,x2),dot(p3,x3)));
}

vec3 curl(vec3 p){
  float e=.2;
  float dx=(snoise(p+vec3(e,0.,0.))-snoise(p-vec3(e,0.,0.)))/(2.*e);
  float dy=(snoise(p+vec3(0.,e,0.))-snoise(p-vec3(0.,e,0.)))/(2.*e);
  float dz=(snoise(p+vec3(0.,0.,e))-snoise(p-vec3(0.,0.,e)))/(2.*e);
  float dx2=(snoise(p+vec3(0.,e,0.))-snoise(p-vec3(0.,e,0.)))/(2.*e);
  float dy2=(snoise(p+vec3(0.,0.,e))-snoise(p-vec3(0.,0.,e)))/(2.*e);
  float dz2=(snoise(p+vec3(e,0.,0.))-snoise(p-vec3(e,0.,0.)))/(2.*e);
  return vec3(dy-dz2,dz-dx2,dx-dy2);
}

void main(){
  vec3 base=instancePos*u_dispersion;
  float t=uTime*.11;
  vec3 p=base*1.1+vec3(t*.3,t*.21,t*.17);
  vec3 f=curl(p)*(5.+u_energy*12.)*mix(.4,1.,u_coherence);
  vec3 w=base+f*u_dispersion;
  vec3 wp=(modelMatrix*vec4(w,1.)).xyz;
  vec3 toC=normalize(uCameraPos-wp);
  vec3 up=abs(toC.y)>.95?vec3(1.,0.,0.):vec3(0.,1.,0.);
  vec3 rt=normalize(cross(up,toC));
  vec3 up2=cross(toC,rt);
  float sc=(.25+.45*instanceSeed)*(.35+u_energy);
  vec3 corner=rt*position.x*sc+up2*position.y*sc;
  vUv=uv;
  vec4 mv=modelViewMatrix*vec4(w+corner,1.);
  gl_Position=projectionMatrix*mv;
  float depth=smoothstep(110.,8.,-mv.z);
  vAlpha=mix(.12,.9,depth)*(.55+.45*u_coherence);
  float hue=fract(instanceSeed*.17+uTime*.015);
  vec3 c1=vec3(.55,.62,.78);
  vec3 c2=vec3(.45,.72,.76);
  vColor=mix(vec3(.32),mix(c1,c2,hue),.5+.4*depth);
}
`;

const FS = /* glsl */ `
precision highp float;
varying float vAlpha;
varying vec3 vColor;
varying vec2 vUv;
void main(){
  vec2 q=vUv*2.-1.;
  float r=length(q);
  float a=smoothstep(1.,.2,r)*vAlpha;
  vec3 col=vColor*(.65+.35*smoothstep(.8,0.,r));
  if(a<.02)discard;
  gl_FragColor=vec4(col,a);
}
`;

export type ParticleParams = {
  particleCount: number;
  dispersion: number;
};

const MAX_INSTANCES = 200_000;

function fillPositions(n: number): { pos: Float32Array; seed: Float32Array } {
  const pos = new Float32Array(n * 3);
  const seed = new Float32Array(n);
  for (let i = 0; i < n; i++) {
    const u = Math.random();
    const v = Math.random();
    const th = 2 * Math.PI * u;
    const ph = Math.acos(2 * v - 1);
    const r = 16 + Math.random() * 40;
    pos[i * 3] = r * Math.sin(ph) * Math.cos(th);
    pos[i * 3 + 1] = r * Math.sin(ph) * Math.sin(th);
    pos[i * 3 + 2] = r * Math.cos(ph);
    seed[i] = Math.random();
  }
  return { pos, seed };
}

export class ParticleRenderer {
  readonly renderer: THREE.WebGLRenderer;
  readonly scene: THREE.Scene;
  readonly camera: THREE.PerspectiveCamera;
  private mesh: THREE.InstancedMesh;
  private material: THREE.ShaderMaterial;
  private maxCount: number;

  constructor(canvas: HTMLCanvasElement, initial: ParticleParams) {
    this.renderer = new THREE.WebGLRenderer({
      canvas,
      antialias: false,
      powerPreference: 'high-performance',
      alpha: false,
    });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
    this.renderer.toneMappingExposure = 1.02;

    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color(0x0a0a0f);

    this.camera = new THREE.PerspectiveCamera(50, 1, 0.4, 320);
    this.camera.position.set(0, 0, 76);

    this.maxCount = MAX_INSTANCES;
    const geo = new THREE.PlaneGeometry(1, 1);
    const { pos, seed } = fillPositions(this.maxCount);
    geo.setAttribute('instancePos', new THREE.InstancedBufferAttribute(pos, 3));
    geo.setAttribute('instanceSeed', new THREE.InstancedBufferAttribute(seed, 1));

    this.material = new THREE.ShaderMaterial({
      uniforms: {
        uCameraPos: { value: new THREE.Vector3() },
        uTime: { value: 0 },
        u_coherence: { value: 1 },
        u_energy: { value: 0 },
        u_dispersion: { value: initial.dispersion },
      },
      vertexShader: VS,
      fragmentShader: FS,
      transparent: true,
      depthWrite: false,
      side: THREE.DoubleSide,
      blending: THREE.AdditiveBlending,
    });

    this.mesh = new THREE.InstancedMesh(geo, this.material, this.maxCount);
    this.mesh.count = clampCount(initial.particleCount);
    this.mesh.frustumCulled = false;
    const id = new THREE.Matrix4().identity();
    for (let i = 0; i < this.maxCount; i++) this.mesh.setMatrixAt(i, id);
    this.mesh.instanceMatrix.needsUpdate = true;
    this.scene.add(this.mesh);
  }

  setSize(w: number, h: number): void {
    this.renderer.setSize(w, h, false);
    this.camera.aspect = w / Math.max(1, h);
    this.camera.updateProjectionMatrix();
  }

  setParticleCount(n: number): void {
    this.mesh.count = clampCount(n);
  }

  setDispersion(d: number): void {
    this.material.uniforms.u_dispersion.value = d;
  }

  update(drive: ParticleDrive, timeSec: number): void {
    this.camera.getWorldPosition(this.material.uniforms.uCameraPos.value);
    this.material.uniforms.uTime.value = timeSec;
    this.material.uniforms.u_coherence.value = drive.coherence;
    this.material.uniforms.u_energy.value = drive.energy;
  }

  render(): void {
    this.renderer.render(this.scene, this.camera);
  }

  dispose(): void {
    this.mesh.geometry.dispose();
    this.material.dispose();
    this.renderer.dispose();
  }

  getInstanceCount(): number {
    return this.mesh.count;
  }
}

function clampCount(n: number): number {
  return Math.min(MAX_INSTANCES, Math.max(4000, Math.floor(n)));
}
