// 从实际原生缓存导出有限业务字段，不接触认证或创建订阅。
(() => {
  'use strict';
  function snapshot(chart,request){
    if(!chart?.mainSeries?.data||chart.symbol!==request.symbol)return {issue:'等待当前图表数据'};
    const all=QfNativeTools.intervals(chart),range=chart.chartCtrl.range;
    const visible=all.filter(r=>r.id>=Math.max(0,Math.ceil(range.leftId))&&r.id<=Math.floor(range.rightId));
    if(!visible.length)return {issue:'当前视图没有有效 K 线'};
    const a=all.findIndex(r=>r.id===visible[0].id),b=all.findIndex(r=>r.id===visible.at(-1).id);
    let first=Math.max(0,a-1000),last=b;
    for(const item of request.settings.items){const r=item.params.range;
      if(item.type!=='vp'||!item.visible||item.params.mode!=='fixed'||!r||r.symbol!==chart.symbol)continue;
      const start=all.findIndex(row=>BigInt(Math.trunc(row.end))>BigInt(r.start_ns));
      const end=all.findLastIndex(row=>BigInt(Math.trunc(row.start))<BigInt(r.end_ns));
      if(start>=0&&end>=start&&Math.max(last,end)-Math.min(first,start)+1<=20000){first=Math.min(first,start);last=Math.max(last,end);}}
    if(last-first+1>20000)return {issue:'可见范围与预热超过 20000 根，请缩小范围'};
    const rows=all.slice(first,last+1).map(({id})=>{const r=chart.mainSeries.data[id];return {id,
      time_ns:String(Math.trunc(r.datetime)),open:r.open,high:r.high,low:r.low,close:r.close,volume:r.volume,close_oi:r.close_oi};});
    if(rows.some((r,i)=>['open','high','low','close','volume','close_oi'].some(k=>!Number.isFinite(r[k])||r[k]<0)||i&&r.id!==rows[i-1].id+1))return {issue:'指标范围存在无效柱或缺柱'};
    return {rows,visible:[visible[0].id,visible.at(-1).id],price_tick:chart.price_ticks,
      coverage_end_ns:String(Math.trunc(all[last].end))};
  }
  window.QfNativeIndicatorData={snapshot};
})();
