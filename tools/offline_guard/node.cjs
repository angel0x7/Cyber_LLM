// Preload only for offline replay. Provider packages install in a separate step.
const net = require('node:net');
const dns = require('node:dns');
const fs = require('node:fs');
const path = require('node:path');
function deny() { throw new Error('Phase 1A forbids network access'); }
net.Socket.prototype.connect = deny;
dns.lookup = deny;
dns.resolve = deny;
function check(file) {
  if (typeof file === 'string' && path.basename(file) === '.env') {
    const error = new Error('Phase 1A forbids reading private .env files');
    error.code = 'ENOENT';
    throw error;
  }
}
for (const name of ['readFileSync', 'readFile', 'openSync', 'open']) {
  const original = fs[name];
  fs[name] = function(file, ...args) { check(file); return original.call(this, file, ...args); };
}
for (const name of ['readFile', 'open']) {
  const original = fs.promises[name];
  fs.promises[name] = async function(file, ...args) { check(file); return original.call(this, file, ...args); };
}
