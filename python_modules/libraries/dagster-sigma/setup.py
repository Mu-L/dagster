from pathlib import Path

from setuptools import find_packages, setup


def get_version() -> str:
    version: dict[str, str] = {}
    with open(Path(__file__).parent / "dagster_sigma/version.py", encoding="utf8") as fp:
        exec(fp.read(), version)

    return version["__version__"]


ver = get_version()
# dont pin dev installs to avoid pip dep resolver issues
pin = "" if ver == "1!0+dev" or "rc" in ver else f"=={ver}"
setup(
    name="dagster_sigma",
    version=ver,
    author="Dagster Labs",
    author_email="hello@dagsterlabs.com",
    license="Apache-2.0",
    description="Build assets representing Sigma dashboards.",
    url=(
        "https://github.com/dagster-io/dagster/tree/master/python_modules/libraries/dagster-sigma"
    ),
    classifiers=[
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Programming Language :: Python :: 3.13",
        "License :: OSI Approved :: Apache Software License",
        "Operating System :: OS Independent",
    ],
    packages=find_packages(exclude=["dagster_sigma_tests*"]),
    install_requires=[f"dagster{pin}", "sqlglot", "aiohttp"],
    extras_require={"test": ["aioresponses", "aiohttp<3.11"]},
    include_package_data=True,
    python_requires=">=3.9,<3.14",
    entry_points={
        "console_scripts": [
            "dagster-sigma = dagster_sigma.cli:app",
        ]
    },
    zip_safe=False,
)
