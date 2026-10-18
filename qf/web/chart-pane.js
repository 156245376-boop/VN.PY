// 单格视图只接收显示快照；原生子页不具有 Python 桥接。
(() => {
  'use strict';
  const periods={close:'分时','1m':'1分钟','5m':'5分钟','15m':'15分钟','30m':'30分钟','1h':'1小时','1d':'日线'};
  const issues={empty:'没有有效 K 线',invalid_bar:'存在无效 K 线',id_sequence:'编号不连续',time_order:'时间重复或倒序',long_gap:'历史日期存在超过一个月的间隔，需要核实'};
  function create(root,options){
    const id=options.id,labels=window.QfLabels;
    root.className='card chart-card chart-pane';root.dataset.pane=id;
    root.id='chart-card'+(id==='pane-1'?'':'-'+id);
    root.innerHTML=`<div class="section-title"><div><h2 data-role="chart-title"></h2><span data-role="chart-detail"></span></div>
      <div class="chart-actions"><button data-role="chart-favorite">☆ 添加自选</button><button data-role="expand-chart">放大 K 线</button></div></div>
      <div class="pane-selects"><label>品种<select data-role="product" aria-label="品种"></select></label>
      <label>来源<select data-role="chart-source"><option value="actual">当前主力合约</option><option value="continuous">主力连续历史</option></select></label>
      <label>周期<select data-role="period"><option value="">默认周期</option></select></label></div>
      <p class="chart-units" data-role="chart-units"></p><p class="chart-units history-note" data-role="history-note"></p>
      <div class="history-controls" data-role="history-controls" hidden><select data-role="history-year" aria-label="定位年份"></select><button data-role="history-latest">回到最新</button></div>
      <p class="chart-units history-summary" data-role="history-summary" role="status"></p>
      <div class="pane-frame"><div class="chart-loading" data-role="chart-loading" role="status"><strong data-role="loading-stage">等待连接</strong><progress data-role="chart-progress"></progress><span data-role="loading-time"></span></div>
      <iframe data-role="chart" title="天勤行情图" sandbox="allow-scripts allow-same-origin allow-forms" referrerpolicy="no-referrer"></iframe></div>`;
    const $=role=>root.querySelector('[data-role="'+role+'"]');
    // 稳定 ID 便于本机辅助功能定位；各格不共享元素。
    for(const e of root.querySelectorAll('[data-role]'))e.id=e.dataset.role+(id==='pane-1'?'':'-'+id);
    for(const [value,name] of Object.entries(periods))$('period').add(new Option(name,value));
    const frame=$('chart');let context=null,url='',reported=null,problem='',binding='',disposed=false,started=performance.now(),catalogKey='',lastSize='';
    function envelope(){return {pane_id:id,generation:context?.generation,revision:context?.request.revision}}
    function send(data){if(url&&!disposed)frame.contentWindow?.postMessage({...data,...envelope()},new URL(url).origin)}
    function post(command,year){send({kind:'qf-chart-command',command,year})}
    function bind(){if(!context?.runtime?.symbol||!url)return;
      send({kind:'qf-chart-labels',catalog:context.catalog,symbol:context.runtime.symbol,
        period:QfChartState.period(context.config),compact:true,width:frame.clientWidth,height:frame.clientHeight});}
    function update(next){
      if(disposed)return;
      const previous=context;context=next;
      const item=next.catalog.find(p=>p.continuous===next.config.continuous),quote=next.rows.find(p=>p.continuous===next.config.continuous);
      const symbol=next.runtime?.symbol;
      $('chart-title').textContent=id.replace('pane-','图 ')+(item?' · '+labels.productName(item):' · 选择品种');
      $('chart-detail').textContent=next.config.mode==='continuous'?'主力连续历史':symbol?labels.contractName(symbol,next.catalog):'当前主力等待核实';
      $('chart-detail').title=symbol||'';
      $('chart-units').textContent='价格：'+(quote?.price_unit||item?.price_unit||'单位待确认')+' · 成交/持仓：手 · 时间：北京时间';
      $('history-note').textContent=next.config.mode==='continuous'?'跨主力合约拼接，切换主力时可能出现价格跳变；可用范围以服务返回为准。':'当前主力合约：历史取决于该月份合约上市时间；跨年份可切换“主力连续历史”。';
      const key=JSON.stringify(next.catalog.map(p=>[p.continuous,p.name]));
      if(key!==catalogKey){catalogKey=key;$('product').replaceChildren(new Option('选择品种',''));
        for(const p of next.catalog)$('product').add(new Option(labels.productName(p)+' · '+labels.exchangeName(p.exchange),p.continuous));}
      $('product').value=next.config.continuous||'';$('chart-source').value=next.config.mode;
      $('period').value=next.config.period||'';
      $('period').options[0].textContent='默认（'+periods[QfChartState.period(next.config)]+'）';
      $('chart-favorite').textContent=next.favorites.includes(next.config.continuous)?'★ 取消自选':'☆ 添加自选';
      $('chart-favorite').disabled=!item||next.favoriteSaving;
      root.classList.toggle('active-pane',next.active);
      if(previous&&previous.generation!==next.generation){post('dispose');frame.src='about:blank';url='';binding='';reported=null;}
      if(['idle','stopped','failed','stopping'].includes(next.status)&&url){post('dispose');frame.src='about:blank';url='';binding='';reported=null;}
      if(next.chart_url&&next.chart_url!==url){url=next.chart_url;frame.src=url;binding='';reported=null;}
      const newBinding=JSON.stringify([next.generation,next.request.revision,symbol,QfChartState.period(next.config)]);
      if(newBinding!==binding){binding=newBinding;reported=null;problem='';started=performance.now();bind();}
      const size=frame.clientWidth+'|'+frame.clientHeight;
      if(size!==lastSize){lastSize=size;if(reported?.status==='ready')reported.status='loading';bind();}
      render();
    }
    function render(){if(!context)return;
      const runtime=context.runtime,missing=context.config.continuous&&!context.catalog.some(p=>p.continuous===context.config.continuous);
      const valid=reported?.status==='ready'&&reported.history?.valid_count>0;
      const bad=problem||runtime?.status==='unavailable'&&(runtime.reason||'当前合约 K 线未返回或读取失败。');
      frame.style.visibility=valid&&!bad?'visible':'hidden';
      $('chart-loading').hidden=!!valid&&!bad;
      $('expand-chart').disabled=!url;
      $('loading-stage').textContent=missing?'保存的品种不在当前目录，请重新选择。':bad||
        (context.connected?'等待本格 K 线数据和实际绘制':'等待连接行情服务');
      const loading=context.loading||{};
      if(loading.phase==='catalog'&&loading.total>0){$('chart-progress').max=loading.total;$('chart-progress').value=loading.done||0;
        $('loading-stage').textContent='读取品种目录（'+(loading.done||0)+' / '+loading.total+'）';}
      else $('chart-progress').removeAttribute('value');
      $('loading-time').textContent='已等待 '+Math.floor((performance.now()-started)/1000)+' 秒 · 剩余时间暂无法准确估计';
      root.dataset.light=!context.connected||reported?.md_connected===false?'red':valid&&!bad&&reported?.md_connected===true?'green':'yellow';
      const detail=context.config.mode==='continuous'?'主力连续历史':context.runtime?.symbol?
        labels.contractName(context.runtime.symbol,context.catalog):'当前主力等待核实';
      $('chart-detail').textContent=detail+' · '+(root.dataset.light==='green'?'图表行情已连接':root.dataset.light==='red'?'图表行情未连接':'图表连接待确认');
      const h=reported?.history,daily=QfChartState.period(context.config)==='1d';
      $('history-controls').hidden=!daily;
      $('history-year').disabled=!valid;$('history-latest').disabled=!valid;
      const years=Object.keys(h?.years||{}).filter(y=>/^\d{4}$/.test(y)).sort(),yearKey=years.join(',');
      if($('history-year').dataset.years!==yearKey){$('history-year').dataset.years=yearKey;$('history-year').replaceChildren(new Option('定位年份',''));
        for(const y of years)$('history-year').add(new Option(y+' 年',y));}
      $('history-summary').dataset.error=String(!!bad);
      $('history-summary').textContent=bad|| (h?.valid_count?'图中已加载：'+h.first+' 至 '+h.last+'，'+h.valid_count+' 根 K 线；当前可见：'+reported.visible?.first+' 至 '+reported.visible?.last+'（北京时间）。':'');
    }
    function message(event){
      if(disposed||!context||!url||event.source!==frame.contentWindow||event.origin!==new URL(url).origin)return;
      const d=event.data||{};
      if(d.kind==='qf-chart-ready'){bind();return;}
      if(d.pane_id!==id||d.generation!==context.generation||d.revision!==context.request.revision)return;
      if(['qf-drawings-request','qf-drawings-commit','qf-drawings-undo','qf-drawings-conflict'].includes(d.kind)&&d.symbol===context.runtime?.symbol){options.onDrawing?.(id,d);return;}
      if(d.kind==='qf-chart-activate'){options.onActivate(id);return;}
      if(d.kind==='qf-chart-escape'){options.onEscape(id);return;}
      if(d.kind==='qf-chart-selection'&&context.catalog.some(p=>p.continuous===d.continuous)&&['actual','continuous'].includes(d.mode)){
        options.onChoose(id,d.continuous,d.mode);return;}
      if(d.kind==='qf-chart-period'&&Object.hasOwn(periods,d.period)){options.onPeriod(id,d.period);return;}
      if(d.kind==='qf-chart-command-failed'){problem='所选年份尚未收到有效数据，请等待加载。';render();return;}
      if(d.kind==='qf-chart-state'&&d.status==='unsupported'){
        reported={status:'unsupported'};problem='图表适配或当前数据不足，已暂停显示。';render();return;}
      if(d.kind!=='qf-chart-state'||!['ready','loading','invalid'].includes(d.status)||
        d.symbol!==context.runtime?.symbol||d.duration!==QfChartState.duration(QfChartState.period(context.config)))return;
      reported={status:d.status,symbol:d.symbol,duration:d.duration,history:d.history,visible:d.visible,
        reason:d.reason,protocol:d.protocol,md_connected:typeof d.md_connected==='boolean'?d.md_connected:null,
        viewport_width:d.viewport_width,viewport_height:d.viewport_height};
      if(d.status==='ready'&&(!Number.isFinite(d.viewport_width)||!Number.isFinite(d.viewport_height)||
        Math.abs(d.viewport_width-frame.clientWidth)>2||Math.abs(d.viewport_height-frame.clientHeight)>2)){
        reported.status='loading';reported.reason='viewport_loading';}
      problem=d.status==='invalid'?'历史数据需核实：'+(d.history?.issues||[]).map(k=>issues[k]).filter(Boolean).join('；'):
        d.status==='unsupported'?'图表适配或当前数据不足，已暂停显示。':'';
      options.onState?.(id,reported);render();
    }
    addEventListener('message',message);frame.addEventListener('load',bind);
    const resizeObserver=typeof ResizeObserver==='function'?new ResizeObserver(bind):null;
    resizeObserver?.observe(frame);
    root.addEventListener('pointerdown',()=>options.onActivate(id));
    $('product').onchange=()=>options.onChoose(id,$('product').value);
    $('chart-source').onchange=()=>options.onSource(id,$('chart-source').value);
    $('period').onchange=()=>options.onPeriod(id,$('period').value||null);
    $('chart-favorite').onclick=()=>options.onFavorite(context.config.continuous);
    $('expand-chart').onclick=()=>options.onExpand(id);
    $('history-year').onchange=()=>{if($('history-year').value)post('year',$('history-year').value)};
    $('history-latest').onclick=()=>post('latest');
    return {update,post,send,setExpanded(value){root.classList.toggle('expanded',value);$('expand-chart').textContent=value?'还原 K 线（Esc）':'放大 K 线';},
      inspect:()=>({state:reported,problem,url,request:context?.request,
        viewport:{width:frame.clientWidth,height:frame.clientHeight},visible:frame.style.visibility==='visible'}),
      dispose(){if(disposed)return;post('dispose');disposed=true;resizeObserver?.disconnect();removeEventListener('message',message);frame.src='about:blank';root.remove();}};
  }
  window.QfChartPane={create};
})();
