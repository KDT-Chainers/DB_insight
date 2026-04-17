const { contextBridge, ipcRenderer, webFrame } = require('electron')

// 앱 로드 즉시 저장된 zoom 적용 (React 렌더링 전에 실행되므로 깜빡임 없음)
try {
  const savedScale = parseFloat(localStorage.getItem('ui-scale') || '0.8')
  if (!isNaN(savedScale) && savedScale > 0) {
    webFrame.setZoomFactor(savedScale)
  }
} catch (_) {}

contextBridge.exposeInMainWorld('electronAPI', {
  selectFolder:   () => ipcRenderer.invoke('select-folder'),
  windowMinimize: () => ipcRenderer.send('window-minimize'),
  windowMaximize: () => ipcRenderer.send('window-maximize'),
  windowClose:    () => ipcRenderer.send('window-close'),
  // webFrame은 renderer 프로세스 모듈이라 IPC 없이 직접 호출 가능
  setZoom: (factor) => webFrame.setZoomFactor(factor),
})
