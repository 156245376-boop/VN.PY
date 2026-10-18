// 固定四格的协调器：不持有 SDK 对象，不处理凭证。
(() => {
  'use strict';
  function create(root,options){
    const S=QfChartState;
    let config=S.clone(options.config),accepted=S.clone(config),state={catalog:[],rows:[],favorites:[]},alive=true,visible=true;
    let expanded=null,workspaceExpanded=false,viewKey='',pending=null,sending=false,drag=null;
    let viewPromise=null,regularHeight=null,expandedHeight=null;
    const panes=new Map(),revisions=new Map(config.panes.map(p=>[p.id,1]));
    let indicators=null,indicatorPanel=null,indicatorConfig=options.indicators?.config;
    if(options.indicators){
      const node=document.createElement('section');document.body.append(node);
      function changeIndicator(a){indicatorConfig=QfIndicatorState.reduce(indicatorConfig,a);indicators.configure(a.pane,indicatorConfig.panes[a.pane]);indicatorPanel.open(a.pane,indicatorConfig.panes[a.pane]);}
      indicatorPanel=QfIndicatorPanel.create(node,{onChange:changeIndicator,symbol:id=>panes.get(id)?.indicatorContext()?.identity.symbol,
        onSelectRange:(id,item)=>indicators.command(id,'begin',item),onLocateRange:(id,item)=>indicators.command(id,'locate',item)});
      indicators=QfIndicatorController.create({config:indicatorConfig,getPane:id=>panes.get(id)?.indicatorContext(),
        submit:options.onIndicatorSubmit,poll:options.onIndicatorPoll,save:options.onIndicatorSave,onNotice:options.onNotice,
        onRange(id,data){const item=indicatorConfig.panes[id]?.items.find(i=>i.id===data.item_id);if(!item)return;
          const next=QfIndicatorState.clone(item);if(data.kind==='qf-indicator-height')next.height=data.height;else{next.params.mode='fixed';next.params.range=data.range;}
          indicatorConfig=QfIndicatorState.reduce(indicatorConfig,{type:'change',pane:id,item:next});indicators.configure(id,indicatorConfig.panes[id]);}});
      addEventListener('message',indicators.onMessage);
    }
    const drawingBook=QfDrawingBook.create();
    root.innerHTML=`<div class="section-title"><div><h2>行情图工作区</h2><span id="active-pane-label"></span></div>
      <div class="chart-actions"><label>布局 <select id="chart-layout"><option value="single">单图</option><option value="columns">左右双图</option><option value="rows">上下双图</option><option value="quad">四宫格</option></select></label>
      <label><input id="link-products" type="checkbox"> 品种联动</label><button id="expand-workspace">放大工作区</button></div></div>
      <p id="workspace-save-note" class="chart-units"></p><div class="chart-grid-scroll"><div class="chart-grid"></div></div>`;
    const grid=root.querySelector('.chart-grid'),scroll=root.querySelector('.chart-grid-scroll');
    const accountBar=document.createElement('div');accountBar.className='account-split';
    accountBar.tabIndex=0;accountBar.role='separator';
    accountBar.setAttribute('aria-label','上下拖动调整图表与账户区域高度');
    accountBar.setAttribute('aria-orientation','horizontal');
    accountBar.title='上下拖动调整图表与账户区域高度（也可用上下方向键）';root.append(accountBar);
    const accountRoot=document.createElement('section');root.append(accountRoot);
    const account=QfAccountView.create(accountRoot,{onCollapse:value=>{if(config.account_collapsed!==value)action({type:'collapse-account',value});}});
    const saves=QfLayoutSaves.create(options.onConfig,result=>{
      if(alive)root.querySelector('#workspace-save-note').textContent=result.ok?'布局已保存':result.reason||'布局未保存';
    });
    const column=document.createElement('div'),row=document.createElement('div');
    const accountSize=()=>Math.floor((workspaceExpanded?scroll:grid).getBoundingClientRect().height);
    function resizeAccount(height){
      if(workspaceExpanded)expandedHeight=height;else regularHeight=height;
      render();
    }
    accountBar.onpointerdown=e=>{if(e.button!==0)return;e.preventDefault();endDrag();
      drag={axis:'account',bar:accountBar,id:e.pointerId,y:e.clientY,height:accountSize()};
      accountBar.setPointerCapture(e.pointerId);root.classList.add('resizing-charts');};
    accountBar.onkeydown=e=>{if(!['ArrowUp','ArrowDown'].includes(e.key))return;
      e.preventDefault();resizeAccount(accountSize()+(e.key==='ArrowDown'?32:-32));};
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
      if(drag.axis==='account'){resizeAccount(drag.height+e.clientY-drag.y);return;}
      const box=grid.getBoundingClientRect(),axis=drag.axis;
      const value=axis==='column'?(e.clientX-box.left)/box.width:(e.clientY-box.top)/box.height;
      config=S.reduce(config,{type:'split',axis,value});render();}
    function finish(){if(drag){const accountDrag=drag.axis==='account';endDrag();if(!accountDrag)save();}}
    function save(){if(alive){root.querySelector('#workspace-save-note').textContent='正在保存布局…';saves.submit(config);}}
    function action(a){if(!alive)return;const before=config;config=S.reduce(config,a);
      for(const p of config.panes){const old=before.panes.find(x=>x.id===p.id);
        if(JSON.stringify(p)!==JSON.stringify(old))revisions.set(p.id,revisions.get(p.id)+1);}
      options.onSelection?.(config.panes.find(p=>p.id===config.active)?.continuous);
      render();sendView();if(!state.connected||['activate','link','split','collapse-account'].includes(a.type))save();
    }
    function requests(){return (visible?S.visibleIds(config):[]).map(id=>{const p=config.panes.find(p=>p.id===id);
      return {...p,continuous:state.catalog.some(x=>x.continuous===p.continuous)?p.continuous:null,revision:revisions.get(id)};});}
    function sendView(){if(!alive||!state.catalog.length||!['connecting','ready','waiting_data','disconnected'].includes(state.status))return;
      const req=requests(),key=JSON.stringify([state.generation,state.visible_symbols,req]);if(key===viewKey)return;viewKey=key;
      pending={key,req,snapshot:S.clone(config)};if(!sending)viewPromise=drain();}
    function rollback(){
      const previous=config,next=S.clone(accepted);
      for(const field of ['linked','split','account_collapsed'])next[field]=S.clone(previous[field]);
      if(S.visibleIds(next).includes(previous.active))next.active=previous.active;
      config=next;viewKey='';options.onSelection?.(config.panes.find(p=>p.id===config.active)?.continuous);
      render();save();
    }
    async function drain(){if(sending)return;sending=true;
      try{while(pending&&alive){const job=pending;pending=null;const result=await options.onView(job.req);
        if(!alive)return;
        if(result.ok){accepted=job.snapshot;if(job.key===viewKey)save();}
        else if(job.key===viewKey){options.onNotice?.(result.reason);rollback();}
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
            onIndicators:id=>indicatorPanel?.open(id,indicatorConfig.panes[id]),
            onIndicatorReady:id=>indicators?.invalidate(id),
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
      account.update(state.account,state.catalog);account.setCollapsed(config.account_collapsed);
      accountBar.hidden=config.account_collapsed||!!expanded||!visible;
      const sizedAccount=workspaceExpanded&&expandedHeight!==null&&!config.account_collapsed;
      root.classList.toggle('workspace-account-sized',sizedAccount);
      if(sizedAccount){
        // 先分配区域，再测量网格；账户区保留可访问高度，窄窗口在图表内部滚动。
        const room=root.getBoundingClientRect().bottom-scroll.getBoundingClientRect().top;
        expandedHeight=Math.max(180,Math.min(expandedHeight,Math.max(180,room-140)));
        scroll.style.flex=`0 0 ${Math.floor(expandedHeight)}px`;
      }else scroll.style.flex='';
      const rowMinimum=ids=>ids.some(id=>S.period(config.panes.find(p=>p.id===id))==='1d')?480:448;
      const topMin=rowMinimum(config.layout==='rows'?ids.slice(0,1):ids.slice(0,2));
      const bottomMin=rowMinimum(config.layout==='rows'?ids.slice(1,2):ids.slice(2,4));
      // clientWidth/Height 会将 DPI 下的小数尺寸取整。按真实边界向下取整，
      // 扣除已有滚动条，避免不到一像素的溢出反复触发横竖滚动条和重绘。
      const bounds=scroll.getBoundingClientRect();
      const availableWidth=Math.floor(bounds.width-scroll.offsetWidth+scroll.clientWidth)-10;
      const availableHeight=Math.floor(bounds.height-scroll.offsetHeight+scroll.clientHeight)-10;
      const width=Math.max(twoColumns?852:420,availableWidth),minimum=twoRows?topMin+bottomMin+12:Math.max(480,topMin);
      const height=workspaceExpanded?Math.max(minimum,availableHeight):Math.max(minimum,regularHeight??(twoRows?960:560));
      if(!workspaceExpanded&&regularHeight!==null)regularHeight=height;
      const firstColumn=Math.max(420,Math.min(width-432,(width-12)*config.split.column));
      const firstRow=Math.max(topMin,Math.min(height-12-bottomMin,(height-12)*config.split.row));
      grid.style.width=width+'px';grid.style.height=height+'px';grid.style.minHeight=minimum+'px';
      grid.style.gridTemplateColumns=twoColumns?`${firstColumn}px minmax(420px,1fr)`:'minmax(420px,1fr)';
      grid.style.gridTemplateRows=twoRows?`${firstRow}px minmax(${bottomMin}px,1fr)`:`minmax(${minimum}px,1fr)`;
      column.hidden=!twoColumns||!!expanded;row.hidden=!twoRows||!!expanded;
      column.style.left=(firstColumn+6)+'px';row.style.top=(firstRow+6)+'px';
      root.querySelector('#chart-layout').value=config.layout;root.querySelector('#link-products').checked=config.linked;
      root.querySelector('#active-pane-label').textContent='当前操作：'+config.active.replace('pane-','图 ')+' · 点击图表切换活动格';
      root.classList.toggle('workspace-expanded',workspaceExpanded);
      root.querySelector('#expand-workspace').textContent=workspaceExpanded?'还原工作区（Esc）':'放大工作区';
      document.body.classList.toggle('chart-expanded',workspaceExpanded||!!expanded);
      if(indicators){for(const id of ['pane-1','pane-2','pane-3','pane-4'])indicators.setVisible(id,ids.includes(id)&&(!expanded||expanded===id));indicators.sync();}
    }
    root.querySelector('#chart-layout').onchange=e=>{finish();expanded=null;action({type:'layout',value:e.target.value});};
    root.querySelector('#link-products').onchange=e=>action({type:'link',value:e.target.checked});
    root.querySelector('#expand-workspace').onclick=()=>{workspaceExpanded=!workspaceExpanded;render();};
    function keydown(e){if(e.key==='Escape')escape();}
    addEventListener('pointermove',move);addEventListener('pointerup',finish);addEventListener('pointercancel',finish);addEventListener('blur',finish);addEventListener('keydown',keydown);addEventListener('resize',render);
    async function flush(){if(viewPromise)await viewPromise;await Promise.all([saves.flush(),indicators?.flush()]);}
    render();
    return {update(next){state=next;if(!alive)return;
        if(state.catalog.length){const active=config.panes.find(p=>p.id===config.active);
          if(!active.continuous){const symbol=state.selected||state.catalog.find(p=>p.product==='rb')?.continuous||state.catalog[0].continuous;
            config=S.reduce(config,{type:'choose',symbol});for(const id of S.visibleIds(config)){const p=config.panes.find(p=>p.id===id);if(!p.continuous)p.continuous=symbol;}}}
        render();sendView();},choose(symbol){action({type:'choose',symbol});},getConfig:()=>S.clone(config),
      setVisible(value){visible=value;finish();if(!value){expanded=null;workspaceExpanded=false;}render();viewKey='';sendView();},
      flush,async prepareExit(){indicators?.quiesce();await flush();},
      inspect:()=>({config:S.clone(config),indicators:indicators?.getConfig(),panes:Object.fromEntries([...panes].map(([id,p])=>[id,p.inspect()]))}),
      dispose(){if(!alive)return;finish();alive=false;pending=null;for(const p of panes.values())p.dispose();panes.clear();
        if(indicators){removeEventListener('message',indicators.onMessage);indicators.dispose();indicatorPanel.dispose();}
        removeEventListener('pointermove',move);removeEventListener('pointerup',finish);removeEventListener('pointercancel',finish);removeEventListener('blur',finish);removeEventListener('keydown',keydown);removeEventListener('resize',render);
        document.body.classList.remove('chart-expanded');}};
  }
  window.QfChartWorkspace={create};
})();
