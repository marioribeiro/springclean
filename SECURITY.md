# Security

Spring Clean reads GitHub repository metadata and writes local reports. It does not delete branches, close pull requests, push commits, or modify repositories.

## Token Handling

- Store local tokens in `.env`; `.env` is ignored by Git.
- Do not commit generated reports if they contain private repository names, branch names, pull request titles, or usernames.
- Use the least privileged GitHub token that can read the target repository.
- Rotate the token if it is accidentally committed, pasted into an issue, or shared in logs.

## Reporting Issues

If you find a security issue, avoid opening a public issue with token values, private repo names, or internal branch data. Contact the maintainer privately, or open a minimal public issue that describes the problem without sensitive details.
