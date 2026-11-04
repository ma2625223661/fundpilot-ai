'use strict';

(function (root) {
  const KEY = 'fundpilot_sector_history_v1';
  const limit = rows => (Array.isArray(rows) ? rows : []).filter(r => r?.research_scope === 'sectors').slice(0, 20);

  function createHistoryStore(options = {}) {
    if (root.FundPilotCloud) {
      let queue = Promise.resolve();
      async function exchange(reportIds) {
        const response = await root.fetch('/api/me/history', reportIds === undefined ? {cache:'no-store',signal:AbortSignal.timeout(20000)} : {
          method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({report_ids:reportIds}),signal:AbortSignal.timeout(20000)
        });
        const value = await response.json();
        if (!response.ok) throw new Error(value.error || '个人研究记录同步失败');
        return limit(value.items);
      }
      return {
        load:async () => ({items:await exchange(), durable:true, backend:root.FundPilotCloud.mode === 'local'?'account':'cloud'}),
        save(rows) {
          const ids = limit(rows).map(row => row.as_of);
          const result = queue.then(async () => {
            const items = await exchange(ids);
            return {backend:root.FundPilotCloud.mode === 'local'?'account':'cloud', saved_count:items.length, limited:items.length < ids.length};
          });
          queue = result.catch(() => {}); return result;
        }
      };
    }
    const timeout = options.timeout ?? 5000;
    let database = options.database, storage = options.storage;
    try { if (!Object.prototype.hasOwnProperty.call(options, 'database')) database = root.indexedDB; } catch {}
    try { if (!Object.prototype.hasOwnProperty.call(options, 'storage')) storage = root.localStorage; } catch {}
    let opening, queue = Promise.resolve();
    function fallbackRead() {
      try { return limit(JSON.parse(storage?.getItem(KEY) || '[]')); } catch { return []; }
    }
    function open() {
      if (!database) return Promise.reject(new Error('database unavailable'));
      if (opening) return opening;
      opening = new Promise((resolve, reject) => {
        let settled = false;
        const timer = setTimeout(() => finish(new Error('database open timeout')), timeout);
        function finish(error, db) {
          if (settled) { if (db) db.close(); return; }
          settled = true; clearTimeout(timer);
          if (error) reject(error); else resolve(db);
        }
        let request;
        try { request = database.open('fundpilot-sector-history', 1); } catch (error) { finish(error); return; }
        request.onupgradeneeded = () => { if (!request.result.objectStoreNames.contains('reports')) request.result.createObjectStore('reports'); };
        request.onerror = () => finish(request.error || new Error('database open failed'));
        request.onblocked = () => finish(new Error('database upgrade blocked'));
        request.onsuccess = () => {
          const db = request.result;
          db.onversionchange = () => { db.close(); opening = undefined; };
          finish(null, db);
        };
      }).catch(error => { opening = undefined; throw error; });
      return opening;
    }
    async function transfer(mode, items) {
      const db = await open();
      return new Promise((resolve, reject) => {
        let value, transaction;
        try {
          transaction = db.transaction('reports', mode);
          const store = transaction.objectStore('reports');
          const request = mode === 'readonly' ? store.get('recent') : store.put(items, 'recent');
          request.onsuccess = () => { value = request.result; };
          transaction.oncomplete = () => resolve(value);
          transaction.onerror = transaction.onabort = () => reject(transaction.error || new Error('database transaction failed'));
        } catch (error) { reject(error); }
      });
    }
    async function load() {
      try {
        const stored = await transfer('readonly');
        return {items:stored === undefined ? fallbackRead() : limit(stored), durable:true};
      } catch { return {items:fallbackRead(), durable:false}; }
    }
    function save(rows) {
      const items = limit(rows);
      const operation = async () => {
        try {
          await transfer('readwrite', items);
          // The legacy value is removed only after the database transaction commits.
          try { storage?.removeItem(KEY); } catch {}
          return {saved_count:items.length, limited:false, backend:'indexedDB'};
        } catch {
          for (let count = items.length; count >= 0; count--) {
            try {
              if (!storage) throw new Error('storage unavailable');
              storage.setItem(KEY, JSON.stringify(items.slice(0, count)));
              return {saved_count:count, limited:count < items.length, backend:'localStorage'};
            } catch {}
          }
          return {saved_count:0, limited:true, backend:'memory'};
        }
      };
      const result = queue.then(operation, operation);
      queue = result.catch(() => {});
      return result;
    }
    return {load, save};
  }
  const api = {createHistoryStore};
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  root.SectorHistory = api;
})(typeof globalThis !== 'undefined' ? globalThis : this);
