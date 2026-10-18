// 指标状态只处理配置，不处理行情、凭证或公式。
(() => {
  'use strict';
  const clone=v=>JSON.parse(JSON.stringify(v));let catalog={},seed=null;
  const keys=(o,want)=>o&&typeof o==='object'&&!Array.isArray(o)&&Object.keys(o).sort().join('|')===want.slice().sort().join('|');
  const number=(v,a,b,integer=false)=>typeof v==='number'&&Number.isFinite(v)&&v>=a&&v<=b&&(!integer||Number.isInteger(v));
  function check(i){
    const fail=()=>{throw Error('指标参数无效，请检查范围与格式');};
    if(!keys(i,['id','type','visible','params','style','height'])||!Object.hasOwn(catalog,i.type)||typeof i.visible!=='boolean')fail();
    if(!(i.type==='vp'?['vp','vp-fixed']:[i.type]).includes(i.id)||!keys(i.params,Object.keys(catalog[i.type].params)))fail();
    for(const [k,v] of Object.entries(i.params)){
      if(k==='periods'){if(!Array.isArray(v)||!v.length||v.length>8||new Set(v).size!==v.length||v.some(n=>!number(n,1,1000,true)))fail();}
      else if(['n','m','m1','m2','short','long','mean_length','std_length'].includes(k)){if(!number(v,1,1000,true))fail();}
      else if(k==='source'){if(!['open','high','low','close'].includes(v))fail();}
      else if(k==='reference_lines'){if(typeof v!=='boolean')fail();}
      else if(k==='p'){if(!number(v,.01,100))fail();}
      else if(['step','max'].includes(k)){if(!number(v,.000001,1))fail();}
      else if(k==='ticks_per_row'){if(!number(v,0,10000,true))fail();}
      else if(k==='mode'){if(!['screen','fixed'].includes(v))fail();}
      else if(k==='range'&&v!==null){if(!keys(v,['symbol','start_ns','end_ns'])||
        !/^(KQ\.m@)?(SHFE|DCE|CZCE|CFFEX|INE|GFEX)\.[A-Za-z]+\d{0,4}$/.test(v.symbol)||
        !/^\d{16,20}$/.test(v.start_ns)||!/^\d{16,20}$/.test(v.end_ns)||BigInt(v.start_ns)>=BigInt(v.end_ns))fail();}
    }
    if(i.type==='macd'&&i.params.short>=i.params.long||i.type==='sar'&&i.params.step>i.params.max)fail();
    const s=i.style;
    if(!keys(s,['colors','width','side','width_pct','transparency','poc'])||!Array.isArray(s.colors)||
      !s.colors.length||s.colors.length>8||s.colors.some(c=>!/^#[0-9a-fA-F]{6}$/.test(c))||
      !number(s.width,1,6)||!number(s.width_pct,10,40)||!number(s.transparency,10,90)||
      !['left','right'].includes(s.side)||typeof s.poc!=='boolean'||!number(i.height,120,600,true))fail();
    return clone(i);
  }
  function validate(c){
    if(!keys(c,['schema','panes'])||c.schema!==1||!keys(c.panes,['pane-1','pane-2','pane-3','pane-4']))throw Error('指标设置无效');
    for(const p of Object.values(c.panes)){if(!keys(p,['items'])||!Array.isArray(p.items)||p.items.length>Object.keys(catalog).length+1)throw Error('指标设置无效');
      const seen=new Set();for(const i of p.items){check(i);if(seen.has(i.id))throw Error('指标已添加');seen.add(i.id);}}
    return clone(c);
  }
  function item(kind,id=kind){if(!Object.hasOwn(catalog,kind))throw Error('未知指标');
    return {id,type:kind,visible:true,params:clone(catalog[kind].params),style:clone(seed.panes['pane-1'].items[0].style),height:160};}
  function reduce(current,a){const c=clone(current),p=c.panes[a.pane];if(!p)throw Error('图格无效');
    if(a.type==='add'){let id=a.kind;if(a.kind==='vp'&&p.items.some(i=>i.id==='vp'))id='vp-fixed';
      const i=item(a.kind,id);if(id==='vp-fixed')i.params.mode='fixed';p.items.push(i);}
    if(a.type==='change'){const n=p.items.findIndex(i=>i.id===a.item.id);if(n<0)throw Error('指标已移除');p.items[n]=check(a.item);}
    if(a.type==='remove')p.items=p.items.filter(i=>i.id!==a.id);
    if(a.type==='move'){const n=p.items.findIndex(i=>i.id===a.id),j=n+a.delta;if(n>=0&&j>=0&&j<p.items.length)[p.items[n],p.items[j]]=[p.items[j],p.items[n]];}
    return validate(c);
  }
  window.QfIndicatorState={install(meta,defaults){catalog=clone(meta);seed=clone(defaults);},defaults:()=>clone(seed),
    catalog:()=>clone(catalog),item,validate,check,reduce,clone};
})();
