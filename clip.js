// Shared click-to-play for the example clips (browse cards and the example-clips page).
// One clip plays at a time and a clip is unloaded when it scrolls away: iOS Safari stops loading new
// <video> elements once a page holds more than a handful, so clips must be released, not just paused.
// A load failure shows a retry state instead of a silent black box.
(function(){
  let active=null;
  // unload only once the clip has been on screen and then left it (the first callback reports the initial state)
  const io='IntersectionObserver' in window?new IntersectionObserver(es=>es.forEach(e=>{if(e.target!==active)return;if(e.isIntersecting)e.target.dataset.seen='1';else if(e.target.dataset.seen)closeClip()}),{threshold:0}):null;
  function closeClip(){const box=active;active=null;if(!box)return;if(io)io.unobserve(box);
    const v=box.querySelector('video');if(v){v.pause();v.removeAttribute('src');v.load();v.remove()}
    box.classList.remove('playing');delete box.dataset.seen}
  function openClip(box){
    if(box.querySelector('video'))return;
    if(active&&active!==box)closeClip();
    box.querySelectorAll('.clip-err').forEach(e=>e.remove());
    const v=document.createElement('video');
    v.controls=true;v.loop=true;v.muted=true;v.playsInline=true;v.preload='auto';
    v.setAttribute('muted','');v.setAttribute('playsinline','');v.setAttribute('autoplay','');
    v.addEventListener('error',()=>{if(active===box)active=null;if(io)io.unobserve(box);v.remove();box.classList.remove('playing');
      const m=document.createElement('div');m.className='clip-err';m.textContent='Clip failed to load. Tap to retry.';box.appendChild(m)});
    v.src=box.dataset.src;box.appendChild(v);box.classList.add('playing');active=box;if(io)io.observe(box);
    const p=v.play();if(p&&p.catch)p.catch(()=>{});
  }
  window.openClip=openClip;window.closeClip=closeClip;
})();
