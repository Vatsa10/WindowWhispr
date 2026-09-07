// React, as an ES module.
//
// The vendored builds are UMD and define globals; this wraps them so the rest
// of the app can import rather than reach for `window.React`. htm gives JSX
// syntax without a build step, which is the whole reason this app has no Node
// toolchain in it: one fewer thing to install, and one fewer thing that can be
// out of date at packaging time.

const React = window.React;
const ReactDOM = window.ReactDOM;
const htm = window.htm;

if (!React || !ReactDOM || !htm) {
  throw new Error("vendored React did not load");
}

export const html = htm.bind(React.createElement);
export const { useState, useEffect, useCallback, useMemo, useRef } = React;
export { React, ReactDOM };
