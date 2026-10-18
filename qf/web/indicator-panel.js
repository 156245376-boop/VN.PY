// 面向用户的指标选择与参数表单；不显示公式代码或 JSON。
(() => {
  'use strict';const S=()=>QfIndicatorState;
  const labels={periods:'均线周期（逗号分隔，可增减）',n:'计算周期',m:'平滑周期',m1:'第一平滑周期',m2:'第二平滑周期',short:'短周期',long:'长周期',p:'标准差倍数',step:'加速步长',max:'加速上限',ticks_per_row:'每价格档跳数（0 为自动）'};
  function timeInput(ns){return ns?new Date(Number(BigInt(ns)/1000000n)+8*3600e3).toISOString().slice(0,19):'';}
  function timeValue(text,previous){if(previous&&text===timeInput(previous))return previous;
    if(!/^\d{4}-\d\d-\d\dT\d\d:\d\d(?::\d\d)?$/.test(text))throw Error('请填写完整的北京时间');
    const ms=Date.parse(text+'+08:00');if(!Number.isFinite(ms))throw Error('时间无效');return String(BigInt(ms)*1000000n);}
  function parameters(item,values){const next=S().clone(item);
    for(const [key,value]of Object.entries(values)){
      if(key==='periods')next.params[key]=String(value).split(/[,，\s]+/).filter(Boolean).map(Number);
      else if(key==='mode')next.params.mode=value;else next.params[key]=Number(value);}
    return S().check(next);
  }
  function create(root,options){let pane=null,config=null;root.className='indicator-panel';root.hidden=true;
    const el=(tag,text)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;return n;};
    function button(label,action){const b=el('button',label);b.type='button';b.onclick=action;return b;}
    function change(a){try{options.onChange({...a,pane});}catch(e){root.querySelector('.indicator-error').textContent=e.message||'指标设置无效';}}
    function render(){if(!config)return;root.replaceChildren();const head=el('div');head.className='indicator-panel-head';
      head.append(el('h2',pane.replace('pane-','图 ')+' · 指标设置'),button('关闭',close));root.append(head);
      root.append(el('p','可叠加多个主图与副图指标；VP 是按收盘价归集的估算。'));
      const error=el('p');error.className='indicator-error';error.role='status';root.append(error);
      const add=el('div'),select=el('select');select.className='indicator-kind';select.setAttribute('aria-label','选择添加指标');
      for(const [kind,meta]of Object.entries(S().catalog()))select.add(new Option(meta.name,kind));
      add.append(select,button('添加指标',()=>change({type:'add',kind:select.value})));root.append(add);
      for(const item of config.items){const box=el('form');box.dataset.indicator=item.id;box.className='indicator-item';
        const title=el('div'),enabled=el('input');enabled.type='checkbox';enabled.checked=item.visible;
        enabled.onchange=()=>change({type:'change',item:{...S().clone(item),visible:enabled.checked}});
        title.append(enabled,el('strong',S().catalog()[item.type].name+(item.id==='vp-fixed'?' · 固定区间':'')),button('删除',()=>change({type:'remove',id:item.id})));box.append(title);
        function field(label,input){const l=el('label',label);l.append(input);box.append(l);return input;}
        const inputs={};for(const [key,value]of Object.entries(item.params)){
          if(key==='range')continue;
          const input=el(key==='mode'?'select':'input');input.dataset.param=key;
          if(key==='mode'){input.add(new Option('当前屏幕范围','screen'));input.add(new Option('自己选择固定区间','fixed'));input.value=value;}
          else{input.type=key==='periods'?'text':'number';input.value=Array.isArray(value)?value.join(', '):value;input.step=['step','max','p'].includes(key)?'any':'1';}
          inputs[key]=field(key==='mode'?'统计范围':labels[key]||key,input);
        }
        const style=S().clone(item.style),colors=[];
        for(let n=0;n<Math.min(item.type==='ma'||item.type==='ema'?item.params.periods.length:3,8);n++){
          const input=el('input');input.type='color';input.value=style.colors[n%style.colors.length];input.dataset.color=String(n);
          field((item.params.periods?.[n]??['第一','第二','第三'][n])+'线颜色',input);colors.push(input);}
        const width=el('input');width.type='number';width.min=1;width.max=6;width.value=style.width;field('线宽（像素）',width);
        const height=el('input');height.type='number';height.min=120;height.max=600;height.value=item.height;
        if(S().catalog()[item.type].board==='sub')field('副图高度（像素）',height);
        let side,percent,transparency,poc,startInput,endInput;
        if(item.type==='vp'){
          side=el('select');side.add(new Option('图表左侧','left'));side.add(new Option('图表右侧','right'));side.value=style.side;field('分布位置',side);
          percent=el('input');percent.type='number';percent.min=10;percent.max=40;percent.value=style.width_pct;field('最大宽度（占图表 %）',percent);
          transparency=el('input');transparency.type='number';transparency.min=10;transparency.max=90;transparency.value=style.transparency;field('透明度（%）',transparency);
          poc=el('input');poc.type='checkbox';poc.checked=style.poc;field('显示最大量价位线 POC',poc);
          const actions=el('div');actions.append(button('在图上选择时间区间',()=>{options.onSelectRange?.(pane,item.id);close();}),
            button('定位到所选区间',()=>{options.onLocateRange?.(pane,item.id);close();}));box.append(actions);
          startInput=el('input');endInput=el('input');for(const input of [startInput,endInput]){input.type='datetime-local';input.step='1';}
          startInput.value=timeInput(item.params.range?.start_ns);endInput.value=timeInput(item.params.range?.end_ns);
          field('固定区间开始（北京时间）',startInput);field('固定区间结束（北京时间）',endInput);
          const summary=el('p',item.params.range?'已选区间：'+new Date(Number(BigInt(item.params.range.start_ns)/1000000n)+8*3600e3).toISOString().slice(0,19).replace('T',' ')+' 起（北京时间）':'固定区间尚未选择');summary.className='indicator-range-summary';box.append(summary);
        }
        const actions=el('div');actions.className='indicator-item-actions';
        const apply=el('button','应用参数');apply.type='submit';actions.append(apply,
          button('恢复默认',()=>{const next=S().item(item.type,item.id);if(item.id==='vp-fixed')next.params.mode='fixed';change({type:'change',item:next});}),
          button('上移',()=>change({type:'move',id:item.id,delta:-1})),button('下移',()=>change({type:'move',id:item.id,delta:1})));box.append(actions);
        box.onsubmit=e=>{e.preventDefault();try{const next=parameters(item,Object.fromEntries(Object.entries(inputs).map(([k,v])=>[k,v.value])));
          next.style.colors=colors.map(c=>c.value);next.style.width=Number(width.value);next.height=Number(height.value);
          if(side){next.style.side=side.value;next.style.width_pct=Number(percent.value);next.style.transparency=Number(transparency.value);next.style.poc=poc.checked;}
          if(startInput&&(startInput.value||endInput.value)){next.params.range={symbol:options.symbol?.(pane)||item.params.range?.symbol||'',start_ns:timeValue(startInput.value,item.params.range?.start_ns),end_ns:timeValue(endInput.value,item.params.range?.end_ns)};}
          change({type:'change',item:S().check(next)});
        }catch(err){error.textContent=err.message;}};
        root.append(box);
      }
    }
    function close(){root.hidden=true;}
    const outside=e=>{if(!root.hidden&&!root.contains(e.target)&&!e.target.closest?.('[data-role="indicators"]'))close();};
    const key=e=>{if(e.key==='Escape'&&!root.hidden){e.preventDefault();e.stopImmediatePropagation();close();}};
    document.addEventListener('pointerdown',outside);document.addEventListener('keydown',key,true);addEventListener('blur',close);
    return {open(id,next){pane=id;config=S().clone(next);root.hidden=false;render();},close,
      dispose(){document.removeEventListener('pointerdown',outside);document.removeEventListener('keydown',key,true);removeEventListener('blur',close);root.remove();}};
  }
  window.QfIndicatorPanel={create,parameters,timeInput,timeValue};
})();
