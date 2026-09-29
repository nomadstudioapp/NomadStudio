window.openJourneyFolderAccess = (function folderAccessService() {
  const DB_NAME = 'openjourney-folder-access-db';
  const STORE_NAME = 'kv';
  const DB_VERSION = 1;
  const HANDLE_KEY = 'output-directory-handle';
  const FILE_SYSTEM_UNSUPPORTED_MESSAGE = 'File System Access API not supported in this browser. In Brave, enable it at brave://flags/#file-system-access-api and restart the browser.';

  function isSupported() {
    return typeof window !== 'undefined' && 'showDirectoryPicker' in window && 'indexedDB' in window;
  }

  function openDb() {
    return new Promise((resolve, reject) => {
      if (!isSupported()) {
        reject(new Error(FILE_SYSTEM_UNSUPPORTED_MESSAGE));
        return;
      }

      const request = window.indexedDB.open(DB_NAME, DB_VERSION);
      request.onerror = () => reject(request.error || new Error(tF('Cannot open IndexedDB.')));
      request.onupgradeneeded = () => {
        const db = request.result;
        if (!db.objectStoreNames.contains(STORE_NAME)) {
          db.createObjectStore(STORE_NAME);
        }
      };
      request.onsuccess = () => resolve(request.result);
    });
  }

  async function setHandle(handle) {
    const db = await openDb();
    return new Promise((resolve, reject) => {
      const tx = db.transaction(STORE_NAME, 'readwrite');
      const store = tx.objectStore(STORE_NAME);
      const req = store.put(handle, HANDLE_KEY);

      req.onerror = () => {
        db.close();
        reject(req.error || new Error(tF('Failed saving folder handle.')));
      };
      tx.oncomplete = () => {
        db.close();
        resolve();
      };
      tx.onerror = () => {
        db.close();
        reject(tx.error || new Error(tF('Folder handle transaction failed.')));
      };
    });
  }

  async function getHandle() {
    const db = await openDb();
    return new Promise((resolve, reject) => {
      const tx = db.transaction(STORE_NAME, 'readonly');
      const store = tx.objectStore(STORE_NAME);
      const req = store.get(HANDLE_KEY);

      req.onerror = () => {
        db.close();
        reject(req.error || new Error(tF('Failed reading folder handle.')));
      };
      req.onsuccess = () => {
        db.close();
        resolve(req.result || null);
      };
    });
  }

  async function clearHandle() {
    const db = await openDb();
    return new Promise((resolve, reject) => {
      const tx = db.transaction(STORE_NAME, 'readwrite');
      const store = tx.objectStore(STORE_NAME);
      const req = store.delete(HANDLE_KEY);

      req.onerror = () => {
        db.close();
        reject(req.error || new Error(tF('Failed clearing folder handle.')));
      };
      tx.oncomplete = () => {
        db.close();
        resolve();
      };
      tx.onerror = () => {
        db.close();
        reject(tx.error || new Error(tF('Clear transaction failed.')));
      };
    });
  }

  async function queryPermission(handle, mode = 'readwrite') {
    if (!handle) return 'prompt';
    if (!handle.queryPermission) return 'prompt';
    return handle.queryPermission({ mode });
  }

  async function requestPermission(handle, mode = 'readwrite') {
    if (!handle) return 'prompt';
    if (!handle.requestPermission) return 'prompt';
    return handle.requestPermission({ mode });
  }

  async function pickDirectory() {
    if (!isSupported()) {
      throw new Error(FILE_SYSTEM_UNSUPPORTED_MESSAGE);
    }

    const handle = await window.showDirectoryPicker({ mode: 'readwrite' });
    await setHandle(handle);
    return handle;
  }

  async function dataUrlToBlob(dataUrl) {
    const response = await fetch(dataUrl);
    return response.blob();
  }

  function sanitizeFileName(name) {
    return String(name || 'image').replace(/[\\/:*?"<>|]/g, '-');
  }

  async function writeDataUrlFile(fileName, dataUrl) {
    const handle = await getHandle();
    if (!handle) {
      throw new Error(tF('No folder selected. Please choose a folder in Settings.'));
    }

    let permission = await queryPermission(handle, 'readwrite');
    if (permission !== 'granted') {
      permission = await requestPermission(handle, 'readwrite');
    }
    if (permission !== 'granted') {
      throw new Error(tF('Folder permission denied by browser.'));
    }

    const blob = await dataUrlToBlob(dataUrl);
    const writableHandle = await handle.getFileHandle(sanitizeFileName(fileName), { create: true });
    const writable = await writableHandle.createWritable();
    await writable.write(blob);
    await writable.close();
  }

  return {
    isSupported,
    pickDirectory,
    getHandle,
    clearHandle,
    queryPermission,
    requestPermission,
    writeDataUrlFile,
  };
})();
