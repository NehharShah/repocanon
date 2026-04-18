# Publishing RepoCanon to PyPI

These steps assume you have PyPI credentials and `twine` installed (it ships with the dev extras: `pip install -e ".[dev]"`).

## 1. Pre-flight

```bash
make lint
make typecheck
make test
```

All three must pass on the commit you intend to publish.

## 2. Bump the version

Edit the version in:

- `pyproject.toml` (`[project] version`)
- `repocanon/__init__.py` (`__version__`)

Use [SemVer](https://semver.org). For early development, `0.x.y` is appropriate.

## 3. Update the changelog and tag

```bash
git commit -am "Release vX.Y.Z"
git tag vX.Y.Z
git push --tags
```

## 4. Build the distributions

```bash
make build
```

This produces `dist/repocanon-X.Y.Z.tar.gz` and `dist/repocanon-X.Y.Z-py3-none-any.whl`.

Sanity-check the wheel locally:

```bash
python -m pip install dist/repocanon-*.whl --force-reinstall
repocanon --version
```

## 5. Upload to TestPyPI first

```bash
make publish-test
```

Then install from TestPyPI in a fresh venv to make sure everything resolves:

```bash
python -m venv /tmp/repocanon-smoke
source /tmp/repocanon-smoke/bin/activate
python -m pip install --upgrade pip
python -m pip install --index-url https://test.pypi.org/simple/ \
    --extra-index-url https://pypi.org/simple/ repocanon
repocanon --help
deactivate
```

## 6. Upload to PyPI

```bash
make publish
```

If you use API tokens (recommended), put them in `~/.pypirc`:

```ini
[pypi]
username = __token__
password = pypi-AgEIcHlwaS5vcmc... (your token here)

[testpypi]
username = __token__
password = pypi-AgENdGVzdC5weXBpLm9yZw... (your TestPyPI token here)
```

## 7. Post-release

- Verify the project page renders correctly: <https://pypi.org/project/repocanon/>
- Bump the version on `main` to the next dev cycle (e.g. `0.2.0.dev0`).
- Open a "next milestone" issue tracking what didn't make this release.
