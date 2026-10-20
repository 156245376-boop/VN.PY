// 天勤原生页面右上角“全屏/还原”固定位置验收；无账户桥接。
const toolbarStarted = Date.now();
const toolbarTimer = setInterval(() => {
  const chart = document.querySelector('.tq-top-view');
  if (!chart) return;
  const button = [...document.querySelectorAll('button,[role="button"],.ivu-checkbox-wrapper,label')]
    .find(node => /全屏|还原/.test((node.textContent || '').trim()));
  if (!button) return;
  if (button.classList.contains('qf-native-fullscreen')) {
    clearInterval(toolbarTimer);
    try {
      const b = button.getBoundingClientRect(), c = chart.getBoundingClientRect();
      if (button.classList.contains('qf-native-fullscreen') === false) throw Error('全屏按钮未标记');
      if (b.right > c.right - 4 || b.left < c.left + c.width * .7) throw Error('全屏按钮不在右上操作区');
      parent.postMessage({kind: 'native-toolbar-result', result: {
        pinned: true, bridge: !!window.pywebview?.api,
        left: b.left, right: b.right, chartLeft: c.left, chartRight: c.right, chartWidth: c.width,
      }}, '*');
    } catch (error) {
      parent.postMessage({kind: 'native-toolbar-result', error: error.message}, '*');
    }
    return;
  }
  if (Date.now() - toolbarStarted > 5000) {
    clearInterval(toolbarTimer);
    parent.postMessage({kind: 'native-toolbar-result', error: '全屏按钮未标记'}, '*');
  }
}, 50);
