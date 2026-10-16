'use strict';
(() => {
  const exchanges={SHFE:'上海期货交易所',DCE:'大连商品交易所',CZCE:'郑州商品交易所',
    CFFEX:'中国金融期货交易所',INE:'上海国际能源交易中心',GFEX:'广州期货交易所'};
  function productName(item){return (item?.name||'').replace(/(?:主力连续合约|主力连续|主连|连续合约)$/,'')||item?.product||'名称待确认'}
  function contractName(symbol,catalog){
    const match=/^(?:KQ\.(m|i)@)?(SHFE|DCE|CZCE|CFFEX|INE|GFEX)\.([A-Za-z]+)(\d{3,4})?$/.exec(symbol||'');
    if(!match)return symbol||'等待合约信息';
    const [,kind,exchange,product,delivery]=match;
    const item=catalog.find(row=>row.exchange===exchange&&row.product.toLowerCase()===product.toLowerCase());
    if(!item||!item.name||item.name===item.product)return '名称待确认（'+symbol+'）';
    const name=productName(item);
    if(kind==='m')return name+' · 主力连续合约';
    if(kind==='i')return name+' · 品种指数';
    if(!delivery)return name+' · 合约';
    const month=Number(delivery.slice(-2));
    if(month<1||month>12)return name+' · '+delivery+'合约';
    if(delivery.length===4)return name+' · 20'+delivery.slice(0,2)+'年'+month+'月合约';
    // 三位合约年份不包含十位数；保留代码，不能凭当前年份猜交割年。
    return name+' · '+delivery+'合约（'+month+'月）';
  }
  function translate(value,catalog){
    return value.replace(/workbench_entry\.py/g,'主力行情 · 只读观察')
      .replace(/py文件/g,'行情程序')
      .replace(/(?:KQ\.[mi]@)?(?:SHFE|DCE|CZCE|CFFEX|INE|GFEX)\.[A-Za-z]+\d{0,4}\b/g,
        symbol=>contractName(symbol,catalog))
      .replace(/\b(\d+)([mhd])\b/g,(_,number,unit)=>number+{m:'分钟',h:'小时',d:'天'}[unit]);
  }
  window.QfLabels={productName,contractName,translate,exchangeName:code=>exchanges[code]||code};
})();
