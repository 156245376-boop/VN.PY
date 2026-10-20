(() => {
  'use strict';
  const HEX32=/^[0-9a-f]{32}$/;
  function buildPlan(capacity,slots){
    if(!Number.isInteger(capacity)||capacity<1||capacity>4)throw Error('并发数必须为1—4');
    if(!Array.isArray(slots)||slots.length!==capacity)throw Error('槽位数量必须等于并发数');
    return {capacity,slots:slots.map((item,index)=>{
      if(!item||!HEX32.test(item.experiment_id||'')||!Number.isInteger(item.revision)
        ||item.revision<1)throw Error(`槽位${index+1}尚未配置有效实验`);
      return {experiment_id:item.experiment_id,revision:item.revision,
        include_fee_stress:item.include_fee_stress===true};
    })};
  }
  function create(root,api,options={}){
    const el=(tag,text)=>{const node=document.createElement(tag);node.textContent=text??'';return node;};
    const title=el('h3','回测计划'),capacityLabel=el('label','并发数 '),capacity=el('input');
    capacity.type='number';capacity.min='1';capacity.max='4';capacity.value='1';
    capacityLabel.append(capacity);
    const list=el('div'),start=el('button','开始全部回测');start.className='primary';
    root.replaceChildren(title,capacityLabel,list,start);
    let slots=[],busy=false,errors={};
    function complete(item){return item&&HEX32.test(item.experiment_id||'')&&
      Number.isInteger(item.revision)&&item.revision>0;}
    function render(){
      list.replaceChildren();
      slots.forEach((item,index)=>{
        const row=el('article'),summary=el('div'),name=el('strong',
          item?.name||`槽位 ${index+1} · 尚未配置`);
        const detail=el('small',complete(item)
          ?`${item.config?.continuous||item.config?.symbol||'品种待核实'} · ${item.config?.start||'—'} → ${item.config?.end||'—'}`
          :'点击“配置策略”选择或创建实验');
        if(errors[`slot_${index+1}`])detail.textContent=errors[`slot_${index+1}`];
        summary.append(name,detail);row.className='research-plan-row';
        const actions=el('div'),configure=el('button','配置策略');
        configure.onclick=()=>options.onConfigure?.(index,item||null);
        const stressLabel=el('label','双倍费用'),stress=el('input');stress.type='checkbox';
        stress.checked=item?.include_fee_stress===true;
        stress.onchange=()=>{if(item)item.include_fee_stress=stress.checked;};
        stressLabel.prepend(stress);actions.append(configure,stressLabel);
        row.append(summary,actions);list.append(row);
      });
      start.disabled=busy||slots.length!==Number(capacity.value)||!slots.every(complete);
    }
    function setCapacity(value){
      const next=Number(value);
      if(!Number.isInteger(next)||next<1||next>4)throw Error('并发数必须为1—4');
      if(next<slots.length&&slots.slice(next).some(complete))
        throw Error('请先移除已配置的末尾槽位');
      errors={};
      if(next>slots.length)while(slots.length<next)slots.push({
        experiment_id:'',revision:0,include_fee_stress:false});
      slots=slots.slice(0,next);capacity.value=String(next);render();
      return next;
    }
    capacity.onchange=async()=>{
      try{const next=setCapacity(capacity.value);await options.onCapacity?.(next);}
      catch(error){capacity.value=String(slots.length||1);options.onNotice?.(error.message);render();}
    };
    start.onclick=async()=>{
      if(busy)return null;
      try{
        const plan=buildPlan(Number(capacity.value),slots);busy=true;render();
        const response=await options.onStart?.(plan);
        if(response?.ok)slots=[];return response;
      }catch(error){options.onNotice?.(error.message);return null;}
      finally{busy=false;render();}
    };
    return {
      setCapacity,
      configure(index,item){if(!Number.isInteger(index)||index<0||index>=slots.length)return;
        slots[index]={...slots[index],...item,include_fee_stress:item.include_fee_stress===true};
        errors={};render();},
      setErrors(value){errors=value&&typeof value==='object'?{...value}:{};render();},
      configureIndex(){return slots.findIndex(item=>!complete(item));},
      slots(){return slots.map(item=>({...item}));},
      show(value){root.hidden=!value;},
      render,
    };
  }
  globalThis.QfResearchPlanner={create,buildPlan};
})();
