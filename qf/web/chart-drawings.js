// 会话内研究图形，按完整合约隔离；不保存到磁盘。
(() => {
  'use strict';
  const clone=v=>JSON.parse(JSON.stringify(v));
  const symbolOK=s=>typeof s==='string'&&/^(?:KQ\.m@)?(SHFE|DCE|CZCE|CFFEX|INE|GFEX)\.[A-Za-z]+\d{0,4}$/.test(s);
  function valid(items){
    if(!Array.isArray(items)||items.length>200)return false;
    const ids=new Set();
    return items.every(item=>{
      if(!item||typeof item.id!=='string'||item.id.length>90||ids.has(item.id)||
        !['horizontal','trend','rectangle'].includes(item.type)||!Array.isArray(item.points)||
        item.points.length!==(item.type==='horizontal'?1:2))return false;
      ids.add(item.id);return item.points.every(p=>p&&Number.isFinite(p.time)&&p.time>0&&
        Number.isFinite(p.price)&&(!Object.hasOwn(p,'boundary')||typeof p.boundary==='boolean'));
    });
  }
  const clean=items=>items.map(d=>({id:d.id,type:d.type,points:d.points.map(p=>({time:p.time,price:p.price,...(p.boundary===true?{boundary:true}:{})}))}));
  function create(){const groups=new Map();
    function read(symbol){const g=groups.get(symbol);return {ok:true,version:g?.version||0,drawings:clone(g?.drawings||[])};}
    function commit(symbol,baseVersion,items){const old=read(symbol);
      if(!symbolOK(symbol)||!Number.isSafeInteger(baseVersion)||baseVersion!==old.version||!valid(items)||(!groups.has(symbol)&&groups.size>=100))return {...old,ok:false};
      const history=groups.get(symbol)?.history||[];history.push(old.drawings);if(history.length>100)history.shift();
      groups.set(symbol,{version:old.version+1,drawings:clean(items),history});return read(symbol);
    }
    function undo(symbol,baseVersion){const old=read(symbol),g=groups.get(symbol);
      if(!g||baseVersion!==g.version||!g.history.length)return {...old,ok:false};
      g.drawings=g.history.pop();g.version++;return read(symbol);
    }
    return {read,commit,undo};
  }
  window.QfDrawingBook={create,valid,symbolOK};
})();
