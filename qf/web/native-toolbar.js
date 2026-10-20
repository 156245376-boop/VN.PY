// 天勤原生页面“全屏/还原”右上角固定；不改 SDK 文件、不接入业务桥接。
(() => {
  'use strict';
  if (window.QfNativeToolbar) return;
  function findFullscreen(root) {
    for (const node of root.querySelectorAll('button,[role="button"],.ivu-checkbox-wrapper,label')) {
      if (/全屏|还原/.test((node.textContent || '').trim())) return node;
    }
    return null;
  }
  let wrapper = null;
  function pin(root = document) {
    const chart = root.querySelector('.tq-top-view');
    if (!chart) return null;
    const button = findFullscreen(chart);
    if (!button) return null;
    if (!wrapper || !chart.contains(wrapper)) {
      wrapper = document.createElement('div');
      wrapper.className = 'qf-native-top-actions';
      chart.appendChild(wrapper);
    }
    if (button.parentElement !== wrapper) wrapper.replaceChildren(button);
    button.classList.add('qf-native-fullscreen');
    return {button, group: wrapper};
  }
  window.QfNativeToolbar = {pin};
  setInterval(() => pin(), 500);
})();
