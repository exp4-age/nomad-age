# nomad-age

A NOMAD plugin for the AGE.

This `nomad` plugin was generated with `Cookiecutter` along with `@nomad`'s [`cookiecutter-nomad-plugin`](https://github.com/FAIRmat-NFDI/cookiecutter-nomad-plugin) template.

## Particle tracking entries

For a recording `X` the parsers create these entries:

| File | Entry type | Content |
| --- | --- | --- |
| `X.h5` with dataset `frames` (camera video) | `AGE_ParticleTransportVideo` | camera settings, first and last frame; the sample (chip), particles and instruments (objective) of the recording are edited here |
| `X_trajs.h5` (trackpy trajectories) | `AGE_ParticleTracking` | counts and plot of the unfiltered trajectories; `video` references the video entry, which lists the tracks under "referenced by" |
| `X_filtered_trajs.h5` | `AGE_ParticleTracking` | only for recordings uploaded without `X_trajs.h5` |
| `*.h5` with datasets `imgs`, `poss`, `tgs` | `AGE_FocusSweep` | images and sharpness of a microscope z sweep |

In particle transport measurements the sample is the chip as it was under the
microscope: `samples` of videos, focus sweeps and tracks link only the coated
chip (`AGE_CoatedSample`, e.g. `2023_0418_1_PMMA5`) whose layer was on the chip
at the measurement's `datetime`, or the bare chip (`AGE_Sample`) if no layer was
on it then. Particles are not samples: they are linked in `particle_batches`
(`AGE_Particles` entries; "Particles" on the overview). The workflow of an entry
has the sample and every particle batch as inputs, so a particle batch lists the
entries under "Referenced by".

For the search apps, `particles` lists the particle batches and `chips` the
chip of the sample (of a coated chip: its chip), each by the name of the linked
entry; `spacer_thickness` and `spacer_thickness_uncertainty` are the ones of the
coated chip (empty for a bare chip) and are shown read-only on the overview.
They are filled each time the entry is processed and are not stored in the entry
files; an entry that cannot be loaded is left out with a warning.

`particle_batches` of a video is filled from the `particles` attribute of the file (lab
ids, searched among the `AGE_Particles` entries of every upload the main author
sees; a batch that is not found is reported, never created) if it is empty; a
choice made on the overview stays when the file is processed again. Tracks
entries show it read-only, taken from their video entry (from the `particles`
attribute of the tracks file without a video entry). Entries stored when
particles were samples are migrated on processing: samples that link a particle
batch (or whose lab_id names one) are removed, and fill `particle_batches` if it
is empty.

Videos and focus sweeps pick their microscope objective (an `AGE_Objective`
entry) in `objective`, a dropdown on the overview page. `instruments` stays the
one list the search apps filter by and the tracks entries take over, and follows
it: on processing, the instruments that link an objective are replaced by one
that links `objective` (other instruments stay). An empty `objective` is filled
from the first objective among the instruments, e.g. the one the parser links
from the `objective` attribute of the video. A picked objective stays when the
file is processed again, whatever its attribute says; to remove the objective,
clear `objective` and remove it from `instruments`.

They pick their chip the same way: `chip`, a dropdown of bare chips
(`AGE_Sample`). The coated chip is not picked, as the dropdown cannot filter by
date: on every processing the sample becomes the `AGE_CoatedSample` of that chip
whose layer was on it at the `datetime` of the measurement (`date_coated` ≤
datetime < `date_removed`; no `date_removed`: still on), so layers entered later
are picked up on reprocessing. A date without time counts as the whole lab day;
on the day one layer is removed and the next coated, the newer one is taken with
a warning. If no layer was on the chip then, or if the measurement has no
datetime, the bare chip is the sample (both with a warning). Other samples are
removed (with a warning unless they link a chip or coated chip). An empty `chip`
is filled from the samples (the linked chip, or the chip of the linked coated
chip), e.g. the chip the parser links from the file name; if they link several
chips nothing changes, with a warning. If the coated chips cannot be looked up,
the samples stay as they are. A picked chip stays when the file is processed
again, and the tracks entries take over the sample.

The entries are written next to the files as `<file>.archive.yaml`. The entry of
the original file itself (`AGE_RawFile`, named after the file) records it for
archival: upload-relative path (`file_name`), `file_type`, `file_size`, `sha256`
and modification time (`modified`, UTC), filled on every processing run, and
`processed_archive`, the link to the written entry. The written entries link back
in `raw_file` (also for field cooling logs), listed under "References"; existing
entry files gain it on the next reprocessing, keeping user edits. Filtered
trajectories are not kept: they are reproduced from the unfiltered ones with the
filter of the upload, documented once per upload in an `AGE_TrajectoryFiltering`
entry ("Trajectory filtering") that users create, e.g. as `filter.archive.yaml`:

```yaml
data:
  m_def: nomad_age.schema_packages.particle_tracking_schema.AGE_TrajectoryFiltering
  name: Trajectory filter
  min_frames: 20            # trackpy.filter_stubs: keeps trajectories with >= 20 frames
  min_net_displacement: 5   # pixels; keeps particles that move farther between first and last point
  displacement_axes: [x]    # |Δx|; Euclidean distance for several axes
  software: trackpy 0.7
  script_file: filtering.py
```

Without `inputs`, the inputs of the filter are all tracks entries
(`*_trajs.h5.archive.yaml`, except filtered-only ones) of the upload when it is
processed; each tracks entry then lists the filter under "referenced by".
Tracks entries added later are linked when the filter entry is processed again.

## Coated chips and spin coating

A chip (`AGE_Sample`, e.g. `2023_0418`) gets a spacer layer, e.g. PMMA, by spin
coating; after some experiments the layer is removed and a new one coated. Each
layer is an ELN entry "Coated chip" (`AGE_CoatedSample`) with lab_id
`<chip>_PMMA<n>`: it references its `chip` and holds `spacer_thickness` ± its
uncertainty (standard error of the mean over the profilometry points on a
scratch in the layer), `date_coated` and `date_removed`. Recordings link the
coated chip they were measured on under samples, by its lab_id or a reference;
videos and focus sweeps link it from their `chip` and `datetime` (see above), so
the dates decide which layer a recording gets.

A "Spin coating" entry (`AGE_SpinCoating`) documents how a layer was made:
resist, spin speed and acceleration, spin time, layers, bake temperature and time;
its datetime is the coating date. Its `chip` is the input and its
`coated_sample` the output of its workflow; both are also listed as its samples.

```yaml
data:
  m_def: nomad_age.schema_packages.age_schema.AGE_CoatedSample
  lab_id: 2023_0418_PMMA2
  chip: ../upload/archive/mainfile/2023_0418.archive.yaml#data
  spacer_thickness: 3369.25            # nm
  spacer_thickness_uncertainty: 36.9   # nm
  thickness_method: profilometry (scratch)
  n_thickness_points: 4
  date_coated: 2025-03-12
```

The "AGE Samples" app shows chips, coated chips and spin coatings.

## Inventory

The "AGE Inventory" app lists lab equipment and consumables: particle batches
(`AGE_Particles`) and microscope objectives (`AGE_Objective`), with columns and
filters for type, name, ID (lab_id), particle type, batch and batch date,
magnification and numerical aperture. To see where an item was used, open it:
"Referenced by" in Entry References lists the recordings linking it.

The inventory entry types are listed once, in `INVENTORY_SCHEMAS` in
`src/nomad_age/apps/__init__.py`; a new type (e.g. cameras, magnets, chemicals)
is added there to appear in the app, plus columns or menu items for its own
quantities.

## Magnetisation measurements on chips

L-MOKE files (`*LMOKE*.txt`) are `LMOKEandVMOKESchema` entries: `technique`
(L-MOKE or V-MOKE, from the device or file name), `measurement_time` (the lab
time in the file name, Europe/Berlin) and the plot of magnetization (else
intensity) against field. Their `samples` link the chip of the `Sample` line in
the AGE Samples upload (`2023_0418` means `2023_0418_1`); a missing chip is a
warning, chips are never created. All magnetisation entry types derive from
`AGE_MagnetisationMeasurement`, so a chip lists them under "Referenced by".

A chip shows the plot of its newest magnetisation measurement (that its main
author sees) with `latest_magnetisation_measurement`, `_time` and `_technique`,
refreshed on every processing of the chip. Processing a measurement that is
newer than the one its chip shows (or is that one) reprocesses the chip entry
shortly after, once the measurement's upload is done (NOMAD with Temporal only).
After deleting measurements, or if a refresh was missed, run in the Oasis
container

```sh
python -m nomad_age.scripts.refresh_chip_plots [--dry-run]
```

which reprocesses the chips that do not show their newest measurement.


## Development

If you want to develop locally this plugin, clone the project and in the plugin folder, create a virtual environment (you can use Python 3.9, 3.10, or 3.11):
```sh
git clone https://github.com/exp4-age/nomad-age.git
cd nomad-age
python3.11 -m venv .pyenv
. .pyenv/bin/activate
```

Make sure to have `pip` upgraded:
```sh
pip install --upgrade pip
```

We recommend installing `uv` for fast pip installation of the packages:
```sh
pip install uv
```

Install the `nomad-lab` package:
```sh
uv pip install '.[dev]' --index-url https://gitlab.mpcdf.mpg.de/api/v4/projects/2187/packages/pypi/simple
```

**Note!**
Until we have an official pypi NOMAD release with the plugins functionality make
sure to include NOMAD's internal package registry (via `--index-url` in the above command).

The plugin is still under development. If you would like to contribute, install the package in editable mode (with the added `-e` flag):
```sh
uv pip install -e '.[dev]' --index-url https://gitlab.mpcdf.mpg.de/api/v4/projects/2187/packages/pypi/simple
```


### Run the tests

You can run locally the tests:
```sh
python -m pytest -sv tests
```

where the `-s` and `-v` options toggle the output verbosity.

Our CI/CD pipeline produces a more comprehensive test report using the `pytest-cov` package. You can generate a local coverage report:
```sh
uv pip install pytest-cov
python -m pytest --cov=src tests
```

### Run linting and auto-formatting

We use [Ruff](https://docs.astral.sh/ruff/) for linting and formatting the code. Ruff auto-formatting is also a part of the GitHub workflow actions. You can run locally:
```sh
ruff check .
ruff format . --check
```


### Debugging

For interactive debugging of the tests, use `pytest` with the `--pdb` flag. We recommend using an IDE for debugging, e.g., _VSCode_. If that is the case, add the following snippet to your `.vscode/launch.json`:
```json
{
  "configurations": [
      {
        "name": "<descriptive tag>",
        "type": "debugpy",
        "request": "launch",
        "cwd": "${workspaceFolder}",
        "program": "${workspaceFolder}/.pyenv/bin/pytest",
        "justMyCode": true,
        "env": {
            "_PYTEST_RAISE": "1"
        },
        "args": [
            "-sv",
            "--pdb",
            "<path-to-plugin-tests>",
        ]
    }
  ]
}
```

where `<path-to-plugin-tests>` must be changed to the local path to the test module to be debugged.

The settings configuration file `.vscode/settings.json` automatically applies the linting and formatting upon saving the modified file.


### Documentation on Github pages

To view the documentation locally, install the related packages using:
```sh
uv pip install -r requirements_docs.txt
```

Run the documentation server:
```sh
mkdocs serve
```


## Adding this plugin to NOMAD

Currently, NOMAD has two distinct flavors that are relevant depending on your role as an user:
1. [A NOMAD Oasis](#adding-this-plugin-in-your-nomad-oasis): any user with a NOMAD Oasis instance.
2. [Local NOMAD installation and the source code of NOMAD](#adding-this-plugin-in-your-local-nomad-installation-and-the-source-code-of-nomad): internal developers.

### Adding this plugin in your NOMAD Oasis

Read the [NOMAD plugin documentation](https://nomad-lab.eu/prod/v1/staging/docs/howto/oasis/plugins_install.html) for all details on how to deploy the plugin on your NOMAD instance.

### Entry hash of aux files

NOMAD's `entry_hash` reads the mainfile and every other file in its directory
(the "aux files") for every entry. Since our uploads keep large videos next to small
measurement files, the plugin replaces `StagingUploadFiles.entry_hash` when its
entry points are loaded (`nomad_age.utils.entry_hash.install()`): the mainfile
content is hashed in full, aux files only by path, size and modification time.
Entries without aux files keep NOMAD's hash. Set `NOMAD_AGE_FULL_ENTRY_HASH=1` in the
NOMAD worker environment to keep NOMAD's original implementation.

Switching implementations changes the `entry_hash` of entries with aux files, so
these entries get a new `entry_timestamp` on their next reprocessing. The same
happens when aux files get new modification times, e.g. when a published upload is
extracted back to staging.

### Adding this plugin in your local NOMAD installation and the source code of NOMAD

Modify the text file under `/nomad/default_plugins.txt` and add:
```sh
<other-content-in-default_plugins.txt>
nomad-age==x.y.z
```
where `x.y.z` represents the released version of this plugin.

Then, go to your NOMAD folder, activate your NOMAD virtual environment and run:
```sh
deactivate
cd <route-to-NOMAD-folder>/nomad
source .pyenv/bin/activate
./scripts/setup_dev_env.sh
```

Alternatively and only valid for your local NOMAD installation, you can modify `nomad.yaml` to include this plugin, see [NOMAD Oasis - Install plugins](https://nomad-lab.eu/prod/v1/staging/docs/howto/oasis/plugins_install.html).


### Build the python package

The `pyproject.toml` file contains everything that is necessary to turn the project
into a pip installable python package. Run the python build tool to create a package distribution:

```sh
pip install build
python -m build --sdist
```

You can install the package with pip:

```sh
pip install dist/nomad-age-0.1.0
```

Read more about python packages, `pyproject.toml`, and how to upload packages to PyPI
on the [PyPI documentation](https://packaging.python.org/en/latest/tutorials/packaging-projects/).


### Template update

We use cruft to update the project based on template changes. A `cruft-update.yml` is included in Github workflows to automatically check for updates and create pull requests to apply updates. Follow the [instructions](https://github.blog/changelog/2022-05-03-github-actions-prevent-github-actions-from-creating-and-approving-pull-requests/) on how to enable Github Actions to create pull requests. 

To run the check for updates locally, follow the instructions on [`cruft` website](https://cruft.github.io/cruft/#updating-a-project).


## Main contributors
| Name | E-mail     |
|------|------------|
| Nikolai Weidt | [nw@uni-kassel.de](mailto:nw@uni-kassel.de)
