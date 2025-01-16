# Debug Adapter

## About

This project implements a Debug Adapter that integrates the GNU Debugger (GDB) with development tools supporting the Debug Adapter Protocol (DAP), such as Visual Studio Code. The adapter provides an interface for debugging control, processing commands, retrieving thread states, stack traces, and other GDB features.

## License

This project is distributed under the MIT license. See the LICENSE file for details.

## Note

The project is under development and is therefore not a working solution that can be used.

## Preparing the developer environment

### Python and build environment

2. Install python, which will be used to develop the project

```bash
pyenv install 3.10
```

3. Create a virtual environment in the project folder

```bash
pyenv virtualenv 3.10 venv
pyenv local venv
pyenv activate
```

4. Install pip and poetry:
```bash
pip install --upgrade pip poetry
```

5. Install all project dependencies
```bash
poetry install
```
This command will create a virtual environment if you did not complete the previous step

6. Register git hooks

```bash
pre-commit install
```


### VS Code
If you are developing in vscode, then install the plugins listed in ./.vscode/extensions.json

## Before pushing

All checks are launched with the command:

```bash
poetry run poe check
```

## VSCode Extension

A [client for VSCode](https://github.com/TheEvilMandarin/debug_adapter_ext) was written for the debug adapter. The entry point is a script located in `./bin/run_debug_adapter`.
