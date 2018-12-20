# MpCsvAccounting

This is a parser for MobilePay MyShop CSVs. It writes CSVs that Dinero accounting software recognizes. In use by F-klubben at the Department of Computer Science at Aalborg University, Denmark.

## Prerequisites

The script is written in [Python 3](https://www.python.org/downloads/) and requires that it is installed on the system.

## Installation

The script currently has a single dependency, [holidays](https://github.com/dr-prodigy/python-holidays). To install with pip, run
```bash
python -m pip install --user holidays==0.9.8
```
or
```bash
python -m pip install --user -r requirements.txt
```

## Usage

To output to "out.csv", passing input file and appendix start:
```bash
python3 mp_csv_accounting.py examples/mpExample.csv 123
```

To output to "somename.csv" in "somedir", passing input file, appendix start, and output file:
```bash
python3 mp_csv_accounting.py examples/mpExample.csv 123 -o someDir/somename.csv
```

An example MP CSV is in the examples directory.

## License

This script is licensed under the GNU General Public License v3.0 - see the [LICENSE](LICENSE) file for details.
