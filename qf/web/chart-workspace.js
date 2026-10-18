// 固定四格的协调器：不持有 SDK 对象，不处理凭证。
(() => {
  'use strict';
  function create(root,options){
    const S=QfChartState;
    let config=S.clone(options.config),accepted=S.clone(config),state={catalog:[],rows:[],favorites:[]},alive=true,visible=true;
    let expanded=null,workspaceExpanded=false,viewKey='',pending=null,sending=false,drag=null;
    const panes=new Map(),revisions=new Map(config.panes.map(p=>[p.id,1]));
    const drawingBook=QfDrawingBook.create();
    root.innerHTML=`<div class="section-title"><div><h2>行情图工作区</h2><span id="active-pane-label"></span></div>
      <div class="chart-actions"><label>布局 <select id="chart-layout"><option value="single">单图</option><option value="columns">左右双图</option><option value="rows">上下双图</option><option value="quad">四宫格</option></select></label>
      <label><input id="link-products" type="checkbox"> 品种联动</label><button id="expand-workspace">放大工作区</button></div></div>
      <p id="workspace-save-note" class="chart-units"></p><div class="chart-grid-scroll"><div class="chart-grid"></div></div>`;
    const grid=root.querySelector('.chart-grid'),scroll=root.querySelector('.chart-grid-scroll');
    const column=document.createElement('div'),row=document.createElement('div');
    for(const [bar,axis] of [[column,'column'],[row,'row']]){bar.className='chart-split split-'+axis;bar.tabIndex=0;bar.role='separator';
      bar.setAttribute('aria-label',axis==='column'?'调整左右分屏比例':'调整上下分屏比例');
      bar.setAttribute('aria-orientation',axis==='column'?'vertical':'horizontal');
      bar.onpointerdown=e=>{if(e.button!==0)return;e.preventDefault();endDrag();
        drag={axis,bar,id:e.pointerId};bar.setPointerCapture(e.pointerId);root.classList.add('resizing-charts');};
      bar.onkeydown=e=>{if(!['ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].includes(e.key))return;
        e.preventDefault();action({type:'split',axis,value:config.split[axis]+(['ArrowRight','ArrowDown'].includes(e.key)?.02:-.02)});};
      grid.append(bar);
    }
    function endDrag(){if(!drag)return;try{drag.bar.releasePointerCapture(drag.id)}catch(_){}drag=null;root.classList.remove('resizing-charts');}
    function move(e){if(!drag)return;if(!(e.buttons&1)){endDrag();return;}
      const box=grid.getBoundingClientRect(),axis=drag.axis;
      const value=axis==='column'?(e.clientX-box.left)/box.width:(e.clientY-box.top)/box.height;
      config=S.reduce(config,{type:'split',axis,value});render();}
    function finish(){if(drag){endDrag();save();}}
    function save(){if(!alive)return;const snapshot=S.clone(config);options.onConfig(snapshot).then(result=>{
      if(alive)root.querySelector('#workspace-save-note').textContent=result.ok?'布局已保存':result.reason||'布局未保存';
    }).catch(()=>{if(alive)root.querySelector('#workspace-save-note').textContent='布局未保存，请稍后重试。';});}
    function action(a){if(!alive)return;const before=config;config=S.reduce(config,a);
      for(const p of config.panes){const old=before.panes.find(x=>x.id===p.id);
        if(JSON.stringify(p)!==JSON.stringify(old))revisions.set(p.id,revisions.get(p.id)+1);}
      options.onSelection?.(config.panes.find(p=>p.id===config.active)?.continuous);
      render();sendView();if(!state.connected||['activate','link','split','collapse-account'].includes(a.type))save();
    }
    function requests(){return S.visibleIds(config).map(id=>{const p=config.panes.find(p=>p.id===id);
      return {...p,continuous:state.catalog.some(x=>x.continuous===p.continuous)?p.continuous:null,revision:revisions.get(id)};});}
    function sendView(){if(!alive||!visible||!state.catalog.length||!['connecting','ready','waiting_data','disconnected'].includes(state.status))return;
      const req=requests(),key=JSON.stringify([state.visible_symbols,req]);if(key===viewKey)return;viewKey=key;
      pending={key,req,snapshot:S.clone(config)};drain();}
    async function drain(){if(sending)return;sending=true;
      try{while(pending&&alive){const job=pending;pending=null;const result=await options.onView(job.req);
        if(!alive)return;
        if(result.ok){if(job.key===viewKey){accepted=job.snapshot;save();}}
        else if(job.key===viewKey){options.onNotice?.(result.reason);config=S.clone(accepted);viewKey='';render();}
      }}catch(_){viewKey='';options.onNotice?.('图表设置未应用，请检查连接。');}finally{sending=false;}}
    function activate(id){if(id!==config.active)action({type:'activate',id});}
    function choose(id,symbol,mode){activate(id);if(mode)config=S.reduce(config,{type:'source',value:mode});action({type:'choose',symbol});}
    function expand(id){expanded=expanded===id?null:id;render();}
    function escape(){if(expanded){expanded=null;render();}else if(workspaceExpanded){workspaceExpanded=false;render();}}
    function drawing(id,data){
      if(data.kind==='qf-drawings-conflict'){options.onNotice?.('其他分屏已更新画线，未提交的冲突编辑已取消。');return;}
      const result=data.kind==='qf-drawings-request'?drawingBook.read(data.symbol):data.kind==='qf-drawings-undo'?
        drawingBook.undo(data.symbol,data.version):drawingBook.commit(data.symbol,data.version,data.drawings);
      if(!result.ok)options.onNotice?.('画线更新未应用：版本冲突或数量/格式超限，已保留最新结果。');
      for(const [target,p] of panes)if(target===id||(data.kind!=='qf-drawings-request'&&result.ok&&p.inspect().state?.symbol===data.symbol))
        p.send({kind:'qf-drawings-state',symbol:data.symbol,...result,source_pane:data.kind==='qf-drawings-request'?null:id});
    }
    function render(){if(!alive)return;
      const ids=visible?S.visibleIds(config):[];
      for(const [id,p] of panes)if(!ids.includes(id)){p.dispose();panes.delete(id);}
      for(const id of ids){if(!panes.has(id)){const node=document.createElement('section');grid.append(node);
          panes.set(id,QfChartPane.create(node,{id,onActivate:activate,onChoose:choose,
            onSource:(id,value)=>{activate(id);action({type:'source',value});},
            onPeriod:(id,value)=>{activate(id);action({type:'period',value});},onExpand:expand,
            onEscape:escape,onFavorite:options.onFavorite,onState:options.onState,onDrawing:drawing}));}
        const p=config.panes.find(p=>p.id===id),request=requests().find(p=>p.id===id);
        const runtime=state.panes?.find(p=>p.id===id&&p.revision===request.revision&&p.continuous===request.continuous&&p.mode===request.mode&&p.period===request.period);
        panes.get(id).update({...state,config:p,request,runtime,active:config.active===id});
        panes.get(id).setExpanded(expanded===id);
        const node=grid.querySelector('[data-pane="'+id+'"]'),index=ids.indexOf(id);
        node.style.gridColumn=config.layout==='rows'?'1':String(config.layout==='single'?1:index%2+1);
        node.style.gridRow=config.layout==='columns'||config.layout==='single'?'1':String(config.layout==='rows'?index+1:Math.floor(index/2)+1);
        node.hidden=!!expanded&&expanded!==id;
      }
      root.dataset.layout=config.layout;grid.dataset.layout=config.layout;
      const twoColumns=['columns','quad'].includes(config.layout),twoRows=['rows','quad'].includes(config.layout);
      root.classList.toggle('workspace-expanded',workspaceExpanded);
      const width=Math.max(twoColumns?852:420,scroll.clientWidth-10),minimum=twoRows?1052:520;
      const height=workspaceExpanded?Math.max(minimum,scroll.clientHeight-10):twoRows?1100:560;
      const firstColumn=Math.max(420,Math.min(width-432,(width-12)*config.split.column));
      const firstRow=Math.max(520,Math.min(height-532,(height-12)*config.split.row));
      grid.style.width=width+'px';grid.style.height=height+'px';
      grid.style.gridTemplateColumns=twoColumns?`${firstColumn}px minmax(420px,1fr)`:'minmax(420px,1fr)';
      grid.style.gridTemplateRows=twoRows?`${firstRow}px minmax(520px,1fr)`:'minmax(520px,1fr)';
      column.hidden=!twoColumns||!!expanded;row.hidden=!twoRows||!!expanded;
      column.style.left=(firstColumn+6)+'px';row.style.top=(firstRow+6)+'px';
      root.querySelector('#chart-layout').value=config.layout;root.querySelector('#link-products').checked=config.linked;
      root.querySelector('#active-pane-label').textContent='当前操作：'+config.active.replace('pane-','图 ')+' · 点击图表切换活动格';
      root.classList.toggle('workspace-expanded',workspaceExpanded);
      root.querySelector('#expand-workspace').textContent=workspaceExpanded?'还原工作区（Esc）':'放大工作区';
      document.body.classList.toggle('chart-expanded',workspaceExpanded||!!expanded);
    }
    root.querySelector('#chart-layout').onchange=e=>{finish();expanded=null;action({type:'layout',value:e.target.value});};
    root.querySelector('#link-products').onchange=e=>action({type:'link',value:e.target.checked});
    root.querySelector('#expand-workspace').onclick=()=>{workspaceExpanded=!workspaceExpanded;render();};
    function keydown(e){if(e.key==='Escape')escape();}
    addEventListener('pointermove',move);addEventListener('pointerup',finish);addEventListener('pointercancel',finish);addEventListener('blur',finish);addEventListener('keydown',keydown);addEventListener('resize',render);
    render();
    return {update(next){state=next;if(!alive)return;
        if(state.catalog.length){const active=config.panes.find(p=>p.id===config.active);
          if(!active.continuous){const symbol=state.selected||state.catalog.find(p=>p.product==='rb')?.continuous||state.catalog[0].continuous;
            config=S.reduce(config,{type:'choose',symbol});for(const id of S.visibleIds(config)){const p=config.panes.find(p=>p.id===id);if(!p.continuous)p.continuous=symbol;}}}
        render();sendView();},choose(symbol){action({type:'choose',symbol});},getConfig:()=>S.clone(config),
      setVisible(value){visible=value;finish();render();viewKey='';sendView();},
      inspect:()=>({config:S.clone(config),panes:Object.fromEntries([...panes].map(([id,p])=>[id,p.inspect()]))}),
      dispose(){if(!alive)return;finish();alive=false;pending=null;for(const p of panes.values())p.dispose();panes.clear();
        removeEventListener('pointermove',move);removeEventListener('pointerup',finish);removeEventListener('pointercancel',finish);removeEventListener('blur',finish);removeEventListener('keydown',keydown);removeEventListener('resize',render);
        document.body.classList.remove('chart-expanded');}};
  }
  window.QfChartWorkspace={create};
})();
