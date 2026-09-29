'use strict';
// Canvas Composer — minimal, dependency-free ZIP reader/writer.
//
// Save/Load are fully client-side (no server round trip — see cc-save.js),
// so the .zip itself has to be built and parsed in the browser. Entries are
// stored uncompressed (method 0): the payload is PNG image bytes, which are
// already entropy-coded, so DEFLATE would barely shrink them while adding a
// real dependency on CompressionStream/DecompressionStream. Standard ZIP
// local/central-directory/EOCD structure, readable by any zip tool.

window.CC = window.CC || {};

(function (CC) {
  var CRC_TABLE = (function () {
    var table = new Uint32Array(256);
    for (var n = 0; n < 256; n++) {
      var c = n;
      for (var k = 0; k < 8; k++) {
        c = (c & 1) ? (0xEDB88320 ^ (c >>> 1)) : (c >>> 1);
      }
      table[n] = c >>> 0;
    }
    return table;
  })();

  function crc32(bytes) {
    var crc = 0xFFFFFFFF;
    for (var i = 0; i < bytes.length; i++) {
      crc = CRC_TABLE[(crc ^ bytes[i]) & 0xFF] ^ (crc >>> 8);
    }
    return (crc ^ 0xFFFFFFFF) >>> 0;
  }

  // entries: [{ name: string, bytes: Uint8Array }] → Blob (application/zip)
  CC.zipCreate = function (entries) {
    var textEncoder = new TextEncoder();
    var localParts = [];
    var centralParts = [];
    var offset = 0;

    entries.forEach(function (entry) {
      var nameBytes = textEncoder.encode(entry.name);
      var data = entry.bytes;
      var crc = crc32(data);

      var localHeader = new DataView(new ArrayBuffer(30));
      localHeader.setUint32(0, 0x04034b50, true);
      localHeader.setUint16(4, 20, true);   // version needed
      localHeader.setUint16(6, 0, true);    // flags
      localHeader.setUint16(8, 0, true);    // method = stored
      localHeader.setUint16(10, 0, true);   // mod time
      localHeader.setUint16(12, 0x21, true); // mod date (arbitrary valid DOS date)
      localHeader.setUint32(14, crc, true);
      localHeader.setUint32(18, data.length, true); // compressed size
      localHeader.setUint32(22, data.length, true); // uncompressed size
      localHeader.setUint16(26, nameBytes.length, true);
      localHeader.setUint16(28, 0, true);   // extra length
      var localHeaderBytes = new Uint8Array(localHeader.buffer);

      localParts.push(localHeaderBytes, nameBytes, data);

      var centralHeader = new DataView(new ArrayBuffer(46));
      centralHeader.setUint32(0, 0x02014b50, true);
      centralHeader.setUint16(4, 20, true);  // version made by
      centralHeader.setUint16(6, 20, true);  // version needed
      centralHeader.setUint16(8, 0, true);   // flags
      centralHeader.setUint16(10, 0, true);  // method
      centralHeader.setUint16(12, 0, true);  // time
      centralHeader.setUint16(14, 0x21, true); // date
      centralHeader.setUint32(16, crc, true);
      centralHeader.setUint32(20, data.length, true);
      centralHeader.setUint32(24, data.length, true);
      centralHeader.setUint16(28, nameBytes.length, true);
      centralHeader.setUint16(30, 0, true);  // extra len
      centralHeader.setUint16(32, 0, true);  // comment len
      centralHeader.setUint16(34, 0, true);  // disk number
      centralHeader.setUint16(36, 0, true);  // internal attrs
      centralHeader.setUint32(38, 0, true);  // external attrs
      centralHeader.setUint32(42, offset, true); // local header offset
      var centralHeaderBytes = new Uint8Array(centralHeader.buffer);

      centralParts.push(centralHeaderBytes, nameBytes);

      offset += localHeaderBytes.length + nameBytes.length + data.length;
    });

    var centralStart = offset;
    var centralSize = centralParts.reduce(function (s, p) { return s + p.length; }, 0);

    var eocd = new DataView(new ArrayBuffer(22));
    eocd.setUint32(0, 0x06054b50, true);
    eocd.setUint16(4, 0, true);
    eocd.setUint16(6, 0, true);
    eocd.setUint16(8, entries.length, true);
    eocd.setUint16(10, entries.length, true);
    eocd.setUint32(12, centralSize, true);
    eocd.setUint32(16, centralStart, true);
    eocd.setUint16(20, 0, true);

    var allParts = localParts.concat(centralParts, [new Uint8Array(eocd.buffer)]);
    return new Blob(allParts, { type: 'application/zip' });
  };

  // ArrayBuffer → { [entryName]: Uint8Array }. Supports method 0 (stored,
  // what CC.zipCreate writes) and method 8 (deflate, in case a composition
  // was hand-edited/re-zipped with a tool that compresses).
  CC.zipRead = function (arrayBuffer) {
    var bytes = new Uint8Array(arrayBuffer);
    var view = new DataView(arrayBuffer);

    var eocdOffset = -1;
    var scanStart = Math.max(0, bytes.length - 22 - 65536);
    for (var i = bytes.length - 22; i >= scanStart; i--) {
      if (view.getUint32(i, true) === 0x06054b50) { eocdOffset = i; break; }
    }
    if (eocdOffset < 0) throw new Error(tF('Not a valid .zip file'));

    var entryCount = view.getUint16(eocdOffset + 10, true);
    var centralDirOffset = view.getUint32(eocdOffset + 16, true);
    var textDecoder = new TextDecoder();
    var result = {};
    var pos = centralDirOffset;

    for (var e = 0; e < entryCount; e++) {
      if (view.getUint32(pos, true) !== 0x02014b50) throw new Error(tF('Malformed zip central directory'));
      var method = view.getUint16(pos + 10, true);
      var compSize = view.getUint32(pos + 20, true);
      var nameLen = view.getUint16(pos + 28, true);
      var extraLen = view.getUint16(pos + 30, true);
      var commentLen = view.getUint16(pos + 32, true);
      var localOffset = view.getUint32(pos + 42, true);
      var name = textDecoder.decode(bytes.subarray(pos + 46, pos + 46 + nameLen));

      var localNameLen = view.getUint16(localOffset + 26, true);
      var localExtraLen = view.getUint16(localOffset + 28, true);
      var dataStart = localOffset + 30 + localNameLen + localExtraLen;
      var compData = bytes.subarray(dataStart, dataStart + compSize);

      if (method === 0) {
        result[name] = compData.slice();
      } else {
        throw new Error('Unsupported zip compression method (' + method + ') for "' + name + '"');
      }

      pos += 46 + nameLen + extraLen + commentLen;
    }
    return result;
  };
})(window.CC);
