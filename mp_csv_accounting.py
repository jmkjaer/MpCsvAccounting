#!/usr/bin/env python3

import argparse
import csv
import datetime
import holidays
import locale
from pathlib import Path
import sys


HOLIDAYS_DK = holidays.DK()


class Account(str):
    """String constants for Dinero's bank accounts."""

    BANK = "55000"
    GAVEKORT = "63080"
    GEBYRER = "7220"
    SALG = "1000"


def parseArgs():
    """Parses command-line arguments and returns them."""

    parser = argparse.ArgumentParser(description="Parse MP CSV and write Dinero CSV.")
    parser.add_argument("infile", help="the MP CSV file to parse")
    parser.add_argument(
        "appendix_start", type=int, help="appendix number start in Dinero"
    )
    parser.add_argument(
        "-o",
        "--outfile",
        metavar="FILE",
        help="write output to file (default: out.csv)",
    )
    return parser.parse_args()


def handleOutFile(args):
    if args.outfile:
        writePath = args.outfile
        if Path(args.outfile).parent:
            Path(args.outfile).parent.mkdir(exist_ok=True)
    else:
        writePath = "out.csv"

    return writePath


def prepareCsvReader(filePath):
    """Prepares the CSV reader by opening the file and skipping two lines."""

    # Encoding is UTF-16, little-endian, due to MP using MS SQL Server
    file = open(filePath, "r", newline="", encoding="utf-16-le")
    next(file)
    next(file)

    return csv.reader(file, delimiter=";")


def readTransactionsFromFile(filePath):
    """Returns transactions in batches read from the CSV file exported by MP.
    
    Returns a list of lists of user transactions bundled in transaction \
    batches before bank transfer. Amount is in øre (1/100th of a krone).
    """

    reader = prepareCsvReader(filePath)
    transactions = []
    transactionsByBatch = []

    for index, row in enumerate(reader):
        # Parse as øre (1/100th krone) instead of kroner
        transferAmount = row[3].replace(",", "").replace(".", "")
        mpFee = row[10].replace(",", "")
        if row[0] == "Salg":
            # Amount, date, message, MP fee
            transactions.append((transferAmount, row[6], row[9], mpFee))
            continue
        elif row[0] == "Refundering":
            transactions.append(("-" + transferAmount, row[6], row[9], mpFee))
            continue
        elif row[0] == "Overførsel":
            # The imported CSV starts with a "Gebyr" and an "Overførsel"
            if transactions:
                transactionsByBatch.append(transactions)
                transactions = []
            continue
        elif row[0] == "Gebyr":
            continue
        else:
            raise ValueError(
                "Error: Unknown transaction type '{}'\n  File {}, line {}".format(
                    row[0], filePath, str(index + 3)
                )
            )
    # The imported CSV possibly ends with a batch of sales with no "Overførsel"
    if transactions:
        transactionsByBatch.append(transactions)

    return transactionsByBatch


def prepareCsvWriter(filePath):
    """Prepares the CSV writer by opening the file and setting delimiters."""

    file = open(filePath, "w", newline="")
    csvWriter = csv.writer(file, delimiter=";")
    return csvWriter


def isRegistration(transaction):
    """Finds out if the transaction is part of a registration.
    
    Searches for the substrings "tilmeld" and "indmeld" in the MP transaction comment.
    """

    return "tilmeld" in transaction[2].lower() or "indmeld" in transaction[2].lower()


def calculateBatchInfo(batch, registrationFee=20000):
    """Returns important information from a batch of transactions.
    
    Returns the amount transferred to the bank, the fees by MP, \
    the registration fees paid by the members, and the voucher amount for the members. \
    Amount is in øre.
    """

    registrationFees = 0
    voucherAmount = 0
    mpFees = 0
    toBank = 0

    for transaction in batch:
        mpFee = int(transaction[3])
        transAmount = int(transaction[0])

        mpFees += mpFee
        toBank += transAmount - mpFee

        if isRegistration(transaction):
            registrationFees += registrationFee
            voucherAmount += transAmount - registrationFee
        else:
            voucherAmount += transAmount

    return (toBank, mpFees, registrationFees, voucherAmount)


def nextBusinessDay(date):
    """Returns the next business day for bank transfer in dd-mm-yyyy format."""

    nextDay = date.date() + datetime.timedelta(days=1)
    while nextDay.weekday() in holidays.WEEKEND or nextDay in HOLIDAYS_DK:
        nextDay += datetime.timedelta(days=1)

    return datetime.datetime.strftime(nextDay, "%d-%m-%Y")


def toDecimalNumber(number):
    """Formats an amount of øre to kroner."""

    return locale.format_string("%.2f", number / 100)


def writeTransactions(filePath, appendixStart, transactionsByBatch):
    """Writes the information gathered throughout the script to a CSV file.
    
    The resulting CSV file is recognized by Dinero's journal entry CSV import. \
    The written information is in Danish.
    """

    currAppendix = appendixStart
    csvWriter = prepareCsvWriter(filePath)

    csvWriter.writerow(["Bilag nr.", "Dato", "Tekst", "Konto", "Beløb", "Modkonto"])

    for batch in transactionsByBatch:
        toBank, mpFees, registrationFees, voucherAmount = calculateBatchInfo(batch)
        batchDate = datetime.datetime.strptime(batch[0][1], "%d-%m-%Y")
        bankTransferDate = nextBusinessDay(batchDate)

        csvWriter.writerow(
            [
                currAppendix,
                bankTransferDate,
                "MP " + (str(batchDate.day) + "-" + str(batchDate.month)).zfill(5),
                Account.BANK,
                toDecimalNumber(toBank),
                None,
            ]
        )
        csvWriter.writerow(
            [
                currAppendix,
                bankTransferDate,
                "Gavekort",
                Account.GAVEKORT,
                "-" + toDecimalNumber(voucherAmount),
                None,
            ]
        )
        if registrationFees > 0:
            csvWriter.writerow(
                [
                    currAppendix,
                    bankTransferDate,
                    "Tilmeldingsgebyr",
                    Account.SALG,
                    "-" + toDecimalNumber(registrationFees),
                    None,
                ]
            )
        csvWriter.writerow(
            [
                currAppendix,
                bankTransferDate,
                "MP-gebyr",
                Account.GEBYRER,
                toDecimalNumber(mpFees),
                None,
            ]
        )

        currAppendix += 1


def main():
    """Reads a CSV by MP and writes a CSV recognizable by Dinero.
    
    Note: The locale is set to be able to convert numbers as strings into Danish \
    decimal numbers with comma as separator.
    """

    locale.setlocale(locale.LC_NUMERIC, "en_DK.UTF-8")

    args = parseArgs()
    writePath = handleOutFile(args)

    try:
        transactionsByBatch = readTransactionsFromFile(args.infile)
    except ValueError as e:
        print(e)
        sys.exit()
    writeTransactions(writePath, args.appendix_start, transactionsByBatch)

    print("Done writing to " + writePath)


if __name__ == "__main__":
    main()
