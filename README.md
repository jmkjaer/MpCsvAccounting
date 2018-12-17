# MpCsvAccounting

This is a parser for MobilePay MyShop CSVs. It writes CSVs that Dinero accounting software recognizes. In use by F-klubben at the Department of Computer Science at Aalborg University, Denmark.

## Prerequisites

MpCsvAccounting is written in [Python 3](https://www.python.org/downloads/) and requires that it is installed on the system.

## Installation

The script currently has a single dependency, [holidays](https://pypi.org/project/holidays/). To install with pip, run
```
python -m pip install --user -r requirements.txt
```
or
```
python -m pip install --user holidays==0.9.8
```

## Usage

```bash
cd dir_with_MP_CSV
python3 MpCsvAccounting.py
```

An example MP CSV is in the examples directory.

## License

This script is licensed under the GNU General Public License v3.0 - see the [LICENSE](LICENSE) file for details.

