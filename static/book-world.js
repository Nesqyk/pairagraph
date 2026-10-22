// A locally served Three.js illustration. No learner data enters this scene.
// Let the page and fallback paint before loading the optional scene.
await new Promise(resolve => {
  const start = () => window.requestIdleCallback ? requestIdleCallback(resolve, {timeout:1000}) : requestAnimationFrame(resolve);
  document.readyState === 'complete' ? start() : window.addEventListener('load', start, {once:true});
});
const THREE = await import('./vendor/three.module.min.js');

const host = document.querySelector('[data-book-world]');
const toggle = document.querySelector('[data-motion-toggle]');
const reduced = matchMedia('(prefers-reduced-motion: reduce)');
let renderer;
try {
  renderer = new THREE.WebGLRenderer({ alpha: true, antialias: true, powerPreference: 'low-power' });
} catch { /* Keep the garden illustration when WebGL is unavailable. */ }
if (host && renderer) {
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(34, 1, .1, 50);
  camera.position.set(7, 7.3, 10.8);
  camera.lookAt(0, .6, 0);
  renderer.setPixelRatio(Math.min(devicePixelRatio, 1.75));
  renderer.setClearColor(0, 0);
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  // Tiny foliage motion does not need a new shadow map on every frame.
  renderer.shadowMap.autoUpdate = false;
  renderer.shadowMap.needsUpdate = true;
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.3;
  host.append(renderer.domElement);
  scene.add(new THREE.HemisphereLight(0xfffced, 0x67805b, 2.8));
  const light = new THREE.DirectionalLight(0xfff3da, 4);
  light.position.set(-3, 8, 6); light.castShadow = true;
  light.shadow.mapSize.set(1024, 1024);
  Object.assign(light.shadow.camera, {left:-5,right:5,top:5,bottom:-5});
  light.shadow.normalBias = .035;
  scene.add(light);
  const world = new THREE.Group(); scene.add(world);
  world.rotation.y = -.18;
  const mats = {};
  const material = color => mats[color] ||= new THREE.MeshStandardMaterial({color, roughness:.85});
  function mesh(geometry, color, parent=world) {
    const obj = new THREE.Mesh(geometry, material(color)); obj.castShadow=true;obj.receiveShadow=true;parent.add(obj);return obj;
  }
  function box(w,h,d,color,x,y,z,parent=world){const m=mesh(new THREE.BoxGeometry(w,h,d),color,parent);m.position.set(x,y,z);return m;}
  function ball(r,color,x,y,z,sx=1,sy=1,sz=1,parent=world){const m=mesh(new THREE.SphereGeometry(r,24,16),color,parent);m.position.set(x,y,z);m.scale.set(sx,sy,sz);return m;}
  // Two gently lifted halves, with visible paper edges and cloth covers.
  for(const side of [-1,1]) {
    const half=new THREE.Group();world.add(half);half.rotation.z=side*.08;
    box(2.65,.13,3.5,'#356849',side*1.32,-.12,0,half);
    box(2.49,.24,3.31,'#eee9d6',side*1.29,.055,0,half);
    for(let i=0;i<5;i++)box(2.51,.013,3.33,'#d4cfb9',side*1.29,-.025+i*.045,0,half);
    const page = new THREE.PlaneGeometry(2.48,3.29,24,1);
    const points=page.attributes.position;
    for(let i=0;i<points.count;i++){const x=points.getX(i);points.setZ(i,.07*Math.sin((x/2.48+.5)*Math.PI));}
    page.computeVertexNormals();
    const sheet=mesh(page,'#fffbea',half);sheet.rotation.x=-Math.PI/2;sheet.position.set(side*1.29,.2,0);
  }
  box(.09,.12,3.54,'#254c36',0,-.15,0);
  // A ribbon bookmark and a few printed lines make the object unmistakably a book.
  box(.24,.018,1.0,'#c8855c',.54,.27,1.55).rotation.x=.14;
  for(let i=0;i<5;i++)box(1.25-i%2*.3,.012,.025,'#a6b29a',-1.42,.36, .5+i*.14);
  for(let i=0;i<3;i++)box(.75,.012,.025,'#a6b29a',1.55,.39,1.0+i*.14);
  // A miniature paper garden grows out of the open spread.
  const mound=ball(1,'#98b979',.7,.3,-.35,1.35,.18,1.1);
  ball(.85,'#c0d294',-1.2,.3,-.65,1,.15,1);
  const plants=[];
  function tree(x,z,size,color){
    const g=new THREE.Group();g.position.set(x,.35,z);g.scale.setScalar(size);world.add(g);plants.push(g);
    mesh(new THREE.CylinderGeometry(.055,.085,1.65,10),'#836b44',g).position.y=.8;
    const crown=ball(.65,color,0,1.65,0,.8,1.3,.7,g);
    crown.rotation.z=-.12;
    for(const side of [-1,1]){const b=mesh(new THREE.CylinderGeometry(.02,.035,.6,8),'#836b44',g);b.position.set(side*.17,1.15,0);b.rotation.z=side*-.6;}
  }
  tree(-1.65,-.75,.93,'#6a9253');tree(.75,-.9,1.25,'#4c7b46');tree(1.65,-.3,.7,'#87a963');
  function sprout(x,z,scale){const g=new THREE.Group();world.add(g);g.position.set(x,.4,z);g.scale.setScalar(scale);plants.push(g);box(.025,.5,.025,'#5e7c45',0,.22,0,g);for(const side of [-1,1]){const l=ball(.2,'#729450',side*.13,.35,0,1.2,.45,.55,g);l.rotation.z=side*.55;}}
  sprout(-.55,-.4,1);sprout(1.8,.55,.8);sprout(-1.9,.1,.7);
  for(const [x,z,s] of [[.2,.55,1],[1.15,.25,.8],[-.85,-1.1,.7]]) {
    const g=new THREE.Group();world.add(g);g.position.set(x,.38,z);plants.push(g);
    box(.028,.45*s,.028,'#557846',0,.2*s,0,g);
    for(let i=0;i<6;i++){const a=i*Math.PI/3;ball(.1*s,'#e7bd72',Math.sin(a)*.12*s,.48*s+Math.cos(a)*.12*s,0,1,1,.5,g);}
    ball(.075*s,'#9b7846',0,.48*s,.035,1,1,.65,g);
  }
  // Cloud and sun silhouettes sit behind the garden, like pop-up paper cutouts.
  ball(.39,'#e8c881',-1.15,3.2,-1.2,1,1,.22);
  function cloud(x,y,z,s){const g=new THREE.Group();g.position.set(x,y,z);g.scale.setScalar(s);world.add(g);for(const [px,py,r] of [[-.35,0,.28],[0,.12,.4],[.36,0,.27]])ball(r,'#fffdf0',px,py,0,1,.75,.5,g);return g;}
  const clouds=[cloud(1.5,3,-1.2,.85),cloud(-2.05,2.5,-.9,.65)];
  const butterfly=new THREE.Group();world.add(butterfly);
  const wings=[];for(const side of [-1,1]){const w=ball(.14,'#d79a69',side*.12,0,0,1,1.3,.2,butterfly);w.rotation.z=side*-.3;wings.push(w);}
  butterfly.position.set(.1,2,1);
  const ground=new THREE.Mesh(new THREE.PlaneGeometry(40,40),new THREE.ShadowMaterial({opacity:.12}));ground.rotation.x=-Math.PI/2;ground.position.y=-.36;ground.receiveShadow=true;scene.add(ground);

  // Compile materials without holding up the reading controls where supported.
  await renderer.compileAsync(scene, camera);

  let paused=reduced.matches, visible=true, frame=0, time=0, last=0, rendered=0;
  const target={x:0,y:0};
  function draw(now=0){
    // 30fps is sufficient for this slow illustration and saves mobile GPU work.
    if (!paused && now-rendered < 1000/30) { frame=requestAnimationFrame(draw); return; }
    rendered=now;
    const delta=Math.min((now-last)/1000,.04);last=now;
    if(!paused){time+=delta;world.rotation.y+=(-.18+target.x*.14-world.rotation.y)*.045;world.rotation.x+=(target.y*.035-world.rotation.x)*.045;
      plants.forEach((p,i)=>p.rotation.z=Math.sin(time*.8+i)*.018);
      clouds.forEach((c,i)=>c.position.y=(i?2.5:3)+Math.sin(time*.6+i)*.06);
      butterfly.position.set(Math.sin(time*.45)*.65,2+Math.sin(time*.9)*.13,.8+Math.cos(time*.45)*.2);
      wings.forEach((w,i)=>w.rotation.y=Math.sin(time*7)*(i?1:-1)*.7);
    }
    renderer.render(scene,camera);
    frame=(!paused&&visible&&!document.hidden)?requestAnimationFrame(draw):0;
  }
  function resume(){if(!frame){last=performance.now();draw(last);}}
  function resize(){const {width,height}=host.getBoundingClientRect();if(!width||!height)return;camera.aspect=width/height;camera.updateProjectionMatrix();renderer.setSize(width,height);resume();}
  const observer=new ResizeObserver(resize);observer.observe(host);
  const intersection=new IntersectionObserver(([entry])=>{visible=entry.isIntersecting;if(visible)resume();});intersection.observe(host);
  const move=e=>{const r=host.getBoundingClientRect();target.x=(e.clientX-r.left)/r.width-.5;target.y=(e.clientY-r.top)/r.height-.5;};
  host.addEventListener('pointermove',move);host.addEventListener('pointerleave',()=>{target.x=target.y=0;});
  const visibility=()=>{if(!document.hidden)resume();};document.addEventListener('visibilitychange',visibility);
  function setPaused(value){paused=value;toggle.textContent=paused?'Play animation':'Pause animation';toggle.setAttribute('aria-pressed',String(paused));resume();}
  toggle.hidden=false;toggle.addEventListener('click',()=>setPaused(!paused));
  const preference=()=>setPaused(reduced.matches);reduced.addEventListener('change',preference);setPaused(paused);
  resize();host.classList.add('ready');
  // Release WebGL resources when this page is discarded; bfcache restores remain live.
  window.addEventListener('pagehide',event=>{if(event.persisted)return;cancelAnimationFrame(frame);observer.disconnect();intersection.disconnect();reduced.removeEventListener('change',preference);document.removeEventListener('visibilitychange',visibility);scene.traverse(obj=>{obj.geometry?.dispose();});Object.values(mats).forEach(m=>m.dispose());ground.material.dispose();renderer.dispose();},{once:true});
  renderer.domElement.addEventListener('webglcontextlost',event=>{event.preventDefault();cancelAnimationFrame(frame);frame=0;host.classList.remove('ready');toggle.hidden=true;});
}
