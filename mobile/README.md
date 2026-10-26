# Mobile

This is the Flutter phone client for AssistMe.

The client is device-first: after one short onboarding step, people go straight
to Home. A helpee can ring a trusted person, and an accepted request opens a
two-person live session with screen sharing, voice, drawing, and optional
helpee-approved control. There is no email, password, group session, chat, or
browser workspace.

## Private local guides

After a help session, users can select screenshots and enter notes or a
transcript. They can explicitly request draft step titles and instructions from
Gemma 4 E2B running on-device. The first request downloads roughly 2.6 GB of
model weights from the public LiteRT Community Hugging Face repository; session
screenshots and notes are not uploaded. Prompts are excluded from the model
package's logs. Generated steps are editable drafts and should be reviewed
before use. Selected screenshots and transcript text are encrypted in the
app-private guide store, with the encryption key held in OS secure storage.

Audio transcription is not implemented: users currently enter or paste session
notes/transcripts themselves. Screenshots are not automatically blurred, so
users must inspect them and deselect sensitive images before generating or
saving. On-device inference requires Flutter/Dart 3.12+, Android 11+ on arm64,
or iOS 15+; the runtime is not supported on the web build. Model generation
uses device memory and can fail on lower-memory devices.
