#!/usr/bin/env python3

import argparse
import csv
import datetime as dt
import logging
import sys
from pathlib import Path

import holidays
from dateutil.easter import easter
from fpdf import FPDF


class DanishBankHolidays(holidays.DK):
    """Bank holidays in Denmark in addition to normal holidays."""

    def _populate(self, year):
        holidays.DK._populate(self, year)
        self[
            easter(year) + dt.timedelta(days=40)  # Day after Ascension Day
        ] = "Banklukkedag"
        self[dt.date(year, 6, 5)] = "Banklukkedag"  # Danish Constitution Day
        self[dt.date(year, 12, 24)] = "Banklukkedag"  # Christmas Eve
        self[dt.date(year, 12, 31)] = "Banklukkedag"  # New Year's Eve


class Account:
    """String constants for Dinero's accounts."""

    BANK = "55000"
    GAVEKORT = "63080"
    GEBYRER = "7220"
    SALG = "1000"


DANISH_BANK_HOLIDAYS = DanishBankHolidays()


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
            transactions.append((transferAmount, row[6], row[9], mpFee, row[7]))
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
                "Error: Unknown transaction type '{}'\n  {}, line {}".format(
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


def isRegistration(transaction, registrationFee):
    """Finds out if the transaction is part of a registration.
    
    Searches for the substrings "tilmeld" and "indmeld" in the MP transaction comment,
    warns if so, if in wrong format, and if amount is below transaction fee.
    """

    isRegistration = False

    if "tilmeld" in transaction[2].lower() or "indmeld" in transaction[2].lower():
        isRegistration = True

        wrongFormatMsg = (
            "* Wrongly formatted registration message."
            if len(transaction[2].split()) != 2
            else ""
        )
        wrongAmountMsg = (
            "\n  * Not enough money transferred for registration."
            if int(transaction[0]) < registrationFee
            else ""
        )

        if wrongFormatMsg or wrongAmountMsg:
            logging.warning(  # This is terrible :(
                "{} for transaction {}, DKK {} - '{}':\n"
                "  {}{}"
                "\nStill treated as registration, edit infile and run again if not.\n".format(
                    "Two errors" if wrongFormatMsg and wrongAmountMsg else "One error",
                    transaction[1],
                    toDecimalNumber(transaction[0]),
                    transaction[2],
                    wrongFormatMsg,
                    wrongAmountMsg,
                )
            )

    return isRegistration


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

        if isRegistration(transaction, registrationFee):
            registrationFees += registrationFee
            voucherAmount += transAmount - registrationFee
        else:
            voucherAmount += transAmount

    return (toBank, mpFees, registrationFees, voucherAmount)


def nextBusinessDay(date):
    """Returns the next business day for bank transfer in dd-mm-yyyy format."""

    nextDay = date.date() + dt.timedelta(days=1)
    while nextDay.weekday() in holidays.WEEKEND or nextDay in DANISH_BANK_HOLIDAYS:
        nextDay += dt.timedelta(days=1)

    return dt.datetime.strftime(nextDay, "%d-%m-%Y")


def toDecimalNumber(number):
    """Formats an amount of øre to kroner."""

    return "{:.2f}".format(int(number) / 100).replace(".", ",")


def writeCsv(filePath, appendixStart, transactionsByBatch):
    """Writes the information gathered throughout the script to a CSV file.
    
    The resulting CSV file is recognized by Dinero's journal entry CSV import. \
    The written information is in Danish.
    """

    currAppendix = appendixStart
    csvWriter = prepareCsvWriter(filePath)

    try:
        csvWriter.writerow(["Bilag nr.", "Dato", "Tekst", "Konto", "Beløb", "Modkonto"])
    except UnicodeEncodeError:
        csvWriter.writerow(
            ["Bilag nr.", "Dato", "Tekst", "Konto", "Beløb".encode("utf-8"), "Modkonto"]
        )

    for batch in transactionsByBatch:
        toBank, mpFees, registrationFees, voucherAmount = calculateBatchInfo(batch)
        batchDate = dt.datetime.strptime(batch[0][1], "%d-%m-%Y")
        bankTransferDate = nextBusinessDay(batchDate)

        csvWriter.writerow(
            [
                currAppendix,
                bankTransferDate,
                "MP fra {}-{}".format(
                    str(batchDate.day).zfill(2), str(batchDate.month).zfill(2)
                ),
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


def writePdf(transactionsBatch, writePath):
    """Writes information from a day's worth of MP transactions to a PDF."""

    pdf = FPDF()
    pdf.add_page()

    pdf.set_font("Arial", "B", 16.0)
    colWidths = [11, 82, 25, 20, 26, 25]
    pdf.ln(5)
    pdf.cell(157, 25.0, "Indbetalinger til Stregsystemet via MobilePay", align="L")
    pdf.image("f-klubben.jpg", w=30)
    pdf.ln(1)

    pdf.set_font("Arial", "", 10.0)
    pdf.cell(0, -10, "18-01-2019", align="L")
    pdf.set_font("Arial", "", 10.0)

    pdf.ln(4 * pdf.font_size)

    header = [
        ("Kl.", "R"),
        ("Besked", "L"),
        ("Tilm.gebyr, kr.", "R"),
        ("Overf., kr.", "R"),
        ("MP-gebyr, kr.", "R"),
        ("Gavekort, kr.", "R"),
    ]

    for i, col in enumerate(header):
        pdf.cell(colWidths[i], 1.5 * pdf.font_size, col[0], border="B", align=col[1])

    pdf.ln(2 * pdf.font_size)

    for transaction in transactionsBatch:
        pdf.cell(colWidths[0], 2 * pdf.font_size, str(transaction[4]), align="R")
        pdf.cell(colWidths[1], 2 * pdf.font_size, transaction[2][:49], align="L")
        pdf.cell(colWidths[2], 2 * pdf.font_size, "", align="R")
        pdf.cell(
            colWidths[3], 2 * pdf.font_size, toDecimalNumber(transaction[0]), align="R"
        )
        pdf.cell(
            colWidths[4], 2 * pdf.font_size, toDecimalNumber(transaction[3]), align="R"
        )
        pdf.cell(colWidths[5], 2 * pdf.font_size, "", align="R")
        pdf.ln(2 * pdf.font_size)

    pdf.output(transactionsBatch[0][1] + ".pdf")


def main():
    """Reads a CSV by MP and writes a CSV recognizable by Dinero."""

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    args = parseArgs()
    writePath = handleOutFile(args)

    try:
        transactionsByBatch = readTransactionsFromFile(args.infile)
    except ValueError as e:
        logging.error(e)
        sys.exit(1)

    writeCsv(writePath, args.appendix_start, transactionsByBatch)

    for batch in transactionsByBatch:
        writePdf(batch, writePath)

    logging.info("Done writing to " + writePath)


if __name__ == "__main__":
    main()
