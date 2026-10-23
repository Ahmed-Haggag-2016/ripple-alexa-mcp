# Friction Log

## Task

Publish the Ripple source code to a new public GitHub repository from a Windows development environment.

## Steps attempted

1. Checked whether Git was available and whether the project was already a Git repository.
2. Found that Git was not installed or available on the system `PATH`.
3. Installed Git for Windows with Windows Package Manager and initialized the project repository.
4. Tried pushing the initial commit to GitHub.

## Expected result

Git should be available to initialize the repository, and the first push should provide a clear way to authenticate with GitHub.

## Actual result

Git was initially unavailable. After installation, the current PowerShell session still could not find Git on `PATH`. The first push then failed because the environment disabled interactive credential prompts, so Git could not ask the user to sign in.

## Severity

Moderate: repository publishing was blocked until Git was installed and GitHub authentication was completed.

## Workaround

Used Git from its installed path, then authenticated through Git Credential Manager's GitHub browser sign-in. The push succeeded and the repository was verified online.

## Actionable suggestion

For Windows-based first-time publishing, provide a short setup checklist that checks for Git, tells users to restart their terminal after installation, and explains how to authenticate with Git Credential Manager's browser flow when terminal prompts are unavailable.

## Scope note

This log describes friction in the local GitHub publishing setup. It is not a report of a defect in Alexa+, Amazon services, or Devpost.
