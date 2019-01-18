# MpCsvAccounting

This is a parser for MobilePay MyShop CSVs. It writes CSVs that Dinero accounting software recognizes. In use by F-klubben at the Department of Computer Science at Aalborg University, Denmark.

## Prerequisites

The script is written in [Python 3](https://www.python.org/downloads/) and requires it to be installed on the system.
In addition, [Pip](https://github.com/pypa/pip) is needed for dependency installation.

## Installation

The script currently has two high-level dependencies, [holidays](https://github.com/dr-prodigy/python-holidays), and [fpdf](https://github.com/reingart/pyfpdf). To install with pip, run
```bash
python3 -m pip install --user -r requirements.txt
```

## Usage

To output to "out.csv" in current dir, pass input file and appendix start:
```bash
python3 mp_csv_accounting.py examples/mpExample.csv 123
```

To output to "somename.csv" in "somedir", pass input file, appendix start, and output file:
```bash
python3 mp_csv_accounting.py examples/mpExample.csv 123 -o someDir/somename.csv
```

An example MP CSV is in the examples directory.

## License

This script is licensed under the GNU General Public License v3.0 - see the [LICENSE](LICENSE) file for details.
