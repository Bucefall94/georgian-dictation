# Security Policy

## Reporting a vulnerability

Please do **not** publish credentials, exploit details, private logs, or sensitive user data in a public issue.

Use GitHub's **private vulnerability reporting** feature for this repository when it is enabled. If private reporting is temporarily unavailable, open a minimal issue asking the maintainer for a private contact channel without disclosing the vulnerability details.

## Credential boundaries

Georgian Dictation is designed so that:

- Deepgram API keys are stored in Windows Credential Manager.
- Google authentication uses Application Default Credentials (ADC).
- No maintainer-specific cloud project or credential file is required in source control.
- Local settings must not contain API keys or service-account JSON.
- Error messages redact common API-key and bearer-token patterns.

## Public issue hygiene

Before attaching logs or screenshots, remove usernames, filesystem paths, project IDs, tokens, email addresses, transcripts, and any text dictated by a real user.
