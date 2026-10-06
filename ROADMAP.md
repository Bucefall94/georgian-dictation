# Roadmap

This roadmap is directional, not a promise of delivery dates.

## Near term

- Improve first-run checks for microphone, native runtime, models, and optional cloud providers.
- Make Vertex project configuration clearer without embedding maintainer-specific cloud identifiers.
- Expand automated tests around failure/fallback paths and long dictation ordering.
- Add reproducible GitHub release packaging for Windows.
- Improve contributor documentation and issue triage.

## Speech quality

- Continue A/B evaluation of Georgian local and cloud ASR.
- Add a small, privacy-safe evaluation workflow for WER regression tracking.
- Improve phrase segmentation and punctuation behavior for longer Georgian dictation.

## Accessibility and UX

- Improve keyboard-only navigation and status announcements.
- Refine setup/error messages for non-technical users.
- Keep the overlay focus-safe and non-intrusive.

## Extensibility

- Keep STT and AI providers behind narrow interfaces.
- Make additional providers possible without coupling them to the UI or insertion layer.
- Document provider contracts and test doubles for contributors.
