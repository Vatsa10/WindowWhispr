// Turning a real key press into the name the hotkey hook matches on.
//
// The browser reports `event.code`, a physical-key identifier; the Python hook
// matches on the `keyboard` library's own names. This is the translation, kept
// pure and in one place so it can be tested without a keyboard.
//
// Physical codes rather than `event.key`: `event.key` for Right Ctrl is
// "Control", identical to Left Ctrl, and binding the talk key to something
// that reports the same name as a modifier you use constantly is how you end
// up dictating every time you copy something.

const BY_CODE = {
  ControlRight: "right ctrl",
  ControlLeft: "left ctrl",
  AltRight: "right alt",
  AltLeft: "left alt",
  ShiftRight: "right shift",
  ShiftLeft: "left shift",
  CapsLock: "caps lock",
  ScrollLock: "scroll lock",
  NumLock: "num lock",
  Pause: "pause",
  ContextMenu: "menu",
  Insert: "insert",
  Home: "home",
  End: "end",
  PageUp: "page up",
  PageDown: "page down",
  Escape: "esc",
  Backquote: "`",
  Backslash: "\\",
};

// Keys that would break the keyboard if held for a sentence. Mirrors
// core/web/keys.py -- both ends refuse the same set, because the page is not
// the only way a config value can arrive.
const FORBIDDEN = new Set([
  "space", "enter", "backspace", "tab", "delete",
  "ctrl", "left ctrl", "alt", "left alt", "shift", "left shift",
  "windows", "left windows", "right windows",
  "up", "down", "left", "right",
]);

export function keyName(event) {
  const code = event.code || "";
  if (BY_CODE[code]) return BY_CODE[code];
  if (/^F\d{1,2}$/.test(code)) return code.toLowerCase();
  if (/^Key[A-Z]$/.test(code)) return code.slice(3).toLowerCase();
  if (/^Digit\d$/.test(code)) return code.slice(5);
  if (/^Numpad/.test(code)) return "num " + code.slice(6).toLowerCase();
  // Fall back to the logical key, lowercased. Better a name that might work
  // than nothing at all.
  return (event.key || "").toLowerCase();
}

export function isUsable(name) {
  const cleaned = (name || "").trim().toLowerCase();
  if (!cleaned || FORBIDDEN.has(cleaned)) return false;
  // A single character would swallow that letter everywhere else.
  return cleaned.length > 1;
}

export function describeKey(name, suggestions) {
  const cleaned = (name || "").trim().toLowerCase();
  const known = (suggestions || []).find((k) => k.value === cleaned);
  if (known) return known.label;
  if (!cleaned) return "";
  return cleaned.replace(/\b\w/g, (c) => c.toUpperCase());
}
