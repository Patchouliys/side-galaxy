# Side Galaxy development

- Read README and the relevant active OpenSpec change before substantial work.
- Use project-local OpenSpec and Ponytail skills; preserve explicit user authorization.
- Write user-facing docs in Chinese and code identifiers in English.
- Board and OS support belong in profiles/modules. Do not hard-code new model IDs into the control plane.
- Treat execution modules as trusted administrator-deployed code. Never expose remote arbitrary shell or module source upload.
- Admission must be atomic. Cancellation and expiry must not silently release possibly active resources.
- Keep module generation, request hash, execution mode and cleanup evidence. Synthetic is never a hardware measurement.
- Never claim Pi or KVM target acceptance based on simulator or mocked tests.
- Run `uv run python -m unittest discover -s tests -v` and `npm run spec:validate` for relevant changes.
- Keep credentials, real inventory, databases and local paths out of commits. Use the project commit identity for initial publication.
