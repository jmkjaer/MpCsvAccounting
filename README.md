# MpCsvAccounting <img src="images/f-klubben.jpg" width="200" align="right">

This is a parser for MobilePay MyShop CSVs. It writes CSVs that Dinero accounting software recognizes, as well as PDFs used for documentation.
In use by F-klubben at the Department of Computer Science at Aalborg University, Denmark.

## Prerequisites

The script is written in [Python 3](https://www.python.org/downloads/) and requires it to be installed on the system.
In addition, [Pip](https://github.com/pypa/pip) is needed for dependency installation.

## Installation

The script currently has three high-level dependencies, [holidays](https://github.com/dr-prodigy/python-holidays), [PyFPDF](https://github.com/reingart/pyfpdf), and [dateutil](https://github.com/dateutil/dateutil). To install with pip, run
```bash
python3 -m pip install --user -r requirements.txt
```

## Usage

An example MP CSV is in the examples directory.

To output to "123-148.csv" in the current dir, pass input file and appendix number start:
```bash
python3 mp_csv_accounting.py examples/mpExample.csv 123
```

**Remember to change the number in the config file to the actual Stregsystem one before real use.**

## License

This script is licensed under the GNU General Public License v3.0 - see the [LICENSE](LICENSE) file for details.
