const toolsTimer=setInterval(()=>{
  const tools=window.QfNativeTools;
  if(!tools)return;
  if(!tools.probeInstalled){
    tools.probeInstalled=true;const attach=tools.attach;
    tools.attach=function(chart){window.fixtureChart=chart;return attach(chart)};
  }
  if(!window.fixtureChart){document.querySelector('.tq-top-view')?.__vue__?.$refs?.tqChart?.updateTqChart();return;}
  if(window.QfNativeHistory?.inspect().status!=='ready')return;
  clearInterval(toolsTimer);
  const check=(value,label)=>{if(!value)throw Error(label)};
  const wait=ms=>new Promise(resolve=>setTimeout(resolve,ms));
  (async()=>{
    const c=window.fixtureChart,b=c.mainBoard,r=b.rightYAxis,l=b.leftYAxis;
    const canvas=b._centerTopCanvas.dom;
    const resizeDivider=async delta=>{
      const handle=document.querySelector('.bottom-area-handle'),y=handle.getBoundingClientRect().top;
      handle.dispatchEvent(new MouseEvent('mousedown',{bubbles:true,clientY:y,buttons:1}));
      document.dispatchEvent(new MouseEvent('mousemove',{bubbles:true,clientY:y+delta,buttons:1}));
      document.dispatchEvent(new MouseEvent('mouseup',{bubbles:true,clientY:y+delta,buttons:0}));
      await wait(100);
    };
    const original=r.scale.domain(),h=b.height,oldDistance=r.scale(3300)-r.scale(3305),oldRange={...c.chartCtrl.range};
    await resizeDivider(60);
    const expanded=r.scale.domain();
    check(b.height>h,'actual divider did not resize chart');
    check(Math.abs(expanded[0]-original[0])<1e-6,'lower price moved');
    check(Math.abs(expanded[1]-(original[0]+(original[1]-original[0])*b.height/h))<1e-6,'height did not expand price range '+JSON.stringify({original,expanded,h,newHeight:b.height,oldRange,newRange:c.chartCtrl.range}));
    check(Math.abs((r.scale(3300)-r.scale(3305))-oldDistance)<=1,'candles stretched');
    check(JSON.stringify(r.scale.domain())===JSON.stringify(l.scale.domain()),'axis domains differ');
    const labels=axis=>[...axis.rootG.node().querySelectorAll('.tick text')].map(el=>el.textContent);
    check(labels(l).length>0&&labels(l).every(text=>/^\d+$/.test(text)),'coarse axis missing');
    check(labels(r).length>labels(l).length,'fine axis not finer');
    tools.restore();
    check(Math.abs(r.scale.domain()[1]-original[1])<1e-6,'restore failed');
    const rect=canvas.getBoundingClientRect(),x=rect.left+100,y=rect.top+70;
    const mouse=(type,xx=x,yy=y,options={})=>{
      const e=new MouseEvent(type,{bubbles:true,cancelable:true,clientX:xx,clientY:yy,button:0,buttons:1,...options});
      if(options.movementX!==undefined)Object.defineProperty(e,'movementX',{value:options.movementX});
      canvas.dispatchEvent(e);
    };
    mouse('mousedown',x,y,{button:2,buttons:2});
    mouse('mouseup',x,y,{button:2,buttons:0});
    mouse('contextmenu',x,y,{button:2,buttons:0});
    await wait(150);
    check(!c.tableContainer.isDraging,'right button started native drag');
    const menu=document.querySelector('[role=menu]');
    check(menu&&!menu.hidden,'context menu missing');
    [...menu.children].find(el=>el.textContent.startsWith('趋势线')).click();
    const before=c.chartCtrl.pixelLeft;
    mouse('mousedown');mouse('mouseup',x,y,{buttons:0});
    mouse('mousemove',x+100,y+20,{movementX:100,buttons:0});
    mouse('mousedown',x+100,y+20);mouse('mouseup',x+100,y+20,{buttons:0});
    await wait(130);
    const drawing=tools.inspect();
    check(drawing.drawings.length===1&&!drawing.pending,'two-point drawing missing');
    check(c.chartCtrl.pixelLeft===before&&!c.tableContainer.isDraging,'drawing also panned chart');
    await resizeDivider(20);
    const line=document.querySelector('svg[aria-label] line');
    check(line&&Math.abs(Number(line.getAttribute('y1'))-r.scale(drawing.drawings[0].points[0].price))<0.01,'drawing drifted after resize');
    document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}));
    check(tools.inspect().mode==='pan','escape did not restore pan');
    const ax=Number(line.getAttribute('x1'))+canvas.getBoundingClientRect().left;
    const ay=Number(line.getAttribute('y1'))+canvas.getBoundingClientRect().top;
    mouse('mousedown',ax,ay);mouse('mouseup',ax,ay,{buttons:0});
    check(document.querySelectorAll('svg[aria-label] circle').length===2,'selection handles missing');
    mouse('mousedown',ax,ay);
    mouse('mousemove',ax+c.bar.step*2,ay+12,{buttons:1});
    mouse('mouseup',ax+c.bar.step*2,ay+12,{buttons:0});
    check(tools.inspect().drawings[0].points[0].time!==drawing.drawings[0].points[0].time,'endpoint edit failed');
    tools.undo();
    check(tools.inspect().drawings[0].points[0].time===drawing.drawings[0].points[0].time,'edit undo failed');
    tools.select('pan');
    mouse('mousedown');await wait(130);
    mouse('mousemove',x+80,y,{movementX:80});mouse('mouseup',x+80,y,{buttons:0});
    check(c.chartCtrl.pixelLeft<before,'left drag not restored');
    const step=c.bar.step;
    canvas.dispatchEvent(new WheelEvent('wheel',{bubbles:true,cancelable:true,deltaY:-100}));
    await wait(120);check(c.bar.step>step,'wheel zoom lost');
    tools.undo();check(tools.inspect().drawings.length===0,'undo failed');
    const period=label=>[...document.querySelectorAll('.ivu-radio-wrapper')]
      .find(el=>el.textContent.trim()===label).click();
    const until=async test=>{for(let i=0;i<80;i++){if(test())return;await wait(30)}throw Error('period change timeout')};
    period('1小时');await until(()=>c.duration===3600e9&&window.QfNativeHistory.inspect().status==='ready');
    c.setRange(0,2);tools.select('rectangle');
    const cr=canvas.getBoundingClientRect();
    mouse('mousedown',cr.left+1,cr.top+50);mouse('mouseup',cr.left+1,cr.top+50,{buttons:0});
    mouse('mousedown',cr.left+c.bar.step+1,cr.top+110);mouse('mouseup',cr.left+c.bar.step+1,cr.top+110,{buttons:0});
    tools.select('pan');const rectangle=tools.inspect().drawings[0];
    check(rectangle.points[1].time-rectangle.points[0].time===7200e9,'hour rectangle is not two full bars');
    period('1分钟');await until(()=>c.duration===60e9&&window.QfNativeHistory.inspect().status==='ready');
    await wait(150);
    check(tools.inspect().drawings.length===1,'drawing vanished across periods');
    const box=document.querySelector('svg[aria-label] rect');
    check(box&&Math.abs(Number(box.getAttribute('width'))-120*c.bar.step)<0.1,'minute rectangle does not cover 120 bars');
    check(c.chartCtrl.range.leftId<=10,'switch did not keep drawing date in view');
    tools.select('pan');
    if(PREVIEW){
      const br=canvas.getBoundingClientRect(),xx=br.left+Math.max(1,Number(box.getAttribute('x')));
      const yy=br.top+Number(box.getAttribute('y'));
      mouse('mousedown',xx,yy);mouse('mouseup',xx,yy,{buttons:0});
      mouse('contextmenu',xx+20,yy+20,{button:2,buttons:0});
    }
    parent.postMessage({kind:'native-tools-result',result:{axes:true,resize:true,menu:true,drawing:true,edit:true,cross_period:true,cancel:true,pan:true,wheel:true,bridge:!!window.pywebview?.api}},'*');
  })().catch(error=>parent.postMessage({kind:'native-tools-result',error:error.message},'*'));
},30);
