/* Nomad Studio — browser storage scoped to the active profile.
 *
 * Every page keeps things in localStorage/sessionStorage (prompt history,
 * recent generations, flow parameters, the task queue, the Sessions cache…)
 * under fixed keys, so every profile on the same browser saw the same data —
 * a Vanish Session included. Fixing each key in ~20 files would leak again
 * the next time someone adds one, so this wraps Storage itself, before any
 * other script runs:
 *
 * - a regular profile's keys become  "u:<viewer id>:<key>";
 * - Vanish uses sessionStorage only (nothing written to disk), under a token
 *   that is new every time Vanish is entered ("v:<token>:<key>"), so it never
 *   sees another profile's or an earlier Vanish's data; entering any other
 *   profile wipes Vanish's leftovers;
 * - no active profile (profile picker, setup): "anon:<key>";
 * - SHARED keys are device preferences (language, theme, zoom…) and stay as
 *   they are for everyone;
 * - old unscoped keys from before this existed belong to nobody we can tell,
 *   so they are removed once instead of being handed to whoever logs in.
 *
 * window.NOMAD_VIEWER = { id, vanish, token } is written by the server just
 * before this script (layout/base.html, app/__init__.py inject_storage_scope).
 */
(function () {
  'use strict';

  var proto = window.Storage && window.Storage.prototype;
  if (!proto || proto.__nomadScoped) return;

  var ls;
  var ss;
  try {
    ls = window.localStorage;
    ss = window.sessionStorage;
  } catch (e) {
    return; // storage blocked by the browser: nothing to scope
  }

  var nativeGet = proto.getItem;
  var nativeSet = proto.setItem;
  var nativeRemove = proto.removeItem;
  var nativeKey = proto.key;
  var lengthOf = Object.getOwnPropertyDescriptor(proto, 'length').get;

  // Device-level preferences, not personal data.
  var SHARED = {
    'oj-lang-v1': 1,
    'oj-theme-v1': 1,
    'ns-card-zoom-step-v2': 1,
    'oj-ncf-grid-zoom-v1': 1,
    'ns-album-card-zoom-step': 1,
    'ns-agent-album-card-zoom-step': 1,
    'oj-library-grid-zoom-v1': 1,
    'oj-create-gallery-zoom-v1': 1,
    'oj-explore-thumb-min-v1': 1,
    'ns-filters-hidden': 1,
    'ns-session-sidebar-hidden': 1,
    'ns-video-caption-v1': 1,
    'openjourney_model_advanced_cache_v1': 1,
    'ns-storage-scope-v1': 1
  };
  var MIGRATED_FLAG = 'ns-storage-scope-v1';

  var viewer = window.NOMAD_VIEWER || {};
  var vanish = !!viewer.vanish;
  var prefix = vanish
    ? 'v:' + String(viewer.token || 'x') + ':'
    : (viewer.id ? 'u:' + String(viewer.id) + ':' : 'anon:');

  function isShared(key) { return Object.prototype.hasOwnProperty.call(SHARED, String(key)); }
  function isScoped(key) { return /^(u:|v:|anon:)/.test(key); }
  function keysOf(store) {
    var out = [];
    var n = lengthOf.call(store);
    for (var i = 0; i < n; i++) out.push(nativeKey.call(store, i));
    return out;
  }

  try {
    // One-time: drop legacy unscoped personal data.
    if (nativeGet.call(ls, MIGRATED_FLAG) !== '1') {
      keysOf(ls).forEach(function (k) { if (!isShared(k) && !isScoped(k)) nativeRemove.call(ls, k); });
      nativeSet.call(ls, MIGRATED_FLAG, '1');
    }
    // sessionStorage lives per tab: unscoped entries can only be legacy ones.
    keysOf(ss).forEach(function (k) { if (!isShared(k) && !isScoped(k)) nativeRemove.call(ss, k); });
    // Vanish leaves nothing behind: any other profile (or a new Vanish entry,
    // with a new token) removes earlier Vanish data from this tab.
    keysOf(ss).forEach(function (k) { if (k.indexOf('v:') === 0 && k.indexOf(prefix) !== 0) nativeRemove.call(ss, k); });
    keysOf(ls).forEach(function (k) { if (k.indexOf('v:') === 0) nativeRemove.call(ls, k); });
  } catch (e) {
    // quota or privacy errors: scoping below still applies
  }

  // Vanish never writes to disk: its "localStorage" is this tab's sessionStorage.
  function storeFor(store) { return vanish && store === ls ? ss : store; }

  proto.getItem = function (key) {
    if (isShared(key)) return nativeGet.call(this, key);
    return nativeGet.call(storeFor(this), prefix + key);
  };
  proto.setItem = function (key, value) {
    if (isShared(key)) return nativeSet.call(this, key, value);
    return nativeSet.call(storeFor(this), prefix + key, value);
  };
  proto.removeItem = function (key) {
    if (isShared(key)) return nativeRemove.call(this, key);
    return nativeRemove.call(storeFor(this), prefix + key);
  };
  proto.__nomadScoped = true;
})();
