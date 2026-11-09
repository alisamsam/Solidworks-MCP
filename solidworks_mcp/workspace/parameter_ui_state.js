/* Local edits are independent of the latest server snapshot. No persistence or CAD writes. */
class ParameterEditBuffer {
  constructor() { this.items = new Map(); }
  key(project, id) { return JSON.stringify([project, id]); }
  fingerprint(p) {
    return JSON.stringify([p.has_draft ?? p.draft_value != null, p.draft_value, p.observed_value,
      p.role, p.value_type, p.unit, p.minimum, p.maximum, p.choices, p.binding]);
  }
  get(project, id) { return this.items.get(this.key(project, id)); }
  stage(project, p, raw) {
    const previous = this.get(project, p.id);
    const entry = {raw, baseline: previous ? previous.baseline : this.fingerprint(p)};
    this.items.set(this.key(project, p.id), entry);
    return entry;
  }
  value(project, p) {
    const edit = this.get(project, p.id);
    if (edit) return edit.raw;
    const value = (p.has_draft ?? p.draft_value != null) ? p.draft_value : p.observed_value;
    return value == null ? '' : String(value);
  }
  conflicts(project, p) {
    const edit = this.get(project, p.id);
    return !!edit && edit.baseline !== this.fingerprint(p);
  }
  discard(project, id) { this.items.delete(this.key(project, id)); }
  clearIf(project, id, saved) { if (this.get(project, id) === saved) this.discard(project, id); }
  get size() { return this.items.size; }
}
if (typeof module !== 'undefined' && module.exports) module.exports = {ParameterEditBuffer};
