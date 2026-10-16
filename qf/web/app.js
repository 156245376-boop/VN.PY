'use strict';
const $ = id => document.getElementById(id);
const names = {idle:'等待连接',connecting:'正在连接',ready:'行情已就绪',waiting_data:'等待行情数据',
  disconnected:'行情连接中断',stopping:'正在断开，请稍候',stopped:'已断开',failed:'连接未完成'};
let api, state={catalog:[],rows:[],favorites:[]}, selected=null, page=0, favoritesOnly=false;
let ticking=false, pending=null, sending=false, lastView='', currentChart='';
const favoriteQueue=[];
let favoriteSaving=false, favoriteVersion=0;
let nativeLabelsReady=false;
const labels=window.QfLabels;
const text = (tag,value,cls) => {const e=document.createElement(tag); e.textContent=value; if(cls)e.className=cls;return e};
const number = (value,digits=0) => value===null||value===undefined?'—':Number(value).toLocaleString('zh-CN',{maximumFractionDigits:digits});
const notice = message => {$('notice').textContent=message||''};
function filtered(){const query=$('search').value.trim().toLowerCase(),exchange=$('exchange').value;
  return state.catalog.filter(r=>(!exchange||r.exchange===exchange)&&(!favoritesOnly||state.favorites.includes(r.continuous))&&
    [r.name,r.product,r.exchange,labels.exchangeName(r.exchange),r.continuous].join(' ').toLowerCase().includes(query));}
async function sendView(symbols){const key=JSON.stringify([symbols,selected]);if(key===lastView)return;
  lastView=key;pending={symbols,selected};if(sending)return;sending=true;
  try{while(pending){const request=pending;pending=null;const result=await api.set_view(request.symbols,request.selected);if(!result.ok)notice(result.reason)}}
  catch(_){notice('品种切换未完成，请检查连接。');lastView=''}finally{sending=false}}
function choose(symbol){selected=symbol;currentChart='';$('chart').hidden=true;$('chart').src='about:blank';
  render();}
async function toggleFavorite(symbol){favoriteQueue.push(symbol);if(favoriteSaving)return;
  favoriteSaving=true;favoriteVersion++;
  try{while(favoriteQueue.length){const current=favoriteQueue.shift();
    const values=state.favorites.includes(current)?state.favorites.filter(s=>s!==current):[...state.favorites,current];
    try{const result=await api.set_favorites(values);notice(result.reason);
      if(result.ok){state.favorites=values;lastView='';render()}}
    catch(_){notice('自选保存未完成，请重试。')}}
  }finally{favoriteSaving=false;favoriteVersion++}}
function render(){const all=filtered(),pages=Math.max(1,Math.ceil(all.length/40));page=Math.min(page,pages-1);
  const visible=all.slice(page*40,page*40+40),quotes=new Map(state.rows.map(r=>[r.continuous,r]));
  $('market-rows').replaceChildren();$('empty').hidden=visible.length>0;
  for(const item of visible){const q=quotes.get(item.continuous)||{},row=document.createElement('tr');
    row.dataset.symbol=item.continuous;if(item.continuous===selected)row.className='selected';row.onclick=()=>choose(item.continuous);
    const favorite=text('button',state.favorites.includes(item.continuous)?'★':'☆',state.favorites.includes(item.continuous)?'saved':'');
    favorite.title='添加或移除自选';favorite.onclick=event=>{event.stopPropagation();toggleFavorite(item.continuous)};
    const star=document.createElement('td');star.append(favorite);row.append(star);
    const name=text('td',labels.productName(item));name.append(text('small',labels.exchangeName(item.exchange)+' · '+item.product));row.append(name);
    const actual=text('td',q.underlying?labels.contractName(q.underlying,state.catalog):'等待主力合约');
    if(q.underlying)actual.append(text('small',q.underlying));
    row.append(actual,text('td',number(q.last_price,3)),
      text('td',q.change_percent==null?'—':number(q.change_percent,2)+'%',q.change_percent>0?'up':q.change_percent<0?'down':''),
      text('td',number(q.volume)),text('td',number(q.open_interest)),text('td',q.quote_time?q.quote_time.slice(11,19):'尚无行情'));
    $('market-rows').append(row);}
  $('count').textContent=all.length+' 个品种';$('page').textContent=(page+1)+' / '+pages;
  $('prev').disabled=page===0;$('next').disabled=page+1>=pages;
  $('catalog-note').textContent=state.cache_state==='live'?'目录来自当前账户 · 报价以右侧时间为准':state.catalog.length?'上次保存的品种目录 · 连接后更新':'尚无本机目录，请先连接';
  $('favorite-count').textContent=state.favorites.length;$('favorites').replaceChildren();
  for(const symbol of state.favorites){const item=state.catalog.find(r=>r.continuous===symbol),q=quotes.get(symbol)||{};
    const row=text('div','', 'favorite'),label=text('div',item?labels.productName(item):symbol);
    label.append(text('small',labels.contractName(q.underlying||symbol,state.catalog)));label.title=q.underlying||symbol;
    row.append(label,text('span',number(q.last_price,2)));row.onclick=()=>choose(symbol);
    const remove=text('button','×');remove.title='移除自选';remove.onclick=event=>{event.stopPropagation();toggleFavorite(symbol)};row.append(remove);$('favorites').append(row)}
  if(!state.favorites.length)$('favorites').append(text('p','点击品种旁的 ☆，建立自己的观察列表。'));
  const item=state.catalog.find(r=>r.continuous===selected),quote=quotes.get(selected);
  $('chart-title').textContent=item?labels.productName(item)+' · 行情图':'选择一个品种查看行情图';
  $('chart-detail').textContent=item?'观察品种：'+labels.contractName(item.continuous,state.catalog)+'；当前主力：'+
    (quote?.underlying?labels.contractName(quote.underlying,state.catalog):'等待服务确认'):'选择品种后显示当前主力合约的中文名称与交割月份';
  $('chart-detail').title=item?item.continuous+' → '+(quote?.underlying||'等待确认'):'';
  const address=nativeLabelsReady&&state.selected===selected&&/^http:\/\/127\.0\.0\.1:\d{1,5}\/?$/.test(state.chart_url||'')?state.chart_url:'';
  if(address!==currentChart){currentChart=address;$('chart').src=address||'about:blank'}
  $('chart').hidden=!address;$('chart-placeholder').hidden=!!address;
  if(api&&state.catalog.length)sendView(visible.map(r=>r.continuous));
}
async function tick(){if(ticking)return;ticking=true;const version=favoriteVersion;try{const incoming=await api.get_state();
  if(favoriteSaving||version!==favoriteVersion)incoming.favorites=state.favorites;
  state=incoming;if(!selected)selected=state.selected;
  $('status').textContent=names[state.status]||'状态待核实';
  $('login').disabled=['connecting','ready','waiting_data','disconnected','stopping'].includes(state.status);
  $('disconnect').disabled=['idle','stopped','failed'].includes(state.status);
  $('heartbeat').textContent='程序心跳 · '+state.heartbeat_seconds+' 秒';
  $('connection-note').textContent=state.reason||'主力映射与报价均以服务返回为准';if(state.issue)notice(state.issue);render();
}catch(_){notice('窗口状态读取未完成，请稍候。')}finally{ticking=false}}
$('login-form').onsubmit=async event=>{event.preventDefault();let password=$('password').value;
  const user=$('user').value.trim();$('password').value='';$('login').disabled=true;
  try{const result=await api.login(user,password);notice(result.reason);selected=null;lastView='';await tick()}
  catch(_){notice('连接未完成，请核对本机环境。');$('login').disabled=false}finally{password=null}};
$('disconnect').onclick=async()=>{notice((await api.disconnect()).reason);await tick()};
for(const id of ['search','exchange'])$(id).addEventListener(id==='search'?'input':'change',()=>{page=0;render()});
$('prev').onclick=()=>{page--;render()};$('next').onclick=()=>{page++;render()};
$('only-favorites').onclick=()=>{favoritesOnly=!favoritesOnly;$('only-favorites').textContent=favoritesOnly?'查看全部':'只看自选';page=0;render()};
for(const button of document.querySelectorAll('[data-resource]'))button.onclick=async()=>notice((await api.open_resource(button.dataset.resource)).reason);
for(const button of document.querySelectorAll('[data-view]'))button.onclick=()=>{const view=button.dataset.view;
  document.querySelectorAll('.nav').forEach(b=>b.classList.toggle('active',b===button));
  for(const section of ['home','research','news','settings'])$(section+'-panel').hidden=section!==view;
  $('market-layout').hidden=!['home','market'].includes(view);
  $('page-title').textContent={home:'研究工作台',market:'行情与品种',research:'策略研究与模拟',news:'新闻与事件',settings:'设置与资源'}[view]};
function sendChartLabels(){if(!currentChart)return;
  $('chart').contentWindow.postMessage({kind:'qf-chart-labels',catalog:state.catalog},new URL(currentChart).origin)}
$('chart').addEventListener('load',sendChartLabels);
addEventListener('message',event=>{if(currentChart&&event.source===$('chart').contentWindow&&
  event.origin===new URL(currentChart).origin&&event.data?.kind==='qf-chart-ready')sendChartLabels()});
addEventListener('qf-native-labels-ready',()=>{nativeLabelsReady=true;if(api)render()});
addEventListener('qf-native-labels-error',()=>notice('图表中文说明未能准备完成，请重新打开工作台。'));
addEventListener('pywebviewready',()=>{api=window.pywebview.api;tick();setInterval(tick,700)});
