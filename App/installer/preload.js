const { contextBridge, ipcRenderer } = require('electron')

contextBridge.exposeInMainWorld('api', {
  checkStatus:          () => ipcRenderer.invoke('check-status'),
  installLibreOffice:   () => ipcRenderer.invoke('install-libreoffice'),
  installRequirements:  () => ipcRenderer.invoke('install-requirements'),
  createShortcut:       () => ipcRenderer.invoke('create-shortcut'),
  launchApp:            () => ipcRenderer.invoke('launch-app'),
  windowClose:          () => ipcRenderer.send('window-close'),
})
