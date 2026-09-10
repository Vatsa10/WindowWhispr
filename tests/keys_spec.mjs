// The browser half of key binding: a real key press into the name the Python
// hook matches on. Pure, so it runs without a keyboard or a browser.
import assert from "node:assert/strict";
import { keyName, isUsable, describeKey } from "../core/web/static/app/keys.js";

const press = (code, key) => ({ code, key: key ?? code });

// event.code, not event.key: both Ctrls report key "Control", and binding the
// talk key to something indistinguishable from the Ctrl in Ctrl+C would
// dictate every time you copied something.
assert.equal(keyName(press("ControlRight", "Control")), "right ctrl");
assert.equal(keyName(press("ControlLeft", "Control")), "left ctrl");
assert.notEqual(keyName(press("ControlRight", "Control")),
                keyName(press("ControlLeft", "Control")));

assert.equal(keyName(press("AltRight", "Alt")), "right alt");
assert.equal(keyName(press("CapsLock")), "caps lock");
assert.equal(keyName(press("ScrollLock")), "scroll lock");
assert.equal(keyName(press("ContextMenu")), "menu");
assert.equal(keyName(press("Pause")), "pause");
assert.equal(keyName(press("F13")), "f13");
assert.equal(keyName(press("F1")), "f1");
assert.equal(keyName(press("KeyA", "a")), "a");
assert.equal(keyName(press("Digit4", "4")), "4");
assert.equal(keyName(press("Escape")), "esc");

// An unknown code still yields something rather than nothing.
assert.equal(keyName(press("Lang1", "KanaMode")), "kanamode");

// The refusals mirror core/web/keys.py: both ends must agree, because the
// page is not the only way a value can reach the config.
for (const bad of ["space", "enter", "backspace", "tab", "ctrl", "left ctrl",
                   "shift", "alt", "up", "down", "left", "right", "a", "4", ""]) {
  assert.equal(isUsable(bad), false, `${bad} should be refused`);
}
for (const good of ["right ctrl", "right alt", "caps lock", "f13", "menu", "pause"]) {
  assert.equal(isUsable(good), true, `${good} should be allowed`);
}

const suggestions = [{ value: "right ctrl", label: "Right Ctrl" }];
assert.equal(describeKey("right ctrl", suggestions), "Right Ctrl");
assert.equal(describeKey("caps lock", suggestions), "Caps Lock");
assert.equal(describeKey("", suggestions), "");

console.log("keys_spec: ok");
