(()=>{if(parent===window)return;
          const OriginalBigInt=BigInt;window.__bigCalls=0;
          window.BigInt=Object.assign(function(value){window.__bigCalls++;return OriginalBigInt(value);},
            {asIntN:OriginalBigInt.asIntN,asUintN:OriginalBigInt.asUintN});
          setInterval(()=>{
          if(!window.__qfReplay)return;const chart=window.QfNativeHistory?.getChart?.();
          parent.postMessage({kind:'research-graph-probe',fills:document.querySelectorAll('[data-fill]').length,
            plots:Object.keys(chart?.plots||{}).filter(k=>k.startsWith('qf_replay_ma_')).length,
            bridge:!!window.pywebview?.api,bigints:window.__bigCalls,history:window.QfNativeHistory?.inspect?.(),
            invalid:[...document.querySelectorAll('[data-fill]')].some(e=>e.getAttribute('d').includes('NaN'))},'*');
        },200);})();
