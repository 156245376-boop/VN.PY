'use strict';
const $ = id => document.getElementById(id);
const names = {idle:'未连接',connecting:'正在连接',ready:'已连接',waiting_data:'已连接',
  disconnected:'连接中断',stopping:'正在断开',stopped:'已断开',failed:'连接失败'};
let api, state={catalog:[],rows:[],favorites:[]}, selected=null, page=0, favoritesOnly=false;
let ticking=false,lastView='',exiting=false,pollTimer,workspace;
const favoriteQueue=[];
let favoriteSaving=false, favoriteVersion=0;
let favoriteContextSymbol=null;
let nativeLabelsReady=false;

const historyIssues={empty:'没有有效 K 线',invalid_bar:'存在无效 K 线',id_sequence:'K 线编号不连续',time_order:'时间重复或倒序',long_gap:'历史日期存在超过一个月的间隔，需要核实'};
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
function choose(symbol){selected=symbol;workspace?.choose(symbol);render();}
async function toggleFavorite(symbol){favoriteQueue.push(symbol);if(favoriteSaving)return;
  favoriteSaving=true;favoriteVersion++;
  try{while(favoriteQueue.length){const current=favoriteQueue.shift();
    const values=state.favorites.includes(current)?state.favorites.filter(s=>s!==current):[...state.favorites,current];
    try{const result=await api.set_favorites(values);notice(result.reason);
      if(result.ok){state.favorites=values;lastView='';render()}}
    catch(_){notice('自选保存未完成，请重试。')}}
  }finally{favoriteSaving=false;favoriteVersion++;render()}}
function favoriteLabel(symbol){return state.favorites.includes(symbol)?'★ 取消自选':'☆ 添加自选'}
function renderFavoriteActions(){
  const item=state.catalog.find(row=>row.continuous===favoriteContextSymbol);
  $('market-context-name').textContent=item?labels.productName(item):'';
  $('market-context-favorite').textContent=favoriteLabel(favoriteContextSymbol);
  $('market-context-favorite').disabled=favoriteSaving||!item;
}
function closeFavoriteMenu(){$('market-context-menu').hidden=true;favoriteContextSymbol=null}
function showFavoriteMenu(event,symbol){event.preventDefault();event.stopPropagation();
  favoriteContextSymbol=symbol;renderFavoriteActions();const menu=$('market-context-menu');menu.hidden=false;
  const rect=menu.getBoundingClientRect();
  menu.style.left=Math.max(4,Math.min(event.clientX,innerWidth-rect.width-8))+'px';
  menu.style.top=Math.max(4,Math.min(event.clientY,innerHeight-rect.height-8))+'px';
}
function render(){if(exiting)return;const current=workspace?.getConfig();if(current)selected=current.panes.find(p=>p.id===current.active)?.continuous;const all=filtered(),pages=Math.max(1,Math.ceil(all.length/40));page=Math.min(page,pages-1);
  const visible=all.slice(page*40,page*40+40),quotes=new Map(state.rows.map(r=>[r.continuous,r]));
  $('market-rows').replaceChildren();$('empty').hidden=visible.length>0;
  for(const item of visible){const q=quotes.get(item.continuous)||{},row=document.createElement('tr');
    row.dataset.symbol=item.continuous;if(item.continuous===selected)row.className='selected';row.onclick=()=>choose(item.continuous);
    row.oncontextmenu=event=>showFavoriteMenu(event,item.continuous);
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
  renderFavoriteActions();
  workspace?.update({...state,visible_symbols:visible.map(r=>r.continuous),favoriteSaving,
    chart_url:nativeLabelsReady?state.chart_url:null});
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
$('market-context-favorite').onclick=()=>{const symbol=favoriteContextSymbol;closeFavoriteMenu();
  if(state.catalog.some(row=>row.continuous===symbol))toggleFavorite(symbol)};
document.addEventListener('mousedown',event=>{if(!$('market-context-menu').contains(event.target))closeFavoriteMenu()});
addEventListener('keydown',event=>{if(event.key==='Escape')closeFavoriteMenu()});
addEventListener('scroll',closeFavoriteMenu,true);addEventListener('resize',closeFavoriteMenu);addEventListener('blur',closeFavoriteMenu);
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
  const show=['home','market'].includes(view);$('market-layout').hidden=!show;
  $('chart-workspace').hidden=!show;workspace?.setVisible(show);
  $('page-title').textContent={home:'研究工作台',market:'行情与品种',research:'策略研究与模拟',news:'新闻与事件',settings:'设置与资源'}[view]};
addEventListener('qf-native-labels-ready',()=>{nativeLabelsReady=true;if(api)render()});
addEventListener('qf-native-labels-error',()=>notice('图表适配未能准备完成，请重新打开工作台。'));
window.qfPrepareExit=()=>{if(exiting)return 'qf-exit-pending';exiting=true;clearInterval(pollTimer);$('password').value='';
  document.querySelectorAll('button,input,select').forEach(e=>e.disabled=true);notice('正在保存布局并退出，请稍候…');
  Promise.resolve(workspace?.prepareExit?.()||workspace?.flush()).finally(()=>{workspace?.dispose();window.qfExitReady=true;});return 'qf-exit-pending';};
addEventListener('pywebviewready',async()=>{api=window.pywebview.api;
  try{await refreshLogin(true);const saved=await api.get_workspace(),indicators=await api.get_indicators();
    QfIndicatorState.install(indicators.catalog,indicators.defaults);
    workspace=QfChartWorkspace.create($('chart-workspace'),{config:saved.workspace,indicators,
      onIndicatorSubmit:r=>api.submit_indicator_calculation(r),onIndicatorPoll:ids=>api.poll_indicator_calculations(ids),onIndicatorSave:c=>api.save_indicators(c),
      onConfig:config=>api.save_workspace(config),onView:panes=>{const all=filtered(),rows=all.slice(page*40,page*40+40);return api.set_workspace(rows.map(r=>r.continuous),panes)},
      onFavorite:toggleFavorite,onNotice:notice,onSelection:symbol=>{selected=symbol;render();}});
    if(saved.issue)notice(saved.issue);
    if(indicators.issue)notice(indicators.issue);
  }catch(_){notice('工作区暂时无法读取，请重新打开软件。');}
  if(!exiting){tick();pollTimer=setInterval(tick,700)}
});
