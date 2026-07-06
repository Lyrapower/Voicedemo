/** 心的着色器。语义不许改,参数走 tokens.ts(issue 时按项调)。 */
export const VERT = `
attribute float seed; attribute float shell;
uniform float uT,uPx,uCoh,uFreeze,uBright; uniform vec4 uW; uniform vec3 uRip,uMouse;
varying float vGlow; varying float vShell; varying float vSpark;
mat2 rot(float a){float c=cos(a),s=sin(a);return mat2(c,-s,s,c);}
void main(){
  float t=uT*(1.0-uFreeze);
  float spawnDelay=shell*0.30;
  float spawnAge=max(0.0,t-spawnDelay);
  float spawnIn=smoothstep(0.0,0.35,spawnAge);
  vec3 b=position; float r=length(b)+1e-4;
  float phase=t*0.5+mix(seed*6.2831,0.0,uCoh);
  float breath=sin(phase);
  vec3 pIdle=b*(1.0+breath*0.05); pIdle.xz=rot(t*0.05)*pIdle.xz;
  vec3 pTh=b*(0.52+0.06*sin(t*1.7+seed)); pTh.xz=rot(t*(1.4/(shell+0.35)))*pTh.xz; pTh.y*=0.8;
  float lane=fract(b.x*0.08+t*0.22+seed*0.001);
  vec3 pWk=vec3((lane-0.5)*30.0,b.y*0.55,b.z*0.55); pWk.yz=rot(sin(seed)*0.3)*pWk.yz;
  vec3 pOut=b*(1.0+breath*0.03); float ripGlow=0.0;
  for(int k=0;k<3;k++){
    float t0=k==0?uRip.x:(k==1?uRip.y:uRip.z);
    float w=t-t0; float d=abs(r-w*9.0);
    float hit=smoothstep(1.2,0.0,d)*smoothstep(2.2,0.0,w)*step(0.0,w);
    pOut+=normalize(b)*hit*1.15; ripGlow+=hit; }
  vec3 p=pIdle*uW.x+pTh*uW.y+pWk*uW.z+pOut*uW.w;
  vec2 dm=p.xy-uMouse.xy; float md=length(dm);
  float pull=smoothstep(6.5,0.0,md);
  p.xy-=normalize(dm+1e-4)*pull*1.1;
  float sparkGate=step(0.97,fract(seed*0.618));
  float scint=sparkGate*pow(max(sin(t*(14.0+fract(seed)*9.0)+seed),0.0),6.0);
  vSpark=scint;
  vGlow=(0.45+breath*0.12*uW.x+uW.y*0.35*(1.0-shell)+ripGlow*1.6+pull*1.4+scint*2.2)*spawnIn;
  vShell=shell;
  vec4 mv=modelViewMatrix*vec4(p*spawnIn,1.0);
  gl_Position=projectionMatrix*mv;
  gl_PointSize=(0.9+(1.0-shell)*0.8+scint*2.6+pull*1.6+ripGlow*1.2)*uPx*(30.0/-mv.z);
}`;
export const FRAG = `
uniform float uCoh,uBright; varying float vGlow; varying float vShell; varying float vSpark;
void main(){
  float d=length(gl_PointCoord-0.5); float a=smoothstep(0.5,0.06,d);
  vec3 edge=mix(vec3(0.46,0.36,0.72),vec3(0.78,0.62,0.90),uCoh);
  vec3 core=mix(vec3(0.72,0.66,0.92),vec3(0.96,0.90,0.78),uCoh);
  vec3 col=mix(core,edge,smoothstep(0.1,0.9,vShell));
  col=mix(col,vec3(0.95,0.98,1.05)+vec3(0.25,-0.05,0.35)*sin(vShell*40.0),vSpark*0.8);
  col*=(1.0+uBright);
  gl_FragColor=vec4(col,a*0.5*vGlow);
}`;
