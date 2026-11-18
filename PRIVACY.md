# Privacy

PDF Studio runs entirely on your computer. This page explains what the app keeps, where it keeps it, and how to remove it.

## What stays on your computer

- **Your documents.** Every PDF you open is copied into the `data` folder inside the project (or into the folder set by `PDF_STUDIO_DATA`). The app needs this copy to edit the file and to keep undo and redo working.
- **Undo history.** Earlier versions of each document are kept in the same folder, so undo still works after you close the tab. The app keeps the last 30 steps.
- **Fonts you upload.** They are stored in `data/fonts`.
- **Exported files.** Files you export are sent to your browser as a download. The app does not keep a copy of them.
- **Permissions.** The folders and files the app makes can be read only by your macOS user account.
- **Locked PDFs.** If you open a PDF that has a password, PDF Studio keeps an unlocked working copy in the data folder. Your original file is not changed, and the password is not saved. To protect the disk itself, turn on FileVault. You can check it with `fdesetup status`.

Nothing in this list leaves your computer.

## What the app does not do

- It does not send your documents, text, fonts, or images to any server.
- It does not collect usage statistics, crash reports, or analytics.
- It does not create an account or ask for an account password. If you open a password-protected PDF, the app asks for that file's password, and uses it only to open that file.
- It does not use the internet while it runs. Packages are downloaded from PyPI only when you install them: on the first start, after `requirements.txt` changes, and when you run `install-ocr.command`. The OCR models are inside that package.
- It does not accept connections from other computers. The server listens on `127.0.0.1` only, and it rejects requests whose host name is not `127.0.0.1` or `localhost`.

## What the browser keeps

The browser stores two small values for the app, using local storage on the page:

- the language you picked (`pdfstudio.lang`)
- the document you had open, so the app can reopen it after a reload (`pdfstudio.doc`)

You can clear both by clearing the site data for `127.0.0.1` in your browser settings.

## Deleting your data

- **One document:** click **Delete** in the top bar. The app removes that document's folder, including its undo history.
- **Everything:** stop the app with `stop.command`, then delete the `data` folder. If you use `PDF_STUDIO_DATA`, delete that folder instead.
- **Uploaded fonts:** delete them from the Font manager, or remove the files in `data/fonts`.

Deleting a file from the app removes the copy the app made. It does not touch the original file you opened, because the app never edits the original on disk. Save or export your changes to a new file first.

## Passwords

If you protect an exported PDF with a password, the app uses it only to write that file. It does not store the password anywhere else.

## Questions

If something here does not match what you see, open an issue in the project repository.
