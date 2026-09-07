// Inserting dictated words where the caret is.
//
// Appending to the end of a field is wrong the moment someone clicks into the
// middle of what they wrote to fix a word, or tabs to a different field in a
// form. The words belong where the cursor is.
//
// The spacing rules are the fiddly part and the reason this is its own module
// with its own tests: joining "Dear Bob" and "how are you" needs a space,
// joining "Dear Bob " and "how are you" does not, and neither does inserting
// before a comma.

/** Characters that must not be pushed away from the word they follow. */
const TIGHT_AFTER = new Set([",", ".", "!", "?", ";", ":", ")", "]", "}"]);

/**
 * Work out the text and caret position after inserting dictation.
 *
 * Pure so the spacing decisions can be tested without a browser. Returns the
 * whole new value plus where the caret should land, which is always after the
 * inserted words — dictating twice in a row should carry on, not overwrite.
 */
export function insertAtCaret(value, selectionStart, selectionEnd, insertion) {
  const words = (insertion || "").trim();
  if (!words) return { value, caret: selectionEnd };

  const start = Math.max(0, Math.min(selectionStart, value.length));
  const end = Math.max(start, Math.min(selectionEnd, value.length));
  const before = value.slice(0, start);
  const after = value.slice(end);

  // A space before, unless we are at the very start, already after
  // whitespace, or immediately after an opening bracket.
  const previous = before.slice(-1);
  const needsLeadingSpace =
    before.length > 0 && !/\s/.test(previous) && !"([{".includes(previous);

  // A space after, unless what follows is punctuation that hugs the word, or
  // whitespace, or nothing at all.
  const next = after.slice(0, 1);
  const needsTrailingSpace =
    after.length > 0 && !/\s/.test(next) && !TIGHT_AFTER.has(next);

  const body = (needsLeadingSpace ? " " : "") + words + (needsTrailingSpace ? " " : "");
  return {
    value: before + body + after,
    caret: before.length + body.length - (needsTrailingSpace ? 1 : 0),
  };
}

/** True when an element is something a person types into. */
export function isTextField(element) {
  if (!element || element.disabled || element.readOnly) return false;
  const tag = element.tagName;
  if (tag === "TEXTAREA") return true;
  if (tag !== "INPUT") return false;
  // Only the input types with a caret. A checkbox has no text to insert into.
  return ["text", "search", "url", "email", "tel", "number", ""].includes(
    (element.type || "").toLowerCase()
  );
}
