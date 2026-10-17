'use strict';
const $ = id => document.getElementById(id);
const names = {idle:'未连接',connecting:'正在连接',ready:'已连接',waiting_data:'已连接',
  disconnected:'连接中断',stopping:'正在断开',stopped:'已断开',failed:'连接失败'};
let api, state={catalog:[],rows:[],favorites:[]}, selected=null, page=0, favoritesOnly=false;
let ticking=false, pending=null, sending=false, lastView='', currentChart='',exiting=false,pollTimer;
const favoriteQueue=[];
let favoriteSaving=false, favoriteVersion=0;
let nativeLabelsReady=false;
const labels=window.QfLabels;
let savedLogin={user:'',saved:false},loginStatus='';
const text = (tag,value,cls) => {const e=document.createElement(tag); e.textContent=value; if(cls)e.className=cls;return e};
const number = (value,digits=0) => value===null||value===undefined?'—':Number(value).toLocaleString('zh-CN',{maximumFractionDigits:digits});
const price=(value,unit)=>value==null?'—':number(value,3)+' '+(unit||'单位待确认');
const hands=value=>value==null?'—':number(value)+' 手';
const notice = message => {$('notice').textContent=message||''};
function passwordHint(){const available=savedLogin.saved&&$('user').value.trim()===savedLogin.user;
  $('password').required=!available;
  $('password').placeholder=available?'密码已保存，留空使用':'请输入快期密码'}
async function refreshLogin(fill=false){savedLogin=await api.get_login_state();
  if(fill)$('user').value=savedLogin.user;passwordHint();
  $('credential-note').textContent=savedLogin.issue||(savedLogin.saved?
    '账号密码已由 Windows 保存；密码留空即可连接。':'勾选后，连接成功会由 Windows 保存，下次无需再输入。')}
function filtered(){const query=$('search').value.trim().toLowerCase(),exchange=$('exchange').value;
  return state.catalog.filter(r=>(!exchange||r.exchange===exchange)&&(!favoritesOnly||state.favorites.includes(r.continuous))&&
    [r.name,r.product,r.exchange,labels.exchangeName(r.exchange),r.continuous].join(' ').toLowerCase().includes(query));}
async function sendView(symbols){if(exiting)return;const key=JSON.stringify([symbols,selected]);if(key===lastView)return;
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
function render(){if(exiting)return;const all=filtered(),pages=Math.max(1,Math.ceil(all.length/40));page=Math.min(page,pages-1);
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
    row.append(actual,text('td',price(q.last_price,q.price_unit||item.price_unit)),
      text('td',q.change_percent==null?'—':number(q.change_percent,2)+'%',q.change_percent>0?'up':q.change_percent<0?'down':''),
      text('td',hands(q.volume)),text('td',hands(q.open_interest)),text('td',q.quote_time?q.quote_time.slice(0,19):'尚无报价时间'));
    const dataState=text('td',q.data_state==='ready'?'报价已返回':q.data_state==='disconnected'?'连接中断':
      q.data_state==='waiting'?'暂无有效报价':'等待订阅',q.data_state==='ready'?'data-ready':'data-waiting');
    dataState.title=q.data_note||'未返回报价不等于价格为零；权限和合约状态需按服务结果核对';row.append(dataState);
    $('market-rows').append(row);}
  $('count').textContent=all.length+' 个品种';$('page').textContent=(page+1)+' / '+pages;
  const received=visible.filter(item=>quotes.get(item.continuous)?.last_price!=null).length;
  $('data-summary').textContent=state.connected===true?'当前页 '+received+' / '+visible.length+
    ' 个品种已返回价格；休市时显示最后收到的报价。绿灯表示连接正常。':
    state.status==='connecting'?'正在连接行情服务，请稍候。':'当前未连接，已有数值仅供核对末次数据。';
  $('prev').disabled=page===0;$('next').disabled=page+1>=pages;
  $('catalog-note').textContent=state.cache_state==='live'?'目录来自当前账户 · 报价以右侧时间为准':state.catalog.length?'上次保存的品种目录 · 连接后更新':'尚无本机目录，请先连接';
  $('favorite-count').textContent=state.favorites.length;$('favorites').replaceChildren();
  for(const symbol of state.favorites){const item=state.catalog.find(r=>r.continuous===symbol),q=quotes.get(symbol)||{};
    const row=text('div','', 'favorite'),label=text('div',item?labels.productName(item):symbol);
    label.append(text('small',labels.contractName(q.underlying||symbol,state.catalog)));label.title=q.underlying||symbol;
    row.append(label,text('span',price(q.last_price,q.price_unit||item?.price_unit)));row.onclick=()=>choose(symbol);
    const remove=text('button','×');remove.title='移除自选';remove.onclick=event=>{event.stopPropagation();toggleFavorite(symbol)};row.append(remove);$('favorites').append(row)}
  if(!state.favorites.length)$('favorites').append(text('p','点击品种旁的 ☆，建立自己的观察列表。'));
  const item=state.catalog.find(r=>r.continuous===selected),quote=quotes.get(selected);
  $('chart-title').textContent=item?labels.productName(item)+' · 行情图':'选择一个品种查看行情图';
  $('chart-detail').textContent=item?'观察品种：'+labels.contractName(item.continuous,state.catalog)+'；当前主力：'+
    (quote?.underlying?labels.contractName(quote.underlying,state.catalog):'等待服务确认'):'选择品种后显示当前主力合约的中文名称与交割月份';
  $('chart-detail').title=item?item.continuous+' → '+(quote?.underlying||'等待确认'):'';
  $('chart-units').textContent=item?'价格：'+(quote?.price_unit||item.price_unit||'单位待确认')+
    ' · 成交量：手 · 持仓量：手 · 时间：北京时间':'价格单位按品种显示 · 成交量和持仓量单位为手';
  const address=nativeLabelsReady&&state.selected===selected&&/^http:\/\/127\.0\.0\.1:\d{1,5}\/?$/.test(state.chart_url||'')?state.chart_url:'';
  if(address!==currentChart){currentChart=address;$('chart').src=address||'about:blank'}
  $('chart').hidden=!address;$('chart-placeholder').hidden=!!address;
  $('chart-placeholder').textContent=state.chart_status==='unavailable'?'当前合约K线未返回或读取失败，可切换其他品种；连接状态请看顶部指示灯。':
    state.connected===true?'正在载入所选品种的 K 线，请稍候。':'连接后将自动选择品种并载入 K 线。';
  $('expand-chart').disabled=!address;
  if(api&&state.catalog.length&&['ready','waiting_data','disconnected'].includes(state.status))sendView(visible.map(r=>r.continuous));
}
async function tick(){if(exiting||ticking)return;ticking=true;const version=favoriteVersion;try{const incoming=await api.get_state();
  if(exiting)return;
  if(favoriteSaving||version!==favoriteVersion)incoming.favorites=state.favorites;
  state=incoming;if(!selected)selected=state.selected||state.catalog.find(r=>r.product==='rb')?.continuous||state.catalog[0]?.continuous;
  if(loginStatus!==state.status){loginStatus=state.status;await refreshLogin()}
  $('status').textContent=names[state.status]||'状态待核实';
  $('status').dataset.light=['connecting','stopping'].includes(state.status)?'yellow':state.connected===true?'green':'red';
  $('login').disabled=['connecting','ready','waiting_data','disconnected','stopping'].includes(state.status);
  $('disconnect').disabled=['idle','stopped','failed'].includes(state.status);
  $('heartbeat').textContent='程序心跳 · '+state.heartbeat_seconds+' 秒';
  $('connection-note').textContent=state.reason||(state.connected===true?'行情服务已连接；各品种是否收到报价请看数据状态。':
    state.status==='connecting'?'正在登录并连接行情服务。':'点击连接行情后读取品种与报价。');if(state.issue)notice(state.issue);render();
}catch(_){notice('窗口状态读取未完成，请稍候。')}finally{ticking=false}}
$('login-form').onsubmit=async event=>{event.preventDefault();let password=$('password').value;
  const user=$('user').value.trim();$('password').value='';$('login').disabled=true;
  try{const result=await api.login(user,password,$('remember-login').checked);notice(result.ok?'':result.reason);
    selected=null;lastView='';await tick()}
  catch(_){notice('连接未完成，请核对本机环境。');$('login').disabled=false}finally{password=null}};
$('disconnect').onclick=async()=>{const result=await api.disconnect();notice(result.ok?'':result.reason);await tick()};
function expandChart(expanded){$('chart-card').classList.toggle('expanded',expanded);
  document.body.classList.toggle('chart-expanded',expanded);$('expand-chart').textContent=expanded?'还原 K 线（Esc）':'放大 K 线'}
$('expand-chart').onclick=()=>expandChart(!$('chart-card').classList.contains('expanded'));
addEventListener('keydown',event=>{if(event.key==='Escape')expandChart(false)});
$('user').addEventListener('input',passwordHint);
$('forget-login').onclick=async()=>{try{const result=await api.forget_login();notice(result.reason);
  if(result.ok){$('user').value='';$('password').value='';await refreshLogin()}}
  catch(_){notice('忘记账号密码未完成，请稍后重试。')}};
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
  const symbol=state.rows.find(row=>row.continuous===selected)?.underlying||'';
  $('chart').contentWindow.postMessage({kind:'qf-chart-labels',catalog:state.catalog,symbol},new URL(currentChart).origin)}
$('chart').addEventListener('load',sendChartLabels);
addEventListener('message',event=>{if(currentChart&&event.source===$('chart').contentWindow&&
  event.origin===new URL(currentChart).origin&&event.data?.kind==='qf-chart-ready')sendChartLabels()});
addEventListener('qf-native-labels-ready',()=>{nativeLabelsReady=true;if(api)render()});
addEventListener('qf-native-labels-error',()=>notice('图表中文说明未能准备完成，请重新打开工作台。'));
window.qfPrepareExit=()=>{exiting=true;clearInterval(pollTimer);pending=null;currentChart='';
  $('chart').src='about:blank';$('chart').hidden=true;$('password').value='';
  document.querySelectorAll('button,input,select').forEach(element=>element.disabled=true);
  notice('正在退出，请稍候…')};
addEventListener('pywebviewready',async()=>{api=window.pywebview.api;
  try{await refreshLogin(true)}catch(_){notice('已保存的账号暂时无法读取，请手动输入。')}
  if(!exiting){tick();pollTimer=setInterval(tick,700)}});
