// 工作区纯配置：不接触 DOM、SDK 或凭证。
(() => {
  'use strict';
  const periods={close:60,'1m':60,'5m':300,'15m':900,'30m':1800,'1h':3600,'1d':86400};
  const clone=value=>JSON.parse(JSON.stringify(value));
  function defaults(){return {schema:1,layout:'single',active:'pane-1',linked:false,
    split:{column:.5,row:.5},account_collapsed:false,
    panes:[1,2,3,4].map(i=>({id:'pane-'+i,continuous:null,mode:'actual',period:null}))}}
  function visibleIds(s){return s.layout==='single'?[s.active]:s.panes.slice(0,s.layout==='quad'?4:2).map(p=>p.id)}
  const period=p=>p.period||(p.mode==='continuous'?'1d':'1m');
  function reduce(current,action){const s=clone(current),p=s.panes.find(p=>p.id===s.active);
    switch(action.type){
      case 'activate':if(s.panes.some(p=>p.id===action.id))s.active=action.id;break;
      case 'layout':if(!['single','columns','rows','quad'].includes(action.value))break;
        s.layout=action.value;
        if(!visibleIds(s).includes(s.active))s.panes=[p,...s.panes.filter(x=>x!==p).sort((a,b)=>a.id.localeCompare(b.id))];
        for(const id of visibleIds(s)){const next=s.panes.find(x=>x.id===id);
          if(!next.continuous){next.continuous=p.continuous;next.mode=p.mode;}}
        break;
      case 'choose':for(const next of s.panes)if(next.id===s.active||(s.linked&&visibleIds(s).includes(next.id)))next.continuous=action.symbol;break;
      case 'source':if(['actual','continuous'].includes(action.value))p.mode=action.value;break;
      case 'period':if(action.value===null||Object.hasOwn(periods,action.value))p.period=action.value;break;
      case 'link':s.linked=action.value===true;break;
      case 'split':if(['row','column'].includes(action.axis)&&Number.isFinite(action.value))s.split[action.axis]=Math.max(.1,Math.min(.9,action.value));break;
      case 'collapse-account':s.account_collapsed=action.value===true;break;
    }return s;
  }
  window.QfChartState={defaults,visibleIds,reduce,period,duration:p=>periods[p]*1e9,clone};
})();
