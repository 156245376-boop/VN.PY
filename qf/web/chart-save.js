// 单写入、合并尚未发送的中间布局；失败不得显示为已保存。
(() => {
  'use strict';
  function create(write,onResult){let latest=0,pending=null,working=null;
    function submit(config){pending={id:++latest,config:JSON.parse(JSON.stringify(config))};
      if(!working)working=drain().finally(()=>{working=null;if(pending)working=drain().finally(()=>{working=null;});});
      return working;
    }
    async function drain(){while(pending){const job=pending;pending=null;let result;
      try{result=await write(job.config);}catch(_){result={ok:false,reason:'布局未保存，请稍后重试。'};}
      if(job.id===latest)onResult(result);
    }}
    async function flush(){while(working)await working;}
    return {submit,flush};
  }
  window.QfLayoutSaves={create};
})();
