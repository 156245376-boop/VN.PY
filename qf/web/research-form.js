// 实验表单只管理草稿；服务端验证和运行快照是执行依据。
(() => {
  'use strict';
  const defaults=()=>({schema_version:2,strategy_id:'ma_cross',strategy_version:2,name:'双均线实验',
    continuous:'KQ.m@SHFE.rb',symbol:'SHFE.rb2505',bar_seconds:60,fast_period:5,slow_period:20,
    start:'2025-03-03',end:'2025-03-07',initial_balance:'100000',precision:'minute',
    timeout_seconds:30,execution_timeout_seconds:30,risk:{sizing:'risk_budget',fixed_lots:'',risk_budget:'',
      stop_method:'confirmed_pivot',pivot_left:2,pivot_right:2,limit_lots:false,limit_margin:false,
      max_lots:null,max_margin_ratio:null,take_profit_mode:'r_multiple',take_profit_value:'3',
      stairs_enabled:true,first_trigger_r:'1',first_offset_ticks:1,second_trigger_r:'2',second_lock_r:'0.5'}});
  function contractFit(row,end){
    const stamp=row.expire_datetime;
    if(typeof stamp!=='number'||!Number.isFinite(stamp)||stamp<=0)return {expiry:null,eligible:true};
    const expiry=new Date(stamp*1000+8*3600000).toISOString().slice(0,10);
    return {expiry,eligible:!end||end<=expiry};
  }
  function preview(r,s,available){
    if(!s)return null;
    const tick=Number(s.price_tick),multiple=Number(s.volume_multiple),margin=Number(s.margin_per_lot),
      distance=Number(r.stop_ticks),cap=Number(r.max_lots),ratio=Number(r.max_margin_ratio);
    if(![tick,multiple,margin,distance,cap,ratio,available].every(x=>Number.isFinite(x)&&x>0))return null;
    let lots=r.sizing==='fixed'?Number(r.fixed_lots):Math.floor(Number(r.risk_budget)/(tick*multiple*distance));
    lots=Math.max(0,Math.min(lots,cap,Math.floor(Math.min(available,available*ratio)/margin)));
    if(lots<Number(s.min_open_lots||1))lots=0;
    const initial_r=lots*tick*multiple*distance;
    return {lots,initial_r,take_profit:r.take_profit_mode==='r_multiple'?initial_r*Number(r.take_profit_value):Number(r.take_profit_value),one_tick:lots*tick*multiple};
  }
  function create(root,options={}){
    const inputs=new Map(),fields=new Map();let catalog=[],contracts=[],running=false,legacy=null;
    const grid=document.createElement('div');grid.className='research-grid';root.append(grid);
    function field(key,title,choices,type='number'){
      const label=document.createElement('label');label.textContent=title;
      const input=document.createElement(choices?'select':'input');input.dataset.field=key;
      if(choices)for(const [value,text] of choices)input.add(new Option(text,value));
      else {input.type=type;if(type==='number'){input.min='0';input.step='any';}}
      const error=document.createElement('small');error.id='error-'+key.replaceAll('.','-');
      input.setAttribute('aria-describedby',error.id);error.className='field-error';
      label.append(input,error);grid.append(label);inputs.set(key,input);fields.set(key,label);
      input.addEventListener('change',()=>{if(['continuous','start','end'].includes(key)){contracts=[];setContracts([]);}update();options.onChange?.(key);});
      input.addEventListener('input',update);return input;
    }
    field('name','实验名称',null,'text');field('strategy_id','策略模板',[['ma_cross','双均线交叉（简单均线）']]);field('continuous','品种',[]);field('symbol','实际月份合约（先查询）',[]);
    field('bar_seconds','K线周期',[[60,'1分钟'],[300,'5分钟'],[900,'15分钟'],[1800,'30分钟'],[3600,'1小时'],[86400,'日线']]);
    field('fast_period','快均线周期（根）');field('slow_period','慢均线周期（根）');
    field('start','起始交易日',null,'date');field('end','结束交易日',null,'date');
    field('initial_balance','回测初始虚拟资金（元）');
    field('precision','回测数据精度',[['minute','分钟近似（流程验证）'],['tick','Tick（需核实权限与覆盖）']]);
    field('risk.sizing','定仓方式',[['risk_budget','按每笔风险预算计算手数'],['fixed','固定手数']]);
    field('risk.fixed_lots','每次固定手数（手）');field('risk.risk_budget','每笔计划风险预算（元，不含费用）');
    field('risk.pivot_left','波峰／波谷左侧确认柱数（根）');field('risk.pivot_right','右侧收盘确认柱数（根）');
    field('risk.limit_lots','限制最大手数（可选）',[['false','不启用'],['true','启用手数上限']]);
    field('risk.max_lots','最大持仓手数（手）');
    field('risk.limit_margin','限制保证金比例（可选）',[['false','不启用'],['true','启用保证金比例上限']]);
    field('risk.max_margin_ratio','最大保证金占启动权益（%）');
    field('risk.take_profit_mode','终点止盈方式',[['r_multiple','初始风险的倍数（R）'],['amount','固定毛盈利金额（元）']]);
    field('risk.take_profit_value','终点止盈数值（R倍数或元）');
    field('risk.stairs_enabled','阶梯保护',[['true','启用阶梯保护'],['false','只用初始止损与终点止盈']]);
    field('risk.first_trigger_r','第一档触发（R）');field('risk.first_offset_ticks','第一档：开仓价向盈利方向偏移（跳）');
    field('risk.second_trigger_r','第二档触发（R）');field('risk.second_lock_r','第二档锁定盈利（R）');
    const note=document.createElement('p');note.className='research-preview';root.append(note);
    function read(){if(legacy)return structuredClone(legacy);const result=defaults();for(const [key,input]of inputs){const target=key.startsWith('risk.')?result.risk:result,k=key.split('.').at(-1);
      target[k]=input.value;}
      for(const k of ['bar_seconds','fast_period','slow_period'])result[k]=Number(result[k]);
      for(const k of ['fixed_lots','pivot_left','pivot_right','first_offset_ticks'])result.risk[k]=Number(result.risk[k]);
      for(const k of ['limit_lots','limit_margin'])result.risk[k]=result.risk[k]==='true';
      result.risk.max_lots=result.risk.limit_lots?Number(result.risk.max_lots):null;
      result.risk.max_margin_ratio=result.risk.limit_margin?String(Number(result.risk.max_margin_ratio)/100):null;
      result.risk.stairs_enabled=result.risk.stairs_enabled==='true';
      if(result.risk.sizing==='fixed'&&!result.risk.risk_budget)result.risk.risk_budget='1';
      if(result.risk.sizing==='risk_budget'&&!result.risk.fixed_lots)result.risk.fixed_lots=1;
      return result;
    }
    function update(){const value=read();fields.get('risk.fixed_lots').hidden=value.risk.sizing!=='fixed';
      fields.get('risk.risk_budget').hidden=value.risk.sizing!=='risk_budget';
      fields.get('risk.max_lots').hidden=!value.risk.limit_lots;
      fields.get('risk.max_margin_ratio').hidden=!value.risk.limit_margin;
      for(const k of ['first_trigger_r','first_offset_ticks','second_trigger_r','second_lock_r'])fields.get('risk.'+k).hidden=!value.risk.stairs_enabled;
      note.textContent=legacy?'旧版跳数止损实验（只读）；请复制为新版拐点实验。旧记录不会被改写。':
        '止损价、止损距离与手数：等待信号后计算。多单取最近已确认波谷，空单取波峰；按预算和实际距离计算。1R推至开仓价±1跳，2R锁0.5R，3R退出；1跳不保证覆盖费用。';
    }
    function setCatalog(rows){const current=inputs.get('continuous').value||'KQ.m@SHFE.rb';catalog=rows||[];
      const select=inputs.get('continuous');if(select.dataset.key===JSON.stringify(catalog))return;
      select.dataset.key=JSON.stringify(catalog);select.replaceChildren();
      for(const row of catalog)select.add(new Option(row.name+' · '+row.exchange,row.continuous));
      select.value=current;if(!select.value&&catalog.length)select.value=catalog[0].continuous;}
    function setContracts(rows,selected){contracts=rows||[];const select=inputs.get('symbol'),old=selected||select.value||'SHFE.rb2505';select.replaceChildren(new Option('请选择已查询的实际合约',''));
      const end=inputs.get('end').value;let eligibleCount=0;
      for(const row of contracts){const fit=contractFit(row,end),option=new Option((row.name||'实际合约')+' · '+row.symbol+' · '+(fit.expiry?'到期 '+fit.expiry:'到期日待核实')+(fit.eligible?'':'（不能覆盖结束日）'),row.symbol);
        option.disabled=!fit.eligible;if(fit.eligible)eligibleCount++;select.add(option);}
      select.value=contracts.some(c=>c.symbol===old&&contractFit(c,end).eligible)?old:'';update();
      return {eligibleCount};}
    function render(config){legacy=config.strategy_version===1?structuredClone(config):null;
      for(const [key,input]of inputs){const value=key.startsWith('risk.')?config.risk[key.slice(5)]:config[key];
      input.value=key==='risk.max_margin_ratio'&&value!=null&&value!==''?String(Number(value)*100):String(value??'');}
      update();setRunning(running);showErrors({});}
    function setRunning(value){running=value;for(const input of inputs.values())input.disabled=running||!!legacy;}
    function showErrors(errors){for(const [key,input]of inputs){const message=errors[key]||'';
      input.setAttribute('aria-invalid',message?'true':'false');fields.get(key).querySelector('small').textContent=message;}
      const first=inputs.get(Object.keys(errors)[0]);first?.focus();}
    function readContractRequest(){return {continuous:inputs.get('continuous').value,start:inputs.get('start').value,end:inputs.get('end').value};}
    function setRunState(snapshot){const p=snapshot?.entry_plan;if(p)note.textContent=`本次入场计划：止损价 ${p.stop_price??'—'}；距离 ${p.distance_ticks??'—'} 跳；计划 ${p.lots} 手；计划风险 ${p.planned_r} 元。实际成交风险可能因滑点和费用变化。`;}
    render(defaults());
    return {read,render,setCatalog,setContracts,readContractRequest,showErrors,setRunState,setRunning,
      get isLegacy(){return !!legacy;},dispose(){root.replaceChildren();}};
  }
  globalThis.QfResearchForm={defaults,preview,create,contractFit};
})();
