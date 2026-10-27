# UI redesign backlog

Notes captured during two-device testing on 2026-10-27:

- Light mode does not carry through to the help-call screen; it remains dark.
- The trusted-helper approval / connect dialog also ignores light mode.
- The “I need help” and “I'm helping” role choices use pale text that is hard to read in light mode. Use theme-aware foreground and selected-state colors with accessible contrast.
- The guide-save dialog is difficult to scan; explain the screenshot review/redaction and local generation steps in plain language, and make generated steps visibly numbered and editable.
- `My Step Guides` has low-contrast white empty-state and guide-title text in light mode; audit the guide list, detail, screenshot-review, and save screens for theme-aware text and borders.
- After a call, saving a guide can appear disabled without a clear reason. Keep the save action visible and explain whether a title, notes, or reviewed screenshots are needed.
- Screen sharing has a noticeable startup delay before the helper sees the first frame. Audio guide capture also appears as a separate opt-in and needs a clearer explanation of what it records and why.

Recheck these screens as part of the full older-adult UI redesign, including high-contrast mode and larger text sizes.
