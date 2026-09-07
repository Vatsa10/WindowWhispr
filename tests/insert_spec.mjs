// Assertions for the caret-insertion rules. Run by pytest through node.
import { insertAtCaret, isTextField } from "../core/web/static/insert.js";

let failures = 0;
function check(name, got, want) {
  const g = JSON.stringify(got), w = JSON.stringify(want);
  if (g !== w) { failures++; console.log(`FAIL ${name}\n  got  ${g}\n  want ${w}`); }
}

// Into an empty field.
check("empty field", insertAtCaret("", 0, 0, "hello there"),
  { value: "hello there", caret: 11 });

// At the end of existing text: one space, never two.
check("appends with a space", insertAtCaret("Dear Bob", 8, 8, "how are you"),
  { value: "Dear Bob how are you", caret: 20 });
check("no double space", insertAtCaret("Dear Bob ", 9, 9, "how are you"),
  { value: "Dear Bob how are you", caret: 20 });

// In the middle: spaces on both sides, caret after the words.
check("mid-text", insertAtCaret("Dear  Bob", 5, 5, "old friend"),
  { value: "Dear old friend Bob", caret: 15 });

// Replacing a selection.
check("replaces selection", insertAtCaret("say hello world", 4, 9, "goodbye"),
  { value: "say goodbye world", caret: 11 });

// Punctuation must stay hugged to its word.
check("before a comma", insertAtCaret("Hi , and welcome", 3, 3, "Bob"),
  { value: "Hi Bob, and welcome", caret: 6 });

// Brackets do not get a space pushed in after them.
check("after a bracket", insertAtCaret("total (", 7, 7, "excluding tax"),
  { value: "total (excluding tax", caret: 20 });

// Dictation is trimmed, not blindly concatenated.
check("trims the dictation", insertAtCaret("a", 1, 1, "   b   "),
  { value: "a b", caret: 3 });

// Nothing spoken changes nothing.
check("empty insertion", insertAtCaret("keep me", 3, 3, "   "),
  { value: "keep me", caret: 3 });

// Out-of-range carets are clamped rather than corrupting the value.
check("caret past the end", insertAtCaret("abc", 99, 99, "d"),
  { value: "abc d", caret: 5 });

// Field detection.
check("textarea is a field", isTextField({ tagName: "TEXTAREA" }), true);
check("text input is a field", isTextField({ tagName: "INPUT", type: "text" }), true);
check("email input is a field", isTextField({ tagName: "INPUT", type: "email" }), true);
check("checkbox is not", isTextField({ tagName: "INPUT", type: "checkbox" }), false);
check("button is not", isTextField({ tagName: "BUTTON" }), false);
check("readonly is not", isTextField({ tagName: "TEXTAREA", readOnly: true }), false);
check("disabled is not", isTextField({ tagName: "INPUT", type: "text", disabled: true }), false);
check("null is not", isTextField(null), false);

console.log(failures ? `${failures} failure(s)` : "all caret-insertion assertions pass");
process.exit(failures ? 1 : 0);
