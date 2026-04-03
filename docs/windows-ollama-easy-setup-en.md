# Windows Easy Setup (Ollama Local, Single Model)

This guide covers the quickest setup for **running Ollama locally on Windows with a single LLM**.

The `.env` file uses the default settings from `config\config.example.env` as-is.

## Does it work in a standard Windows environment?

In most cases, yes — **it works in a standard PowerShell 5.1 environment on Windows 10 / 11**.

- No `winget`, `choco`, `WSL`, or Git Bash required.
- An **internet connection is required** for the initial setup to download Python, Ollama, and the Ollama model.
- You may see confirmation prompts from Ollama's installer or from Windows when enabling long path support.
- If your PC (e.g., a corporate machine) restricts app installation or registry changes via policy, those restrictions will apply.

## Required external applications

- **Python:**
  The setup script will automatically install the **latest stable Python** from the official source if not already present.
- **Ollama:**
  The setup script will automatically install Ollama if not already present.

## Installing manually before running setup

Python and Ollama can be installed automatically, but you can also **install them manually first and then run the setup**.

- If you want to use a specific version of Python, install it manually before running setup.
- In that case, make sure **Python 3.9 or later** is installed and both `python` and `py` commands are available.
- If `py` is not available in your standard Python installation, the setup script may install an additional copy of the latest stable Python.
- If Ollama is already installed manually, the setup script will use that existing installation.

## The easiest way to get started

1. Open the `POTranslatorLLM` folder.
2. Double-click `Start-Windows-Ollama-Setup.cmd`.
3. If prompted by Ollama, Python, or Windows, allow the actions and wait until `Setup complete!` is displayed.

If Windows 11's **Smart App Control** blocks `Start-Windows-Ollama-Setup.cmd`, open PowerShell, navigate to the `POTranslatorLLM` folder, and run the following:

```powershell
cd <folder where POTranslatorLLM was extracted>
Unblock-File .\Start-Windows-Ollama-Setup.cmd
Unblock-File .\setup\install-ollama-local.ps1
.\Start-Windows-Ollama-Setup.cmd
```

If you downloaded the `.zip` file, right-click it before extracting, open **Properties**, check **Unblock**, and then extract — this reduces the chance of being blocked.

This single run automatically completes the following:

- Verifies / installs Ollama
- Starts Ollama if not running
- Downloads the default model `qwen2.5:7b`
- Installs the latest stable Python (if missing or outdated)
- Adds `python`, `py`, and Python's `Scripts` folder to `PATH`
- Enables Windows long path support (`LongPathsEnabled`)
- Installs Python dependencies
- Creates `.env` (copied from `config\config.example.env`)

## About `.env`

The `.env` file works out of the box. If you are using a single model locally, the default settings are all you need.

If a `.env` already exists, its contents take priority. Only delete `.env` and re-run `Start-Windows-Ollama-Setup.cmd` if you want to reset to the defaults.

## Verifying the setup

Start with a dry run to check everything is working.

`Localization/Game` is a sample path. Replace it with the path to the folder containing the `.po` files you want to translate.

```powershell
python scripts\translate.py --folder Localization/Game --source-lang ja --target-lang en --dry-run
```

If that looks good, run the actual translation:

```powershell
python scripts\translate.py --folder Localization/Game --source-lang ja --target-lang en
```

## Troubleshooting

- The initial model download may take some time.
- If the setup fails partway through, check the output and double-click the same file again.
- If Windows 11's Smart App Control blocks the script, use the `Unblock-File` steps above.
- If a Python installer prompt appears, **allow it** — the setup script installs the latest stable Python from the official source.
- You do **not** need to manually click "Disable path length limit" — the setup script enables `LongPathsEnabled` automatically.
- If `python` or `py` is not immediately available, open a new PowerShell or Command Prompt window.
- If you cancel the UAC elevation for the long path setting, that step will not be applied. Re-run the setup and allow the elevation to enable it.

## Related files

- Setup launcher: `Start-Windows-Ollama-Setup.cmd`
- Full documentation: `docs\user-manual.md`
