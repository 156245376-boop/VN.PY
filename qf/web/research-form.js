// 实验表单只管理草稿；服务端验证和运行快照是执行依据。
(() => {
  'use strict';
  const defaults=()=>({schema_version:1,strategy_id:'ma_cross',strategy_version:1,name:'双均线实验',
    continuous:'KQ.m@SHFE.rb',symbol:'SHFE.rb2505',bar_seconds:60,fast_period:5,slow_period:20,
    start:'2025-03-03',end:'2025-03-07',initial_balance:'100000',precision:'minute',
    timeout_seconds:30,execution_timeout_seconds:30,risk:{sizing:'risk_budget',fixed_lots:'',risk_budget:'',
      stop_ticks:'',max_lots:'',max_margin_ratio:'',take_profit_mode:'r_multiple',take_profit_value:'3',
      stairs_enabled:true,first_trigger_r:'1',first_offset_ticks:1,second_trigger_r:'2',second_lock_r:'0.5'}});
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
    const inputs=new Map(),fields=new Map();let catalog=[],contracts=[],running=false;
    const grid=document.createElement('div');grid.className='research-grid';root.append(grid);
    function field(key,title,choices,type='number'){
      const label=document.createElement('label');label.textContent=title;
      const input=document.createElement(choices?'select':'input');input.dataset.field=key;
      if(choices)for(const [value,text] of choices)input.add(new Option(text,value));
      else {input.type=type;if(type==='number'){input.min='0';input.step='any';}}
      label.append(input);grid.append(label);inputs.set(key,input);fields.set(key,label);
      input.addEventListener('change',()=>{if(key==='continuous'){contracts=[];setContracts([]);}update();options.onChange?.(key);});
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
    field('risk.stop_ticks','初始止损距离（跳）');field('risk.max_lots','最大持仓手数（手）');
    field('risk.max_margin_ratio','最大保证金占启动权益（%）');
    field('risk.take_profit_mode','终点止盈方式',[['r_multiple','初始风险的倍数（R）'],['amount','固定毛盈利金额（元）']]);
    field('risk.take_profit_value','终点止盈数值（R倍数或元）');
    field('risk.stairs_enabled','阶梯保护',[['true','启用阶梯保护'],['false','只用初始止损与终点止盈']]);
    field('risk.first_trigger_r','第一档触发（R）');field('risk.first_offset_ticks','第一档：开仓价向盈利方向偏移（跳）');
    field('risk.second_trigger_r','第二档触发（R）');field('risk.second_lock_r','第二档锁定盈利（R）');
    const note=document.createElement('p');note.className='research-preview';root.append(note);
    function read(){const result=defaults();for(const [key,input]of inputs){const target=key.startsWith('risk.')?result.risk:result,k=key.split('.').at(-1);
      target[k]=input.value;}
      for(const k of ['bar_seconds','fast_period','slow_period'])result[k]=Number(result[k]);
      for(const k of ['fixed_lots','stop_ticks','max_lots','first_offset_ticks'])result.risk[k]=Number(result.risk[k]);
      result.risk.max_margin_ratio=String(Number(result.risk.max_margin_ratio)/100);
      result.risk.stairs_enabled=result.risk.stairs_enabled==='true';
      if(result.risk.sizing==='fixed'&&!result.risk.risk_budget)result.risk.risk_budget='1';
      if(result.risk.sizing==='risk_budget'&&!result.risk.fixed_lots)result.risk.fixed_lots=1;
      return result;
    }
    function update(){const value=read();fields.get('risk.fixed_lots').hidden=value.risk.sizing!=='fixed';
      fields.get('risk.risk_budget').hidden=value.risk.sizing!=='risk_budget';
      for(const k of ['first_trigger_r','first_offset_ticks','second_trigger_r','second_lock_r'])fields.get('risk.'+k).hidden=!value.risk.stairs_enabled;
      const spec=contracts.find(c=>c.symbol===value.symbol),p=preview(value.risk,spec,Number(value.initial_balance));
      note.textContent=p?`SDK当前模型预估：${p.lots} 手；实际初始风险约 ${p.initial_r} 元；终点毛止盈 ${p.take_profit} 元；全仓一跳 ${p.one_tick} 元。以运行时核实为准，费用另列。`:
        '查询并选择实际合约、填写仓位参数后显示换算。默认保护：1R推至开仓价±1跳，2R锁0.5R，3R退出。1跳不保证覆盖费用。';
    }
    function setCatalog(rows){const current=inputs.get('continuous').value||'KQ.m@SHFE.rb';catalog=rows||[];
      const select=inputs.get('continuous');if(select.dataset.key===JSON.stringify(catalog))return;
      select.dataset.key=JSON.stringify(catalog);select.replaceChildren();
      for(const row of catalog)select.add(new Option(row.name+' · '+row.exchange,row.continuous));
      select.value=current;if(!select.value&&catalog.length)select.value=catalog[0].continuous;}
    function setContracts(rows,selected){contracts=rows||[];const select=inputs.get('symbol'),old=selected||select.value||'SHFE.rb2505';select.replaceChildren(new Option('请选择已查询的实际合约',''));
      for(const row of contracts)select.add(new Option((row.name||'实际合约')+' · '+row.symbol,row.symbol));
      select.value=contracts.some(c=>c.symbol===old)?old:(contracts[0]?.symbol||'');update();}
    function render(config){for(const [key,input]of inputs){const value=key.startsWith('risk.')?config.risk[key.slice(5)]:config[key];
      input.value=key==='risk.max_margin_ratio'&&value!==''?String(Number(value)*100):String(value??'');}update();}
    render(defaults());
    return {read,render,setCatalog,setContracts,setRunning(value){running=value;for(const input of inputs.values())input.disabled=running;},dispose(){root.replaceChildren();}};
  }
  globalThis.QfResearchForm={defaults,preview,create};
})();
