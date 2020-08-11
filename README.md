# [FiftyOne](http://www.voxel51.com/fiftyone): Explore, Analyze and Curate Visual Datasets

<img src="https://user-images.githubusercontent.com/21222883/89923076-001f0400-dbce-11ea-948c-5a7c863f8458.png" alt="FiftyOne"/>

[FiftyOne](http://www.voxel51.com/docs/fiftyone) is an **open-source** machine
learning tool that helps you get closer to your data. With FiftyOne, you can
rapidly experiment with your datasets, enabling you to search, sort, filter,
visualize, analyze, and improve your datasets without wrangling or writing
custom scripts for every new dataset you collect. FiftyOne is designed to be
lightweight and easily integrate into your existing computer vision/machine
learning workflows.

To stay up-to-date on all things FiftyOne, collaborate with other users, and
get support from the Voxel51 team,
[join the FiftyOne Slack Community](https://join.slack.com/t/fiftyone-users/shared_invite/zt-gtpmm76o-9AjvzNPBOzevBySKzt02gg).

[Follow us on Medium](https://medium.com/voxel51) for regular posts on computer
vision, machine learning, and data science topics.

You can also follow us on social media (
<a href="http://www.twitter.com/voxel51" rel="twitter">
<img src="docs/source/_static/images/icons/logo-twitter-dark.svg" width="16" height="16"/>
</a> <a href="http://www.facebook.com/voxel51" rel="facebook">
<img src="docs/source/_static/images/icons/logo-facebook-dark.svg" width="16" height="16" />
</a> ).

## Installation

You can install the latest stable version of FiftyOne via `pip`:

```shell
pip install --index https://pypi.voxel51.com fiftyone
```

Consult the
[installation guide](https://voxel51.com/docs/fiftyone/getting_started/install.html)
for troubleshooting and other information about getting up-and-running with
FiftyOne.

## Documentation

Full documentation for FiftyOne can be found at
https://voxel51.com/docs/fiftyone. In particular, check out:

-   [Tutorials](https://voxel51.com/docs/fiftyone/tutorials/index.html)
-   [Recipes](https://voxel51.com/docs/fiftyone/recipes/index.html)
-   [User Guide](https://voxel51.com/docs/fiftyone/user_guide/index.html)
-   [CLI Documentation](https://voxel51.com/docs/fiftyone/cli/index.html)
-   [API Reference](https://voxel51.com/docs/fiftyone/api/fiftyone.html)

## Contributing to FiftyOne

FiftyOne is open source and community contributions are welcome!

Check out the [contribution guide](CONTRIBUTING.md) to learn how to get
involved.

## Installing from source

This section explains how to install the latest development version of
[FiftyOne](http://www.voxel51.com/docs/fiftyone) from source.

The instructions below are for macOS and Linux systems. Windows users may need
to make adjustments.

### Prerequisites

You will need:

-   [Python](https://www.python.org/) (3.5 or newer)
-   [Node.js](https://nodejs.org/) - on Linux, we recommend using
    [nvm](https://github.com/nvm-sh/nvm) to install an up-to-date version.
-   [Yarn](https://yarnpkg.com/) - once Node.js is installed, you can install
    Yarn via `npm install -g yarn`
-   On Linux, you will need at least the `openssl` and `libcurl` packages. On
    Debian-based distributions, you will need to install `libcurl4` or
    `libcurl3` instead of `libcurl`, depending on the age of your distribution.
    For example:

```shell
# Ubuntu 18.04
sudo apt install libcurl4 openssl

# Fedora 32
sudo dnf install libcurl openssl
```

### Installation

We strongly recommend that you install FiftyOne in a
[virtual environment](https://voxel51.com/docs/fiftyone/getting_started/virtualenv.html)
to maintain a clean workspace.

1. Clone the repository:

```shell
git clone --recursive https://github.com/voxel51/fiftyone
cd fiftyone
```

2. Run the installation script:

```shell
bash install.bash
```

3. If you want to use the `fiftyone.brain` package, you will need to install it
   separately after installing FiftyOne:

```shell
pip install --index https://pypi.voxel51.com fiftyone-brain
```

### Customizing your ETA installation

Installing FiftyOne from source includes an
[ETA lite installation](https://github.com/voxel51/eta#lite-installation),
which should be sufficient for most users. If you want a full ETA installation,
or wish to otherwise customize your ETA installation,
[see here](https://github.com/voxel51/eta).

### Developer installation

If you would like to [contribute to FiftyOne](CONTRIBUTING.md), you should
perform a developer installation using the `-d` flag of the install script:

```shell
bash install.bash -d
```

### Generating documentation

See the [docs guide](docs/docs_guide.md) for information on building and
contributing to the documentation.

## Uninstallation

You can uninstall FiftyOne as follows:

```shell
pip uninstall fiftyone fiftyone-brain fiftyone-db fiftyone-gui
```

## Copyright

Copyright 2017-2020, Voxel51, Inc.<br> voxel51.com
