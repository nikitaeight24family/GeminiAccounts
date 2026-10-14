const fs = require('fs');
const path = require('path');

class CredentialStore {
  constructor(file, encryption) { this.file = file; this.encryption = encryption; }
  read() {
    if (!fs.existsSync(this.file)) return {};
    return JSON.parse(this.encryption.decryptString(fs.readFileSync(this.file)));
  }
  get(email) { return this.read()[String(email).trim().toLowerCase()] || null; }
  filterInventory(rows) {
    const saved = new Set(Object.keys(this.read()).map(email => email.trim().toLowerCase()));
    return (rows || []).filter(row => saved.has(String(row.email || '').trim().toLowerCase()));
  }
  inventory(rows) {
    return Object.entries(this.read()).map(([email, credentials]) => ({
      email: credentials.email || email,
      password: credentials.password,
      secret: credentials.secret,
      areas: (rows || []).filter(row => String(row.email || '').trim().toLowerCase() === email.trim().toLowerCase())
    }));
  }
  update(email, credentials) {
    const rows = this.read();
    const key = String(email).trim().toLowerCase();
    const nextKey = credentials.email.trim().toLowerCase();
    if (!rows[key]) throw new Error('Automatic sign-in account no longer exists.');
    if (key !== nextKey && rows[nextKey]) throw new Error('This email already has saved sign-in data.');
    delete rows[key];
    rows[nextKey] = credentials;
    this.write(rows);
  }
  remove(email) {
    const rows = this.read();
    delete rows[String(email).trim().toLowerCase()];
    this.write(rows);
  }
  save(credentials) {
    const rows = this.read();
    rows[credentials.email.trim().toLowerCase()] = credentials;
    this.write(rows);
  }
  write(rows) {
    if (!this.encryption.isEncryptionAvailable()) throw new Error('Windows credential protection is unavailable.');
    fs.mkdirSync(path.dirname(this.file), {recursive:true});
    const temp = this.file + '.tmp';
    fs.writeFileSync(temp, this.encryption.encryptString(JSON.stringify(rows)));
    fs.renameSync(temp, this.file);
  }
}
module.exports = {CredentialStore};
