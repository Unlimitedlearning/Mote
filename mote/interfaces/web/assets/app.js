const $=id=>document.getElementById(id);
const state={sessions:[],current:null,messages:[],names:{},tree:null,busy:false,seq:0,editNode:null,settingsMode:'hybrid',ctrl:null,retry:null,hits:[],hitTotal:0,hitSeq:0,searchTimer:null,win:40,treePos:null,settings:null,zoom:1,zoomAuto:true,treeDragMoved:false,find:{open:false,q:'',hits:[],cur:-1,scroll:false,dirty:false,painted:false}};

function esc(s){return String(s==null?'':s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}

function inline(src){
  let s=esc(src), codes=[];
  s=s.replace(/`([^`\n]+)`/g,(m,c)=>{codes.push('<code>'+c+'</code>');return '__CD'+(codes.length-1)+'__';});
  s=s.replace(/\*\*([^*]+)\*\*/g,'<strong>$1</strong>');
  s=s.replace(/(^|[^*])\*([^*\n]+)\*/g,'$1<em>$2</em>');
  s=s.replace(/~~([^~]+)~~/g,'<del>$1</del>');
  s=s.replace(/\[([^\]]+)\]\(([^)]+)\)/g,(m,t,u)=>{
    const url=u.trim();
    if(!/^(https?:\/\/|mailto:|#)/i.test(url))return m;
    return '<a href="'+esc(url)+'" target="_blank" rel="noopener">'+t+'</a>';
  });
  return s.replace(/__CD(\d+)__/g,(m,i)=>codes[Number(i)]||m);
}

function md(src){
  const lines=String(src||'').replace(/\r\n?/g,'\n').split('\n');
  const out=[]; let para=[]; let i=0;
  const flush=()=>{if(para.length){out.push('<p>'+inline(para.join('\n')).replace(/\n/g,'<br>')+'</p>');para=[];}};
  const cells=s=>s.trim().replace(/^\||\|$/g,'').split('|').map(x=>x.trim());
  while(i<lines.length){
    const line=lines[i];
    if(/^\s*```/.test(line)){
      flush();
      const lang=line.trim().slice(3).trim(); const buf=[]; i++;
      while(i<lines.length&&!/^\s*```/.test(lines[i])){buf.push(lines[i]);i++;}
      i++;
      out.push('<pre><span class="head"><span>'+esc(lang||'text')+'</span><button type="button" class="copy">复制</button></span><code>'+esc(buf.join('\n'))+'</code></pre>');
      continue;
    }
    if(/^\s*$/.test(line)){flush();i++;continue;}
    const h=line.match(/^\s*(#{1,6})\s+(.*)$/);
    if(h){flush();out.push('<h'+h[1].length+'>'+inline(h[2])+'</h'+h[1].length+'>');i++;continue;}
    if(/^\s*(?:-{3,}|\*{3,}|_{3,})\s*$/.test(line)){flush();out.push('<hr>');i++;continue;}
    if(line.indexOf('|')>=0&&i+1<lines.length&&/^\s*\|?\s*:?-{1,}:?\s*(\|\s*:?-{1,}:?\s*)+\|?\s*$/.test(lines[i+1])){
      flush();
      const head=cells(lines[i]); i+=2; const rows=[];
      while(i<lines.length&&lines[i].trim()&&lines[i].indexOf('|')>=0){rows.push(cells(lines[i]));i++;}
      out.push('<div class="table-wrap"><table><thead><tr>'+head.map(x=>'<th>'+inline(x)+'</th>').join('')+
        '</tr></thead><tbody>'+rows.map(r=>'<tr>'+r.map(x=>'<td>'+inline(x)+'</td>').join('')+'</tr>').join('')+
        '</tbody></table></div>');
      continue;
    }
    if(/^\s*>\s?/.test(line)){
      flush(); const buf=[];
      while(i<lines.length&&/^\s*>\s?/.test(lines[i])){buf.push(lines[i].replace(/^\s*>\s?/,''));i++;}
      out.push('<blockquote>'+inline(buf.join('\n')).replace(/\n/g,'<br>')+'</blockquote>');continue;
    }
    const li=line.match(/^\s*([-*+]|\d+\.)\s+(.*)$/);
    if(li){
      flush(); const ordered=/^\d+\./.test(li[1]), items=[];
      while(i<lines.length){
        const m=lines[i].match(/^\s*([-*+]|\d+\.)\s+(.*)$/);
        if(!m||/^\d+\./.test(m[1])!==ordered)break;
        items.push('<li>'+inline(m[2])+'</li>');i++;
      }
      out.push('<'+(ordered?'ol':'ul')+'>'+items.join('')+'</'+(ordered?'ol':'ul')+'>');continue;
    }
    para.push(line);i++;
  }
  flush();return out.join('');
}

function scrollBottom(force){
  const el=$('scroll');
  if(force||el.scrollHeight-el.scrollTop-el.clientHeight<180)el.scrollTop=el.scrollHeight;
}

function thinkBlock(text,open,label,node){
  const d=document.createElement('details');d.className='think';if(open)d.open=true;
  const s=document.createElement('summary');s.textContent=label;
  // 推理原文常带小标题、列表和代码：按 Markdown 渲染，而不是原样贴文本
  const b=document.createElement('div');b.className='body md';b.innerHTML=text?md(text):'';
  if(!text&&node&&state.current){
    d.addEventListener('toggle',async()=>{
      if(!d.open||b.dataset.loaded)return;
      const sid=state.current;
      b.dataset.loaded='1';b.textContent='读取中…';
      try{
        const r=await fetch('/sessions/'+encodeURIComponent(sid)+'/thinking/'+encodeURIComponent(node));
        const data=await r.json();
        if(!r.ok||data.error)throw new Error(data.error||'读取失败');
        b.innerHTML=md(data.text||'');
        const m=state.messages.find(x=>x.role==='assistant'&&x.node===node);
        if(m){m.thinking=data.text||'';m.thinking_chars=(data.text||'').length;}
        s.textContent='思考过程（'+(data.chars||0)+' 字）';
      }catch(err){
        b.dataset.loaded='';b.textContent='思考内容读取失败：'+err.message;
      }
    });
  }
  d.appendChild(s);d.appendChild(b);return d;
}
function paintPendingInto(bubble,m){
  bubble.innerHTML='';
  if(m.thinking)bubble.appendChild(thinkBlock(m.thinking,true,'思考中 · '+m.thinking.length+' 字'));
  if(m.text){
    const body=document.createElement('div');body.className='md';body.innerHTML=md(m.text);
    bubble.appendChild(body);
  }else{
    const t=document.createElement('div');t.className='thinking';
    t.innerHTML='<span class="spin"></span>思考中<span class="secs"></span>';
    t.querySelector('.secs').textContent=((Date.now()-(m.started||Date.now()))/1000).toFixed(0)+'s';
    bubble.appendChild(t);
  }
}
function paintPending(){
  const idx=state.messages.findIndex(m=>m.pending);if(idx<0)return;
  const start=winStart();
  const row=$('thread').children[idx-start+(start>0?1:0)];if(!row)return;
  const bubble=row.querySelector('.bubble');if(!bubble)return;
  const old=bubble.querySelector('.think');
  paintPendingInto(bubble,state.messages[idx]);
  if(old&&old.open){const next=bubble.querySelector('.think');if(next)next.open=true;}
}

// 窗口默认取末尾 win 条；查找跳转会临时指定 [winFrom, winEnd) 这一小段，
// 否则上千轮的导入会话里定位一句话要把整段历史重绘一遍
function winStart(){return state.winFrom!=null?state.winFrom:Math.max(0,state.messages.length-state.win);}
function winEnd(){return state.winEnd!=null?Math.min(state.winEnd,state.messages.length):state.messages.length;}
function resetWin(){state.win=40;state.winFrom=null;state.winEnd=null;}
function branchIndex(){
  const nodes=(state.tree&&state.tree.nodes)||[];
  const groups={};
  nodes.forEach(n=>{const p=n.parent||null;(groups[p]=groups[p]||[]).push(n.id);});
  const map={};
  Object.keys(groups).forEach(p=>{
    const ids=groups[p];if(ids.length<2)return;
    ids.forEach((id,i)=>{map[id]={ids,at:i};});
  });
  return map;
}
function branchNavFor(node,index){
  const hit=index&&index[node];if(!hit)return null;
  const ids=hit.ids, at=hit.at;
  const el=document.createElement('div');el.className='branch-nav';
  el.dataset.prev=ids[(at-1+ids.length)%ids.length];
  el.dataset.next=ids[(at+1)%ids.length];
  el.innerHTML='<button type="button" data-act="prev" title="上一个分支">‹</button>'+
    '<span class="count">'+(at+1)+'/'+ids.length+'</span>'+
    '<button type="button" data-act="next" title="下一个分支">›</button>';
  return el;
}
function renderMessages(keep){
  const scroll=$('scroll'), prevTop=scroll.scrollTop, prevHeight=scroll.scrollHeight;
  const box=$('thread'); box.innerHTML='';state.find.painted=false;
  if(!state.messages.length){
    const e=document.createElement('div'); e.className='empty';
    e.innerHTML='<div class="big">M</div><h2>带一个问题来</h2><p>我会挑几个思维镜头，给你判断建议。任务清单由你自己管。</p>'+
      '<div class="suggest">'+
      ['<button>手里有个还没做完的项目，该不该现在换工作？','<button>这个方案看起来不错，怎么找它的隐患？','<button>两个 offer 差别很大，怎么判断哪个更适合我？','<button>团队一直加班，问题到底出在哪里？'].map(s=>s+'</button>').join('')+'</div>';
    box.appendChild(e);
    e.querySelectorAll('.suggest button').forEach(b=>b.onclick=()=>{$('q').value=b.textContent;$('q').focus();});
    $('toLatest').classList.remove('show');return;
  }
  const start=winStart(), end=winEnd(), index=branchIndex();
  let lastAnswer=-1;
  state.messages.forEach((m,i)=>{if(m.role==='assistant'&&m.node)lastAnswer=i;});
  if(start>0){
    const more=document.createElement('button');more.type='button';more.className='load-more';
    more.textContent='加载更早的 '+start+' 条';
    more.onclick=()=>{
      if(state.winFrom!=null)state.winFrom=Math.max(0,start-150);
      else state.win+=150;
      renderMessages(true);
    };
    box.appendChild(more);
  }
  state.messages.slice(start,end).forEach((m,offset)=>{
    const i=start+offset;
    const row=document.createElement('div');row.className='msg '+(m.role==='user'?'user':'assistant');
    const av=document.createElement('div');av.className='avatar '+(m.role==='user'?'u':'m');av.textContent=m.role==='user'?'你':'M';
    const bubble=document.createElement('div');bubble.className='bubble';
    if(m.role==='user'){
      bubble.textContent=m.text;
      if(m.node){
        const foot=document.createElement('div');foot.className='q-foot';
        const nav=branchNavFor(m.node,index);if(nav)foot.appendChild(nav);
        const actions=document.createElement('div');actions.className='msg-actions';
        actions.innerHTML='<button type="button" class="msg-more" data-node="'+esc(m.node)+'" title="管理这条问答">···</button>';
        const menu=document.createElement('div');menu.className='msg-menu';menu.dataset.node=esc(m.node);
        menu.innerHTML='<button type="button" data-act="main">'+mainLabel()+'</button>'+
          '<button type="button" data-act="edit">编辑并另开分支</button>'+
          '<button type="button" class="danger" data-act="delete">删除问题与回复</button>';
        actions.appendChild(menu);foot.appendChild(actions);
        bubble.appendChild(foot);
      }
    }
    else if(m.pending){paintPendingInto(bubble,m);}
    else if(m.error){
      const box=document.createElement('div');box.className='err-box';
      const t=document.createElement('div');t.className='failed';t.textContent='生成失败：'+m.error;
      box.appendChild(t);
      const row=document.createElement('div');row.className='row';
      const again=document.createElement('button');again.type='button';again.className='retry';again.textContent='重试';
      row.appendChild(again);box.appendChild(row);bubble.appendChild(box);
    }
    else{
      if(m.thinking)bubble.appendChild(thinkBlock(m.thinking,false,'思考过程（'+m.thinking.length+' 字）',m.node));
      else if(m.thinking_chars)bubble.appendChild(thinkBlock('',false,'思考过程（'+m.thinking_chars+' 字）',m.node));
      const body=document.createElement('div');body.className='md';body.innerHTML=md(m.text);bubble.appendChild(body);
      if(m.stopped){
        const note=document.createElement('div');note.className='stop-note';note.textContent='已停止生成';
        bubble.appendChild(note);
      }
      const chips=[];
      if(m.route==='local')chips.push('本地 · '+(m.model||'qwen'));
      else if(m.mode==='direct'||m.route==='direct')chips.push('云端直连 · '+(m.model||m.worker||''));
      else if(m.route==='cloud')chips.push('云端 · '+(m.model||m.worker||''));
      else if(m.model)chips.push(m.model);
      if(m.saved_chars)chips.push('省 '+m.saved_chars+' 字上下文');
      (m.lenses||[]).forEach(k=>chips.push(state.names[k]||k));
      if(chips.length){
        const row2=document.createElement('div');row2.className='lens-row';
        chips.forEach(label=>{const c=document.createElement('span');c.className='lens-chip';c.textContent=label;row2.appendChild(c);});
        bubble.appendChild(row2);
      }
      if(i===lastAnswer&&m.node){
        const tools=document.createElement('div');tools.className='ans-tools';
        const regen=document.createElement('button');regen.type='button';
        regen.className='regen';regen.dataset.node=m.node;regen.textContent='重新生成';
        tools.appendChild(regen);bubble.appendChild(tools);
      }
    }
    if(m.role==='user'&&m.node)row.dataset.node=m.node;
    else if(m.role==='assistant'&&m.node)row.dataset.ansnode=m.node;
    row.appendChild(av);row.appendChild(bubble);box.appendChild(row);
  });
  if(end<state.messages.length){
    const rest=state.messages.length-end;
    const more=document.createElement('button');more.type='button';more.className='load-more';
    more.textContent='加载更新的 '+Math.min(150,rest)+' 条';
    more.onclick=()=>{state.winEnd=Math.min(state.messages.length,end+150);renderMessages(true);};
    box.appendChild(more);
  }
  if(keep)scroll.scrollTop=prevTop+(scroll.scrollHeight-prevHeight);
  else scroll.scrollTop=scroll.scrollHeight;
  $('toLatest').classList.remove('show');
  if(state.find.open&&!state.find.dirty&&state.find.q)paintFind();
}

function groupOf(s){
  const d=new Date(String(s.date||'').replace(' ','T'));const t=new Date();t.setHours(0,0,0,0);
  if(d>=t)return '今天';
  const y=new Date(t);y.setDate(y.getDate()-1);
  if(d>=y)return '昨天';
  if(d>=new Date(t.getTime()-6*86400000))return '近 7 天';
  return '更早';
}
function closeMenus(){document.querySelectorAll('.session-row.open').forEach(r=>r.classList.remove('open'));}
function renderSessions(){
  const q=$('search').value.trim().toLowerCase(), box=$('sessions');box.innerHTML='';
  const rows=state.sessions.filter(s=>!q||((s.title||'')+' '+(s.preview||'')+' '+s.id).toLowerCase().includes(q));
  if(!rows.length){box.innerHTML=q?'':'<div class="group">还没有历史对话</div>';return;}
  let last='';
  rows.forEach(s=>{
    const g=groupOf(s);
    if(g!==last){const h=document.createElement('div');h.className='group';h.textContent=g;box.appendChild(h);last=g;}
    const wrap=document.createElement('div');wrap.className='session-row';wrap.dataset.id=s.id;
    const b=document.createElement('button');b.className='session'+(s.id===state.current?' active':'');
    b.dataset.id=s.id;
    b.innerHTML='<div class="t">'+esc(s.title||'新对话')+'</div><div class="m">'+esc((s.date||'').replace('T',' ').slice(5,16))+' · '+s.turns+' 轮</div>';
    const more=document.createElement('button');more.className='more';more.dataset.id=s.id;
    more.textContent='···';more.title='管理对话';
    const menu=document.createElement('div');menu.className='menu';
    menu.innerHTML='<button type="button" data-act="rename" data-id="'+s.id+'">重命名</button>'+
                   '<button type="button" data-act="export-md" data-id="'+s.id+'">导出 Markdown</button>'+
                   '<button type="button" data-act="export-json" data-id="'+s.id+'">导出 JSON</button>'+
                   '<button type="button" class="danger" data-act="delete" data-id="'+s.id+'">删除</button>';
    wrap.appendChild(b);wrap.appendChild(more);wrap.appendChild(menu);box.appendChild(wrap);
  });
}
function hitMarkup(h){
  const snippet=esc(h.snippet||'').replace(/\u0001/g,'<mark>').replace(/\u0002/g,'</mark>');
  return '<div class="ht">'+esc(h.title||'新对话')+'</div>'+
    '<div class="hs">'+snippet+'</div>'+
    '<div class="hm">'+(h.role==='user'?'你':'AI')+' · 第 '+esc(String(h.turn||'-'))+' 轮 · '+
    esc((h.ts||'').replace('T',' ').slice(5,16))+'</div>';
}
function renderHits(){
  const q=$('search').value.trim(), box=$('hits');
  if(!q){box.innerHTML='';box.style.display='none';return;}
  box.style.display='block';
  const head='<div class="hd"><span>聊天内容</span><span>'+(state.hitTotal?state.hitTotal+' 条':'')+'</span></div>';
  if(!state.hits.length){box.innerHTML=head+'<div class="hempty">没有匹配的消息</div>';return;}
  box.innerHTML=head+state.hits.map(h=>'<button type="button" class="hit" data-session="'+esc(h.session)+'" data-node="'+esc(h.node||'')+'" data-role="'+esc(h.role||'')+'">'+hitMarkup(h)+'</button>').join('');
}
async function runSearch(q){
  const seq=++state.hitSeq;
  try{
    const r=await fetch('/search?q='+encodeURIComponent(q)+'&limit=30');
    const d=await r.json();
    if(seq!==state.hitSeq)return;
    if(!r.ok||d.error)throw new Error(d.error||'搜索失败');
    state.hits=d.results||[];state.hitTotal=d.total||0;renderHits();
  }catch(err){
    if(seq!==state.hitSeq)return;
    state.hits=[];state.hitTotal=0;renderHits();
  }
}
function onSearchInput(){
  renderSessions();
  const q=$('search').value.trim();
  clearTimeout(state.searchTimer);++state.hitSeq;
  if(!q){state.hits=[];state.hitTotal=0;renderHits();return;}
  state.searchTimer=setTimeout(()=>runSearch(q),260);
}
async function openHit(sid,node,role){
  if(state.busy||!sid)return;
  if(state.current!==sid)await select(sid,true);
  if(node)await jumpToNode(node,role);
}
function download(url){
  const a=document.createElement('a');a.href=url;a.download='';
  document.body.appendChild(a);a.click();a.remove();
}
async function saveRename(id,title){
  const t=String(title||'').trim();
  if(!t){renderSessions();return;}
  try{
    const r=await fetch('/sessions/'+encodeURIComponent(id)+'/title',{
      method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({title:t})});
    const d=await r.json();
    if(!r.ok||d.error)throw new Error(d.error||'重命名失败');
    const s=state.sessions.find(x=>x.id===id);if(s)s.title=d.title;
  }catch(err){alert('重命名失败：'+err.message);}
  renderSessions();setTitle();
}
function beginRename(id){
  const row=document.querySelector('.session-row[data-id="'+id+'"]');
  const t=row&&row.querySelector('.t');if(!t)return;
  const item=state.sessions.find(s=>s.id===id);
  const input=document.createElement('input');input.className='rename-input';
  input.value=item?(item.title||''):t.textContent;
  t.replaceWith(input);input.focus();input.select();
  let done=false;
  const finish=save=>{
    if(done)return;done=true;
    if(save)saveRename(id,input.value);else renderSessions();
  };
  input.addEventListener('keydown',e=>{
    if(e.key==='Enter'){e.preventDefault();finish(true);}
    else if(e.key==='Escape'){e.preventDefault();finish(false);}
    e.stopPropagation();
  });
  input.addEventListener('blur',()=>finish(true));
  input.addEventListener('click',e=>e.stopPropagation());
}
async function deleteSession(id){
  if(!confirm('确定删除这个对话？删除后无法恢复。'))return;
  try{
    const r=await fetch('/sessions/'+encodeURIComponent(id),{method:'DELETE'});
    const d=await r.json();
    if(!r.ok||d.error)throw new Error(d.error||'删除失败');
    await loadSessions();
    if(state.current===id)newChat(false);
  }catch(err){alert('删除失败：'+err.message);}
}
function setTitle(){
  const row=state.sessions.find(s=>s.id===state.current);
  const first=state.messages.find(m=>m.role==='user');
  $('topTitle').textContent=(row&&row.title)||(first&&first.text.slice(0,28))||'新对话';
}
function setHash(id){
  const next=id?'#/c/'+encodeURIComponent(id):'#new';
  if(location.hash!==next)history.pushState(null,'',next);
}
function readHash(){
  const h=decodeURIComponent(location.hash||'');
  return h.startsWith('#/c/')?h.slice(4):null;
}
async function loadSessions(){
  const r=await fetch('/sessions');const d=await r.json();
  state.sessions=d.sessions||[];renderSessions();setTitle();
}
async function select(id,push){
  if(push)setHash(id);
  closeFind();
  state.current=id;state.messages=[];state.tree=null;resetWin();const seq=++state.seq;
  renderSessions();setTitle();renderMessages();
  try{
    const r=await fetch('/sessions/'+encodeURIComponent(id)+'/messages');
    const d=await r.json();
    if(seq!==state.seq)return;
    if(!r.ok)throw new Error(d.error||'读取失败');
    state.messages=d.messages||[];state.tree=d.tree||null;renderMessages();setTitle();
  }catch(err){state.messages=[{role:'assistant',text:'读取历史失败：'+err.message}];renderMessages();}
}
function newChat(push){
  ++state.seq;if(push)setHash(null);
  closeFind();
  state.current=null;state.messages=[];state.tree=null;resetWin();renderSessions();setTitle();renderMessages();$('q').focus();
}
function openFromHash(){
  const id=readHash();
  if(!id)return newChat(false);
  if(state.sessions.some(s=>s.id===id))return select(id,false);
  select(id,false);
}
function closeModal(id){$(id).classList.remove('show');}
async function loadTree(){
  if(!state.current){state.tree=null;return null;}
  try{
    const tip=tipNode();
    const r=await fetch('/sessions/'+encodeURIComponent(state.current)+'/tree'+
      (tip?'?node='+encodeURIComponent(tip):''));
    const d=await r.json();
    if(!r.ok||d.error)throw new Error(d.error||'读取分支失败');
    state.tree=d.tree||null;return state.tree;
  }catch(err){alert('读取分支失败：'+err.message);return null;}
}
function renderTree(){
  const nodes=(state.tree&&state.tree.nodes)||[];
  const by={};nodes.forEach(n=>{by[n.id]=n;});
  const box=$('treeBox'), stat=$('treeStat');
  if(!nodes.length){
    box.innerHTML='<div class="group">还没有问答</div>';
    if(stat)stat.textContent='';
    state.treePos=null;
    return;
  }
  // 主链居中：兄弟里把当前分支摆到中间，其余左右交替，主干才不会一直歪向一侧
  const order=(kids,depth)=>{
    if(kids.length<2)return kids;
    const at=kids.findIndex(k=>k.in_path);
    if(at<0)return kids;
    const rest=kids.slice(), pick=rest.splice(at,1)[0];
    // 只有一个兄弟分支时按层左右交替，连续几层才不会全挂在同一侧
    if(rest.length===1)return depth%2 ? [pick].concat(rest) : rest.concat([pick]);
    const left=[], right=[];
    rest.forEach((k,i)=>(i%2?right:left).push(k));
    return left.concat([pick],right);
  };
  const ROOT=42, PAD=20;
  const mainSet=new Set((state.tree&&state.tree.main_path)||[]);
  const roots=nodes.filter(n=>!n.parent||!by[n.parent]);
  const seen=new Set();
  // 先量深度与叶子数：深链大会话按可用空间压缩层距与列距，否则会画成上万像素的长条
  let depthMax=0, leafCount=0;
  const probe=(n,d)=>{
    if(seen.has(n.id))return;
    seen.add(n.id);
    if(d>depthMax)depthMax=d;
    const kids=(n.children||[]).filter(id=>by[id]).filter(k=>!seen.has(k));
    if(!kids.length){leafCount++;return;}
    kids.forEach(id=>probe(by[id],d+1));
  };
  roots.forEach(r=>probe(r,0));
  nodes.forEach(n=>{if(!seen.has(n.id))probe(n,0);});
  const LV=Math.min(34,Math.max(13,Math.round(5200/Math.max(depthMax,1))));
  const GAP=Math.min(26,Math.max(11,Math.round(4000/Math.max(leafCount,1))));
  const HIT=Math.min(11,Math.max(5.5,GAP/2));
  const DR=GAP<14?4:4.5;
  const pos={};seen.clear();
  let cursor=PAD;
  // 后序定横坐标：叶子按顺序占位，父节点落在首末子中点，单链自然成为一条竖线
  const place=(n,depth)=>{
    if(seen.has(n.id))return null;
    seen.add(n.id);
    const kids=order((n.children||[]).map(id=>by[id]).filter(k=>k&&!seen.has(k.id)),depth);
    let x=cursor;
    if(kids.length){
      const xs=kids.map(k=>place(k,depth+1)).filter(v=>v!==null);
      if(xs.length)x=(xs[0]+xs[xs.length-1])/2;
      else cursor+=GAP;
    }else{
      cursor+=GAP;
    }
    pos[n.id]={x:x,y:PAD+depth*LV};
    return x;
  };
  roots.forEach((r,i)=>{if(i)cursor+=ROOT;place(r,0);});
  // parent 已失效的孤立节点也要画出来，否则整段分支会凭空消失
  nodes.forEach(n=>{if(!seen.has(n.id)){cursor+=ROOT;place(n,0);}});

  const f=v=>Math.round(v*10)/10;
  const width=Math.ceil(cursor+PAD), height=PAD*2+depthMax*LV+12;
  const edges=[], dots=[];
  // 只画点与连线：根在上，子节点向下展开，正文只进 title 提示
  nodes.forEach(n=>{
    const p=pos[n.id]; if(!p)return;
    (n.children||[]).forEach(id=>{
      const c=pos[id], kid=by[id]; if(!c)return;
      const px=f(p.x), py=f(p.y), cx=f(c.x), cy=f(c.y);
      let d;
      if(Math.abs(cx-px)<1){
        d='M'+px+' '+py+'L'+cx+' '+cy;
      }else{
        const my=f((p.y+c.y)/2), dir=cx>px?1:-1;
        const r=Math.max(0,Math.min(6,Math.abs(cx-px)/2,my-py,cy-my));
        d=r<0.6
          ? 'M'+px+' '+py+'L'+px+' '+my+'L'+cx+' '+my+'L'+cx+' '+cy
          : 'M'+px+' '+py+'L'+px+' '+(my-r)+'Q'+px+' '+my+' '+(px+dir*r)+' '+my+
            'L'+(cx-dir*r)+' '+my+'Q'+cx+' '+my+' '+cx+' '+(my+r)+'L'+cx+' '+cy;
      }
      const on=!!(n.in_path&&kid&&kid.in_path);
      const onMain=mainSet.has(n.id)&&mainSet.has(id);
      edges.push('<path class="tm-edge'+(on?' on':(onMain?' main':''))+'" d="'+d+'"/>');
    });
  });
  nodes.forEach(n=>{
    const p=pos[n.id]; if(!p)return;
    const r=n.active?DR+2:((n.children||[]).length>1?DR+1:DR);
    const x=f(p.x), y=f(p.y);
    const label=esc(String(n.text||'（空问题）').replace(/\s+/g,' ').slice(0,80));
    dots.push('<g class="tm-node'+(n.in_path?' on':'')+(n.active?' cur':'')+(mainSet.has(n.id)?' main':'')+'" data-node="'+esc(n.id)+'">'+
      '<title>'+label+'</title>'+
      '<circle cx="'+x+'" cy="'+y+'" r="'+HIT+'" fill="transparent"/>'+
      (n.active?'<circle class="halo" cx="'+x+'" cy="'+y+'" r="'+(DR+4)+'"/>':'')+
      '<circle class="dot" cx="'+x+'" cy="'+y+'" r="'+r+'"/>'+
      '</g>');
  });
  box.innerHTML='<div class="tree-map"><svg xmlns="http://www.w3.org/2000/svg" width="'+width+'" height="'+height+
    '" viewBox="0 0 '+width+' '+height+'" role="img" aria-label="对话分支树">'+
    edges.join('')+dots.join('')+'</svg></div>';
  // 窄树居中，宽树左对齐（居中会让溢出部分滚不到）
  box.firstChild.classList.toggle('narrow', width<box.clientWidth-8);
  const act=nodes.find(n=>n.active);
  state.treePos=(act&&pos[act.id])?pos[act.id]:null;
  const forks=nodes.filter(n=>(n.children||[]).length>1).length;
  if(stat)stat.textContent='共 '+nodes.length+' 个问题'+(forks?' · '+forks+' 处分叉':'');
  treeZoomStyle();
}
async function openTree(){
  if(state.busy)return;
  if(!state.current){alert('当前还没有对话');return;}
  await loadTree();
  // 大会话有一千多个节点，先把弹窗和提示画出来，再渲染整棵树，避免点击后没有反馈
  $('treeBox').innerHTML='<div class="group">正在画分支…</div>';
  $('treeModal').classList.add('show');
  await new Promise(r=>requestAnimationFrame(()=>r()));
  renderTree();
  const zbox=$('treeBox'), zsvg=zbox.querySelector('.tree-map svg');
  if(state.zoomAuto&&zsvg&&Number(zsvg.getAttribute('width'))>zbox.clientWidth-40)treeFit();
  else centerOnNode();
}

// ── 分支树缩放：zoom 落在 .tree-map 上，滚动条、点击坐标都跟着一起缩
const TREE_ZMIN=0.15, TREE_ZMAX=2.5;
function treeZoomStyle(){
  const box=$('treeBox'), map=box.querySelector('.tree-map');
  if(!map)return;
  map.style.zoom=state.zoom;
  const svg=map.querySelector('svg');
  const w=(Number(svg&&svg.getAttribute('width'))||0)*state.zoom;
  // 缩小后能一屏放下的树重新居中，否则左对齐保留横向滚动
  map.classList.toggle('narrow',w<box.clientWidth-8);
  $('zoomPct').textContent=Math.round(state.zoom*100)+'%';
}
function centerOnNode(){
  const box=$('treeBox'), at=state.treePos, z=state.zoom||1;
  if(!at){box.scrollLeft=0;box.scrollTop=0;return;}
  box.scrollLeft=Math.max(0,at.x*z-box.clientWidth/2);
  box.scrollTop=Math.max(0,at.y*z-box.clientHeight/2);
}
// 以鼠标位置（缺省为视口中心）为锚点缩放，缩放前后锚点下的内容不动
function treeZoom(z,ax,ay){
  const box=$('treeBox'), map=box.querySelector('.tree-map');
  if(!map){$('zoomPct').textContent=Math.round((state.zoom||1)*100)+'%';return;}
  const old=state.zoom||1;
  state.zoomAuto=false;
  z=Math.max(TREE_ZMIN,Math.min(TREE_ZMAX,z));
  if(Math.abs(z-old)<0.001){treeZoomStyle();return;}
  const px=ax==null?box.clientWidth/2:ax, py=ay==null?box.clientHeight/2:ay;
  const cx=(box.scrollLeft+px)/old, cy=(box.scrollTop+py)/old;
  state.zoom=z;map.style.zoom=z;
  box.scrollLeft=Math.max(0,cx*z-px);
  box.scrollTop=Math.max(0,cy*z-py);
  treeZoomStyle();
}
// 只缩小不放大：宽树缩到一屏，窄树保持原样
function treeFit(){
  const box=$('treeBox'), svg=box.querySelector('.tree-map svg');
  if(!svg)return;
  const w=Number(svg.getAttribute('width'))||1;
  state.zoom=Math.max(TREE_ZMIN,Math.min(1,box.clientWidth/(w+24)));
  treeZoomStyle();
  if(box.scrollWidth>box.clientWidth-4){
    state.zoom=Math.max(TREE_ZMIN,state.zoom*(box.clientWidth-4)/box.scrollWidth);
    treeZoomStyle();
  }
  centerOnNode();
}

function revealNode(node,role){
  const pick=wanted=>{
    for(let i=state.messages.length-1;i>=0;i--){
      const m=state.messages[i];
      if(m.node===node&&m.role===wanted)return i;
    }
    return -1;
  };
  let idx=pick(role==='assistant'?'assistant':'user');
  if(idx<0)idx=pick('user');
  if(idx<0)idx=pick('assistant');
  if(idx<0)return;
  const fromEnd=state.messages.length-idx;
  state.winFrom=null;state.winEnd=null;
  if(fromEnd>state.win)state.win=fromEnd+20;
}
// 界面当前显示的那条链的末端：跳转、删除、提问都以它为准，主分支不参与
function tipNode(){
  for(let i=state.messages.length-1;i>=0;i--){
    const m=state.messages[i];
    if(m.role==='user'&&m.node)return m.node;
  }
  return null;
}
// 主分支标记落在当前这条链路上时，菜单项变成「取消主分支」
function pinnedHere(){
  const t=state.tree||{};
  return !!(t.main&&(t.path||[]).indexOf(t.main)>=0);
}
function mainLabel(){return pinnedHere()?'取消主分支':'设为主分支';}
let noteTimer=null;
function note(text){
  const el=$('note');if(!el)return;
  el.textContent=text;el.classList.add('show');
  clearTimeout(noteTimer);
  noteTimer=setTimeout(()=>el.classList.remove('show'),2400);
}
async function setMain(node){
  if(state.busy||!state.current)return;
  const tree=state.tree||{};
  // 已在这条链上就取消；否则钉到这条链的末端——游标只记分叉点，只有末端能唯一确定一条链
  const off=pinnedHere();
  const target=off?null:(tree.active||node);
  try{
    const r=await fetch('/sessions/'+encodeURIComponent(state.current)+'/main',{
      method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({node:target,tip:tipNode()})});
    const d=await r.json();
    if(!r.ok||d.error)throw new Error(d.error||'设置失败');
    if(d.tree)state.tree=d.tree;
    renderMessages(true);
    note(off?'已取消主分支，打开这个对话跟随最近的分支'
           :'已设为主分支，以后打开这个对话默认停在这条链路');
  }catch(err){alert('设置主分支失败：'+err.message);}
}
// ── 设置：端点、模型与 API Key 在页面里改，保存后写入 config.json 并立即生效
function settingsProfile(name,data){
  const d=data||state.settings||{};
  return (d.profiles||[]).find(p=>p&&p.name===name)||null;
}
// ── 外观：主题只存本机 localStorage，不进 config.json，点选即时生效
function themeNow(){return document.documentElement.dataset.theme==='dark'?'dark':'light';}
function paintTheme(){
  const t=themeNow();
  document.querySelectorAll('#setTheme button').forEach(b=>{
    b.classList.toggle('active',b.dataset.theme===t);
  });
}
function setTheme(t){
  document.documentElement.dataset.theme=t;
  try{localStorage.setItem('mote-theme',t);}catch(e){}
  paintTheme();
  // 分支树的配色全部来自 CSS 变量，切换时 SVG 不用重画
}
function setGroupEnabled(name,on){
  const map={cloud:['setCloudUrl','setCloudModel','setCloudKey','setCloudThink'],
             local:['setLocalUrl','setLocalModel']};
  (map[name]||[]).forEach(id=>{const el=$(id);if(el)el.disabled=!on;});
}
function paintSettingsMode(data){
  const local=settingsProfile('local',data);
  if(!local&&state.settingsMode!=='direct')state.settingsMode='direct';
  document.querySelectorAll('#setMode button').forEach(b=>{
    b.classList.toggle('active',b.dataset.mode===state.settingsMode);
    // 两种要用本地模型的方式，缺 local 端点时都点不动
    if(b.dataset.mode!=='direct')b.disabled=!local;
  });
  $('setModeWarn').textContent=local?''
    :'配置里没有 local 端点，只能用「直接云端」；想用本地前置或仅本地，需要在 config.json 里补上 local。';
}
function fillSettings(d){
  const cloud=settingsProfile('cloud',d), local=settingsProfile('local',d);
  $('setCloudUrl').value=cloud?cloud.base_url:'';
  $('setCloudModel').value=cloud?cloud.model:'';
  $('setCloudKey').value='';
  $('setCloudKey').placeholder=!cloud?'（配置里没有 cloud 端点）'
    :cloud.has_key?('已保存（'+cloud.key_hint+'），留空不修改')
    :cloud.key_env?('未设置：可填 sk-… 或设置环境变量 '+cloud.key_env):'sk-…';
  $('setCloudThink').checked=!!(cloud&&cloud.thinking);
  $('setLocalUrl').value=local?local.base_url:'';
  $('setLocalModel').value=local?local.model:'';
  const mode=d.hybrid&&d.hybrid.mode;
  state.settingsMode=(mode==='hybrid'||mode==='direct'||mode==='local')
    ?mode:((d.hybrid&&d.hybrid.enabled)?'hybrid':'direct');
  setGroupEnabled('cloud',!!cloud);
  setGroupEnabled('local',!!local);
  paintSettingsMode(d);
  paintTheme();
  $('setHint').textContent=d.config_path
    ?'保存后写入 '+d.config_path+'，下一条消息生效。API Key 只存在本机。':'';
  const t=$('setTest');t.textContent='';t.className='';
}
async function openSettings(){
  try{
    const r=await fetch('/settings');
    const d=await r.json();
    if(!r.ok||d.error)throw new Error(d.error||'读取失败');
    state.settings=d;
    fillSettings(d);
    $('setModal').classList.add('show');
  }catch(err){alert('读取设置失败：'+err.message);}
}
async function saveSettings(){
  const profiles={};
  const cloud=settingsProfile('cloud'), local=settingsProfile('local');
  if(cloud){
    profiles.cloud={base_url:$('setCloudUrl').value.trim(),
                    model:$('setCloudModel').value.trim(),
                    thinking:$('setCloudThink').checked};
    // 留空表示不改：后端也按「空值不覆盖」处理，避免误清已保存的 key
    const key=$('setCloudKey').value.trim();
    if(key)profiles.cloud.api_key=key;
  }
  if(local){
    profiles.local={base_url:$('setLocalUrl').value.trim(),
                    model:$('setLocalModel').value.trim()};
  }
  const body={profiles:profiles};
  if(state.settings)body.hybrid={mode:state.settingsMode};
  const tip=$('setTest');tip.className='';tip.textContent='正在保存…';
  $('setSave').disabled=true;
  try{
    const r=await fetch('/settings',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify(body)});
    const d=await r.json();
    if(!r.ok||d.error)throw new Error(d.error||'保存失败');
    state.settings=d;
    closeModal('setModal');
    note('已保存，下一条消息按新配置生效');
    await refreshHealth();
  }catch(err){tip.className='bad';tip.textContent='保存失败：'+err.message;}
  finally{$('setSave').disabled=false;}
}
async function testSettings(){
  const tip=$('setTest');tip.className='';tip.textContent='测试中…';
  const body={profile:'cloud',
              base_url:$('setCloudUrl').value.trim(),
              model:$('setCloudModel').value.trim(),
              api_key:$('setCloudKey').value.trim(),
              thinking:$('setCloudThink').checked};
  try{
    const r=await fetch('/settings/test',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify(body)});
    const d=await r.json();
    if(!r.ok||d.error)throw new Error(d.error||'测试失败');
    if(!d.ok)throw new Error(d.error||'连接失败');
    tip.className='ok';
    tip.textContent='连接成功 · '+d.model+' · '+d.ms+'ms'+
      (d.thinking_chars?' · 思考 '+d.thinking_chars+' 字':'');
  }catch(err){tip.className='bad';tip.textContent='连接失败：'+err.message;}
}
async function jumpToNode(node,role){
  if(state.busy||!state.current||!node)return;
  const seq=++state.seq;
  try{
    const r=await fetch('/sessions/'+encodeURIComponent(state.current)+'/cursor',{
      method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({node})});
    const d=await r.json();
    if(seq!==state.seq)return;
    if(!r.ok||d.error)throw new Error(d.error||'切换失败');
    state.messages=d.messages||[];state.tree=d.tree||state.tree;
    syncFind();
    closeModal('treeModal');revealNode(node,role);renderMessages(true);setTitle();
    focusQuestion(node,role);
  }catch(err){alert('切换分支失败：'+err.message);}
}
function focusQuestion(node,role){
  const box=$('thread');
  const user=box.querySelector('.msg.user[data-node="'+node+'"]');
  const answer=box.querySelector('.msg.assistant[data-ansnode="'+node+'"]');
  const row=(role==='assistant'?answer:user)||user||answer;
  if(!row)return;
  const target=row.querySelector('.bubble')||row;
  row.scrollIntoView({block:'center'});
  target.classList.add('q-hit');
  setTimeout(()=>target.classList.remove('q-hit'),1200);
}
// ── 对话内查找：数据先算命中，界面只负责标黄与滚动；窗口外的命中在跳转时扩窗
function findHits(q){
  const needle=q.toLowerCase(), out=[];
  if(!needle)return out;
  state.messages.forEach((m,i)=>{
    const text=String(m.text||'');if(!text)return;
    const low=text.toLowerCase();let at=low.indexOf(needle);
    while(at>=0){out.push({i:i,at:at});at=low.indexOf(needle,at+needle.length);}
  });
  return out;
}
function clearFindMarks(){
  $('thread').querySelectorAll('mark.find').forEach(mk=>{
    const p=mk.parentNode;if(!p)return;
    p.replaceChild(document.createTextNode(mk.textContent),mk);p.normalize();
  });
}
function markIn(root,needle){
  if(!needle)return;
  const walker=document.createTreeWalker(root,NodeFilter.SHOW_TEXT,null);
  const nodes=[];let node;
  while((node=walker.nextNode())){
    const text=node.nodeValue;if(!text||!text.trim())continue;
    const el=node.parentElement;
    if(el&&el.closest('button,mark,textarea,script,style,.q-foot'))continue;
    if(text.toLowerCase().indexOf(needle)>=0)nodes.push(node);
  }
  nodes.forEach(node=>{
    const text=node.nodeValue,low=text.toLowerCase(),frag=document.createDocumentFragment();
    let at=0,hit;
    while((hit=low.indexOf(needle,at))>=0){
      if(hit>at)frag.appendChild(document.createTextNode(text.slice(at,hit)));
      const mk=document.createElement('mark');mk.className='find';
      mk.textContent=text.slice(hit,hit+needle.length);
      frag.appendChild(mk);at=hit+needle.length;
    }
    if(at<text.length)frag.appendChild(document.createTextNode(text.slice(at)));
    if(node.parentNode)node.parentNode.replaceChild(frag,node);
  });
}
function paintFind(){
  const f=state.find, hits=f.hits, thread=$('thread');
  clearFindMarks();
  $('findCount').textContent=(hits.length?f.cur+1:0)+'/'+hits.length;
  $('findInput').classList.toggle('none',!f.dirty&&!!f.q&&!hits.length);
  if(!f.q||!hits.length)return;
  const needle=f.q.toLowerCase(), start=winStart(), end=winEnd(), rows=thread.children, off=start>0?1:0;
  // 只标窗口内的行：命中总数按数据算，不必为了显示把整段历史塞进 DOM
  state.messages.slice(start,end).forEach((m,i)=>{
    if(m.pending)return;
    if(String(m.text||'').toLowerCase().indexOf(needle)<0)return;
    const row=rows[i+off];if(!row)return;
    const bubble=row.querySelector('.bubble');if(bubble)markIn(bubble,needle);
  });
  const cur=hits[Math.max(f.cur,0)];
  const row=rows[cur.i-start+off];if(!row)return;
  let k=0;
  for(let j=0;j<f.cur;j++)if(hits[j].i===cur.i)k++;
  const marks=row.querySelectorAll('mark.find');
  const mk=marks[k]||marks[marks.length-1];
  if(!mk)return;
  mk.classList.add('on');
  f.painted=true;
  // 只有主动换命中时才滚动，重新渲染（加载更早/更新）不该把视野拽回来
  if(f.scroll){f.scroll=false;mk.scrollIntoView({block:'center'});}
}
// 命中已在窗口内且已铺好标黄时，翻下一处只挪 .on 与视野，不重铺上千个 mark
function paintFindMove(){
  const f=state.find,h=f.hits[f.cur];if(!h)return false;
  const start=winStart(),rows=$('thread').children,off=start>0?1:0;
  const row=rows[h.i-start+off];if(!row)return false;
  let k=0;
  for(let j=0;j<f.cur;j++)if(f.hits[j].i===h.i)k++;
  const marks=row.querySelectorAll('mark.find');
  const mk=marks[k]||marks[marks.length-1];
  if(!mk)return false;
  const prev=$('thread').querySelector('mark.find.on');if(prev)prev.classList.remove('on');
  mk.classList.add('on');
  $('findCount').textContent=(f.cur+1)+'/'+f.hits.length;
  mk.scrollIntoView({block:'center'});
  return true;
}
// 当前命中不在窗口里就把窗口挪到它前后几十条，别为了看一眼重绘整段历史
function jumpFindCur(){
  const f=state.find,h=f.hits[f.cur];
  if(!h)return;
  const start=winStart(), end=winEnd();
  f.scroll=true;
  if(h.i<start||h.i>=end){
    state.winFrom=Math.max(0,h.i-4);
    state.winEnd=Math.min(state.messages.length,h.i+40);
    renderMessages(true);
  }else paintFind();
}
// 切换分支、删除问答后消息换了，命中表跟着重算，序号越界就归零
function syncFind(){
  const f=state.find;
  if(!f.open||f.dirty||!f.q)return;
  f.hits=findHits(f.q);
  if(f.cur>=f.hits.length)f.cur=f.hits.length?0:-1;
}
// 打字阶段只标记「还没查」，不跳也不标黄，避免边打边跳
function markFindDirty(){
  const f=state.find;
  f.dirty=true;f.hits=[];f.cur=-1;f.painted=false;
  clearFindMarks();
  $('findCount').textContent='0/0';
  $('findInput').classList.remove('none');
}
// step 正负表示相对当前命中前后翻；查询词变了就先定位到离视野最近的一条
function findNav(step){
  const f=state.find, q=$('findInput').value.trim();
  if(!q){
    f.q='';f.dirty=false;f.hits=[];f.cur=-1;f.painted=false;
    clearFindMarks();$('findCount').textContent='0/0';
    $('findInput').classList.remove('none');return;
  }
  if(f.dirty||q!==f.q){
    f.q=q;f.hits=findHits(q);f.dirty=false;f.cur=-1;
    if(!f.hits.length){paintFind();return;}
    // 从离当前视图最近的一条开始，往上翻更符合「刚说过什么」的直觉
    const end=winEnd();
    let pick=f.hits.length-1;
    while(pick>0&&f.hits[pick].i>=end)pick--;
    f.cur=pick;
    jumpFindCur();return;
  }
  if(!step||!f.hits.length)return;
  const n=f.hits.length;
  f.cur=((f.cur<0?0:f.cur)+step+n)%n;
  if(f.painted&&paintFindMove())return;
  jumpFindCur();
}
function openFind(){
  state.find.open=true;$('findbar').classList.add('show');
  const input=$('findInput');
  // 选中一段文字再按 Ctrl+F，直接拿它当查询词
  const sel=String((window.getSelection&&window.getSelection().toString())||'').trim();
  if(sel&&sel.length<=60&&sel.indexOf('\n')<0&&!input.value){input.value=sel;markFindDirty();}
  input.focus();input.select();
}
function closeFind(){
  const f=state.find;
  f.open=false;f.q='';f.hits=[];f.cur=-1;f.scroll=false;f.dirty=false;f.painted=false;
  $('findbar').classList.remove('show');
  $('findInput').value='';$('findInput').classList.remove('none');
  $('findCount').textContent='0/0';
  clearFindMarks();
}
function beginEdit(node){
  const m=state.messages.find(x=>x.role==='user'&&x.node===node);
  if(!m){alert('找不到这条问题');return;}
  state.editNode=node;$('editText').value=m.text;$('editModal').classList.add('show');$('editText').focus();
}
async function submitEdit(){
  const text=$('editText').value.trim(), fork=state.editNode;
  if(!text||!fork)return;
  closeModal('editModal');state.editNode=null;
  await send(text,{fork});
}
async function deleteTurn(node){
  if(state.busy)return;
  if(!confirm('删除这条问题、AI 回复及其下游分支？此操作不可恢复。'))return;
  const seq=++state.seq;
  try{
    const tip=tipNode();
    const r=await fetch('/sessions/'+encodeURIComponent(state.current)+'/nodes/'+encodeURIComponent(node)+
      (tip?'?tip='+encodeURIComponent(tip):''),{method:'DELETE'});
    const d=await r.json();
    if(seq!==state.seq)return;
    if(!r.ok||d.error)throw new Error(d.error||'删除失败');
    state.messages=d.messages||[];state.tree=d.tree||null;syncFind();
    await loadSessions();await loadTree();renderMessages();setTitle();
  }catch(err){alert('删除失败：'+err.message);}
}
async function ensureSession(){
  if(state.current)return state.current;
  const r=await fetch('/sessions',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});
  const d=await r.json();
  if(!r.ok||d.error)throw new Error(d.error||'建会话失败');
  state.current=d.session;setHash(state.current);await loadSessions();return state.current;
}
function autoGrow(){const el=$('q');el.style.height='auto';el.style.height=Math.min(el.scrollHeight,160)+'px';}
function setSendState(busy){
  const b=$('send');
  b.disabled=false;
  b.classList.toggle('stop',busy);
  b.textContent=busy?'■':'➤';
  b.title=busy?'停止生成':'发送（Enter）';
}
async function stopGenerating(){
  const sid=state.current;
  if(!sid)return;
  $('status').textContent='正在停止…';
  try{
    await fetch('/sessions/'+encodeURIComponent(sid)+'/stop',
      {method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});
  }catch(e){}
  if(state.ctrl)state.ctrl.abort();
}
async function settleStop(sid,pending,text){
  const partial=pending.text||'';
  for(let i=0;i<10;i++){
    await new Promise(r=>setTimeout(r,400));
    try{
      const r=await fetch('/sessions/'+encodeURIComponent(sid)+'/messages');
      const d=await r.json();
      if(!r.ok||!d.messages)continue;
      const msgs=d.messages||[];
      let lastUser=-1;msgs.forEach((m,idx)=>{if(m.role==='user')lastUser=idx;});
      const answered=lastUser>=0&&msgs.slice(lastUser+1).some(m=>m.role==='assistant');
      const sameQ=lastUser>=0&&(msgs[lastUser].text||'').trim()===text.trim();
      if(answered||!sameQ){
        // 已落盘，或本轮节点已被服务端清掉：以服务端为准
        state.messages=msgs;await loadTree();renderMessages(false);scrollBottom(true);return;
      }
    }catch(e){}
  }
  // 服务端迟迟未落盘：本地保留已生成文本，节点信息等下次进会话再同步
  const i=state.messages.indexOf(pending);
  if(i>=0)state.messages.splice(i,1);
  if(partial){
    state.messages.push({role:'assistant',text:partial,stopped:true});
  }else{
    let at=-1;
    state.messages.forEach((x,idx)=>{if(x.role==='user'&&(x.text||'').trim()===text.trim())at=idx;});
    if(at>=0)state.messages.splice(at,1);
  }
  renderMessages(false);
}
async function send(override,opts){
  if(state.busy)return;
  opts=opts||{};
  const text=String(override==null?$('q').value:override).trim();
  if(!text)return;
  if(override==null){$('q').value='';autoGrow();}
  state.messages=state.messages.filter(m=>!m.error);state.retry=null;
  state.busy=true;setSendState(true);
  const ctrl=new AbortController();state.ctrl=ctrl;
  $('status').textContent='思考中…';
  const started=Date.now();
  const pending={role:'assistant',text:'',thinking:'',pending:true,started};
  const userMsg={role:'user',text};
  if(opts.fork){
    const at=state.messages.findIndex(m=>m.role==='user'&&m.node===opts.fork);
    if(at>=0)state.messages=state.messages.slice(0,at);
  }else if(opts.parent){
    const at=state.messages.findIndex(m=>m.role==='user'&&m.node===opts.parent);
    if(at>=0)state.messages=state.messages.slice(0,at+1);
  }
  state.messages.push(userMsg);state.messages.push(pending);
  state.winFrom=null;state.winEnd=null;renderMessages(false);
  const tick=setInterval(()=>{
    const el=$('thread').querySelector('.thinking .secs');
    if(el)el.textContent=((Date.now()-started)/1000).toFixed(0)+'s';
  },1000);
  let sid=state.current;
  // 视图里显示的是哪条链，就把新问题接到哪条链上；主分支只决定打开时落在哪，不改变追加位置
  const tip=tipNode()||((state.tree&&state.tree.active)||null);
  try{
    sid=await ensureSession();
    const body={message:text,session:sid};
    if(opts.fork)body.fork=opts.fork;
    else if(opts.parent)body.parent=opts.parent;
    else if(tip)body.parent=tip;
    const r=await fetch('/inbox/stream',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body),signal:ctrl.signal});
    if(!r.ok){let d={};try{d=await r.json();}catch(e){}
      throw new Error(d.error||('HTTP '+r.status));}
    if(!r.body)throw new Error('浏览器不支持流式读取');
    const reader=r.body.getReader(), decoder=new TextDecoder();
    let buffer='', final=null, failed=null;
    const handle=(event,data)=>{
      if(event==='delta'){pending.text+=data.delta||'';paintPending();scrollBottom(false);}
      else if(event==='thinking'){pending.thinking+=data.delta||'';paintPending();}
      else if(event==='preprocess'){$('status').textContent=data.route==='local'?'本地处理…':'云端处理…';}
      else if(event==='tool_start'){$('status').textContent='调用 '+(data.name||'工具')+'…';}
      else if(event==='done')final=data;
      else if(event==='error')failed=data.error||'生成失败';
    };
    while(true){
      const chunk=await reader.read();
      if(chunk.done)break;
      buffer+=decoder.decode(chunk.value,{stream:true});
      let at;
      while((at=buffer.indexOf('\n\n'))>=0){
        const block=buffer.slice(0,at);buffer=buffer.slice(at+2);
        let event='',data='';
        block.split('\n').forEach(line=>{
          if(line.startsWith('event:'))event=line.slice(6).trim();
          else if(line.startsWith('data:'))data+=line.slice(5).trim();
        });
        if(!event||!data)continue;
        try{handle(event,JSON.parse(data));}catch(e){}
      }
    }
    if(failed)throw new Error(failed);
    if(!final)throw new Error('流式响应提前结束');
    const index=state.messages.indexOf(pending);
    if(index>=0)state.messages.splice(index,1);
    if(final.node){userMsg.node=final.node;userMsg.parent=final.parent||opts.parent||null;}
    state.messages.push({role:'assistant',text:final.reply||'',lenses:final.lenses||[],
                         route:final.route,worker:final.worker,model:final.model,
                         thinking:final.thinking||'',saved_chars:final.saved_chars||0,
                         node:final.node||null,parent:final.parent||opts.parent||null,
                         mode:final.mode,stopped:!!final.stopped});
    await loadSessions();await loadTree();renderMessages(false);scrollBottom(true);
  }catch(err){
    const index=state.messages.indexOf(pending);
    if(index>=0)state.messages.splice(index,1);
    if(err&&err.name==='AbortError'){
      await settleStop(sid,pending,text);
    }else{
      const at=state.messages.indexOf(userMsg);
      if(at>=0)state.messages.splice(at,1);
      state.retry={text,opts};
      state.messages.push({role:'assistant',error:(err&&err.message)||String(err)});
      renderMessages(false);
    }
  }finally{
    clearInterval(tick);$('status').textContent='';
    state.busy=false;state.ctrl=null;setSendState(false);$('q').focus();
  }
}

$('send').onclick=()=>{if(state.busy)return stopGenerating();send();};
function regenerate(node){
  if(state.busy)return;
  const at=state.messages.findIndex(m=>m.role==='user'&&m.node===node);
  if(at<0){alert('找不到这条问题');return;}
  send(state.messages[at].text,{fork:node});
}
function retryLast(){
  if(state.busy||!state.retry)return;
  const last=state.retry;
  state.messages=state.messages.filter(m=>!m.error);
  send(last.text,last.opts);
}
$('findBtn').onclick=openFind;
$('findClose').onclick=()=>{closeFind();$('q').focus();};
$('findPrev').onclick=()=>findNav(-1);
$('findNext').onclick=()=>findNav(1);
$('findInput').addEventListener('input',markFindDirty);
$('findInput').addEventListener('keydown',e=>{
  if(e.key==='Enter'){e.preventDefault();findNav(e.shiftKey?-1:1);}
  else if(e.key==='ArrowDown'){e.preventDefault();findNav(1);}
  else if(e.key==='ArrowUp'){e.preventDefault();findNav(-1);}
  else if(e.key==='Escape'){e.preventDefault();closeFind();$('q').focus();}
  e.stopPropagation();
});
$('branchBtn').onclick=openTree;
$('zoomIn').onclick=()=>treeZoom((state.zoom||1)*1.25);
$('zoomOut').onclick=()=>treeZoom((state.zoom||1)/1.25);
$('zoomPct').onclick=()=>treeZoom(1);
$('zoomFit').onclick=treeFit;
$('treeBox').addEventListener('wheel',e=>{
  if(!e.ctrlKey)return;
  e.preventDefault();
  const r=$('treeBox').getBoundingClientRect();
  treeZoom((state.zoom||1)*(e.deltaY<0?1.12:1/1.12),e.clientX-r.left,e.clientY-r.top);
},{passive:false});
// 空白处拖动平移：位移过阈值才算拖动，松手后吞掉这次 click，免得误触跳转
let treePan=null;
function endTreePan(){
  if(!treePan)return;
  const moved=treePan.moved;
  treePan=null;$('treeBox').classList.remove('panning');
  if(moved){state.treeDragMoved=true;setTimeout(()=>{state.treeDragMoved=false;},260);}
}
$('treeBox').addEventListener('pointerdown',e=>{
  if(e.button!==0||e.target.closest('[data-node]'))return;
  const box=$('treeBox');
  treePan={x:e.clientX,y:e.clientY,left:box.scrollLeft,top:box.scrollTop,moved:false};
  try{box.setPointerCapture(e.pointerId);}catch(_){}
});
$('treeBox').addEventListener('pointermove',e=>{
  if(!treePan)return;
  const box=$('treeBox'),dx=e.clientX-treePan.x,dy=e.clientY-treePan.y;
  if(!treePan.moved&&Math.abs(dx)+Math.abs(dy)<4)return;
  treePan.moved=true;box.classList.add('panning');
  box.scrollLeft=treePan.left-dx;box.scrollTop=treePan.top-dy;
});
$('treeBox').addEventListener('pointerup',endTreePan);
$('treeBox').addEventListener('pointercancel',endTreePan);
$('treeBox').onclick=e=>{
  if(state.treeDragMoved)return;
  const b=e.target.closest('[data-node]');
  if(b&&b.dataset.node)jumpToNode(b.dataset.node);
};
$('editSubmit').onclick=submitEdit;
$('new').onclick=()=>newChat(true);
$('hide').onclick=()=>$('side').classList.add('collapsed');
$('toggle').onclick=()=>$('side').classList.toggle('collapsed');
$('search').oninput=onSearchInput;
$('search').addEventListener('keydown',e=>{
  if(e.key!=='Enter')return;
  e.preventDefault();
  const first=state.hits[0];
  if(first)openHit(first.session,first.node,first.role);
});
$('hits').onclick=e=>{
  const hit=e.target.closest('.hit');if(!hit)return;
  openHit(hit.dataset.session,hit.dataset.node,hit.dataset.role);
};
$('backup').onclick=()=>download('/export');
$('setMode').onclick=e=>{
  const b=e.target.closest('button[data-mode]');if(!b||b.disabled)return;
  state.settingsMode=b.dataset.mode;paintSettingsMode();
};
$('sessions').onclick=e=>{
  const action=e.target.closest('.menu button');
  if(action){
    e.stopPropagation();closeMenus();
    const act=action.dataset.act, id=action.dataset.id;
    if(act==='rename')beginRename(id);
    else if(act==='export-md')download('/sessions/'+encodeURIComponent(id)+'/export?format=md');
    else if(act==='export-json')download('/sessions/'+encodeURIComponent(id)+'/export?format=json');
    else deleteSession(id);
    return;
  }
  const more=e.target.closest('.more');
  if(more){
    e.stopPropagation();
    const row=more.closest('.session-row'), open=row.classList.contains('open');
    closeMenus();if(!open)row.classList.add('open');
    return;
  }
  const b=e.target.closest('.session');
  if(b){closeMenus();select(b.dataset.id,true);}
};
document.addEventListener('click',e=>{
  if(!e.target.closest('.session-row'))closeMenus();
  if(!e.target.closest('.msg-menu')&&!e.target.classList.contains('msg-more'))
    document.querySelectorAll('.msg-menu.open').forEach(m=>m.classList.remove('open'));
  const close=e.target.closest('[data-close]');
  if(close)closeModal(close.dataset.close);
});
$('q').addEventListener('input',autoGrow);
$('q').addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.isComposing){e.preventDefault();send();}});
$('scroll').addEventListener('scroll',()=>{
  const el=$('scroll');
  $('toLatest').classList.toggle('show',el.scrollHeight-el.scrollTop-el.clientHeight>180);
});
$('toLatest').onclick=()=>scrollBottom(true);
$('setBtn').onclick=openSettings;
$('setSave').onclick=saveSettings;
$('setTestBtn').onclick=testSettings;
document.querySelectorAll('#setTheme button').forEach(b=>{
  b.onclick=()=>setTheme(b.dataset.theme);
});
paintTheme();
$('thread').addEventListener('click',e=>{
  const regen=e.target.closest('.regen');
  if(regen){e.stopPropagation();regenerate(regen.dataset.node);return;}
  const again=e.target.closest('.retry');
  if(again){e.stopPropagation();retryLast();return;}
  const nav=e.target.closest('.branch-nav button');
  if(nav){
    e.stopPropagation();
    const holder=nav.closest('.branch-nav');
    jumpToNode(nav.dataset.act==='prev'?holder.dataset.prev:holder.dataset.next);
    return;
  }
  const action=e.target.closest('.msg-menu button');
  if(action){
    e.stopPropagation();
    const node=action.closest('.msg-menu').dataset.node;
    document.querySelectorAll('.msg-menu.open').forEach(m=>m.classList.remove('open'));
    if(action.dataset.act==='edit')beginEdit(node);
    else if(action.dataset.act==='main')setMain(node);
    else deleteTurn(node);
    return;
  }
  const more=e.target.closest('.msg-more');
  if(more){
    e.stopPropagation();
    const menu=more.parentElement.querySelector('.msg-menu');
    const open=menu.classList.contains('open');
    document.querySelectorAll('.msg-menu.open').forEach(m=>m.classList.remove('open'));
    if(!open)menu.classList.add('open');
    return;
  }
  if(!e.target.classList.contains('copy'))return;
  const code=e.target.closest('pre').querySelector('code').innerText;
  navigator.clipboard.writeText(code).then(()=>{
    e.target.textContent='已复制';setTimeout(()=>{e.target.textContent='复制';},1400);
  }).catch(()=>{e.target.textContent='复制失败';});
});
window.addEventListener('popstate',openFromHash);
// Ctrl+F 只在对话已打开时接管，其余情况仍交给浏览器
document.addEventListener('keydown',e=>{
  if((e.ctrlKey||e.metaKey)&&!e.altKey&&!e.shiftKey&&e.key.toLowerCase()==='f'){
    if(!state.current||!state.messages.length||document.querySelector('.modal.show'))return;
    e.preventDefault();openFind();return;
  }
  if(e.key==='Escape'&&state.find.open&&!document.querySelector('.modal.show'))closeFind();
},true);

function applyHealth(health){
  if(!health)return;
  if(health.profile){
    // 顶栏标签跟当前方式走：仅本地时别显示云端模型名
    const pre=health.mode==='local'?'仅本地 · ':(health.mode==='hybrid'||health.hybrid?'本地路由 → ':'');
    $('model').textContent=pre+(health.profile.model||'');
  }
}
async function refreshHealth(){
  applyHealth(await fetch('/health').then(r=>r.json()).catch(()=>null));
}

(async()=>{
  const healthP=fetch('/health').then(r=>r.json()).catch(()=>null);
  const namesP=fetch('/lens-names').then(r=>r.json()).catch(()=>null);
  const id=readHash();
  // 会话列表与历史同时开始拉取，健康检查和镜头名不挡首屏
  const chatP=id?select(id,false):Promise.resolve(newChat(false));
  const listP=loadSessions();
  const [health,names]=await Promise.all([healthP,namesP]);
  applyHealth(health);
  // 新用户第一次打开：端点还没配好，直接把设置面板弹出来
  if(health&&health.needs_setup)openSettings();
  if(names){
    state.names=names.names||{};
    if(state.messages.some(m=>(m.lenses||[]).length))renderMessages(true);
  }
  await Promise.all([listP,chatP]);
})();
