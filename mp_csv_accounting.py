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


def toDanishDateFormat(date):
    return date.strftime("%d-%m-%Y")


def toDecimalNumber(number):
    """Formats an amount of øre to kroner."""

    return "{:.2f}".format(int(number) / 100).replace(".", ",")


def nextBusinessDay(date):
    """Returns the next business day for bank transfer in dd-mm-yyyy format."""

    nextDay = date + dt.timedelta(days=1)
    while nextDay.weekday() in holidays.WEEKEND or nextDay in DANISH_BANK_HOLIDAYS:
        nextDay += dt.timedelta(days=1)

    return nextDay


class Transaction:
    SALG = "Salg"
    REFUNDERING = "Refundering"
    REGISTRATION_FEE = 20000

    def __init__(self, type, amount, date, time, message, mpFee):
        self.type = type

        if type == Transaction.SALG:
            self.amount = int(amount.replace(",", "").replace(".", ""))
        else:
            self.amount = -int(amount.replace(",", "").replace(".", ""))

        self.date = dt.datetime.strptime(date, "%d-%m-%Y").date()
        self.time = dt.datetime.strptime(time, "%H:%M").time()
        self.message = message
        self.mpFee = int(mpFee.replace(",", ""))
        self.isRegistration = self.checkRegistration(Transaction.REGISTRATION_FEE)

    def __repr__(self):
        return "{} {}, {} DKK {}, registration: {}".format(
            self.date,
            self.time,
            self.type,
            toDecimalNumber(self.amount).rjust(6),
            self.isRegistration,
        )

    def checkRegistration(self, registrationFee):
        """Finds out if the transaction is part of a registration.
        
        Searches for the substrings "tilmeld" and "indmeld" in the MP transaction comment,
        warns if so, if in wrong format, and if amount is below transaction fee.
        """

        isRegistration = False

        if "tilmeld" in self.message.lower() or "indmeld" in self.message.lower():
            isRegistration = True

            wrongFormatMsg = (
                "* Wrongly formatted registration message."
                if len(self.message.split()) != 2
                else ""
            )
            wrongAmountMsg = (
                "\n  * Not enough money transferred for registration."
                if int(self.amount) < registrationFee
                else ""
            )

            if wrongFormatMsg or wrongAmountMsg:
                logging.warning(  # This is terrible :(
                    "{} for transaction {}, DKK {} - '{}':\n"
                    "  {}{}"
                    "\nStill treated as registration, edit infile and run again if not.\n".format(
                        "Two errors"
                        if wrongFormatMsg and wrongAmountMsg
                        else "One error",
                        self.date,
                        # toDecimalNumber(self.amount),
                        self.amount / 100,
                        self.message,
                        wrongFormatMsg,
                        wrongAmountMsg,
                    )
                )

        return isRegistration


class TransactionBatch:
    def __init__(self):
        self.transactions = []
        self.totalAmount = 0
        self.date = None
        self.mpFees = 0
        self.registrationFees = 0
        self.registrations = 0
        self.voucherAmount = 0
        self.toBank = 0
        self.bankTransferDate = None

    def add_transaction(self, transaction):
        self.transactions.append(transaction)
        self.totalAmount += transaction.amount
        self.mpFees += transaction.mpFee

        if transaction.isRegistration:
            self.registrations += 1
            self.registrationFees += Transaction.REGISTRATION_FEE
            self.voucherAmount += transaction.amount - Transaction.REGISTRATION_FEE
        else:
            self.voucherAmount += transaction.amount

    def isActive(self):
        return len(self.transactions) > 0

    def commit(self):
        self.date = self.transactions[0].date
        self.bankTransferDate = nextBusinessDay(self.date)
        self.toBank = self.totalAmount - self.mpFees

    def __repr__(self):
        return "Date: {} ({})\n{} transactions\nTotal: {}\nFees: {}\nRegistrations: {}\nRegistration fees: {}\nVoucher amount: {}\nTo bank: {}".format(
            self.date,
            self.bankTransferDate,
            len(self.transactions),
            toDecimalNumber(self.totalAmount),
            toDecimalNumber(self.mpFees),
            self.registrations,
            toDecimalNumber(self.registrationFees),
            toDecimalNumber(self.voucherAmount),
            toDecimalNumber(self.toBank),
        )


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
    parser.add_argument("-n", "--no-pdf", help="don't create PDFs", action="store_true")
    return parser.parse_args()


def handleOutFile(args):
    """If output filename is specified, create dir if applicable, and set writepath."""

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
    transactionBatches = []
    currentBatch = TransactionBatch()

    for index, row in enumerate(reader):
        if row[0] == "Salg" or row[0] == "Refundering":
            currentBatch.add_transaction(
                Transaction(row[0], row[3], row[6], row[7], row[9], row[10])
            )
        elif row[0] == "Overførsel":
            if currentBatch.isActive():
                currentBatch.commit()
                transactionBatches.append(currentBatch)
                currentBatch = TransactionBatch()
        elif row[0] == "Gebyr":
            continue
        else:
            raise ValueError(
                "Unknown transaction type '{}', {}, line {}".format(
                    row[0], filePath, str(index + 3)
                )
            )

    # The imported CSV possibly ends with a batch of sales with no "Overførsel"
    if currentBatch.isActive():
        currentBatch.commit()
        transactionBatches.append(currentBatch)

    return transactionBatches


def prepareCsvWriter(filePath):
    """Prepares the CSV writer by opening the file and setting delimiters."""

    file = open(filePath, "w", newline="")
    csvWriter = csv.writer(file, delimiter=";")
    return csvWriter


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
        csvWriter.writerow(
            [
                currAppendix,
                toDanishDateFormat(batch.bankTransferDate),
                "MP fra {}".format(batch.date.strftime("%d-%m")),
                Account.BANK,
                toDecimalNumber(batch.toBank),
                None,
            ]
        )
        csvWriter.writerow(
            [
                currAppendix,
                toDanishDateFormat(batch.bankTransferDate),
                "Gavekort",
                Account.GAVEKORT,
                "-" + toDecimalNumber(batch.voucherAmount),
                None,
            ]
        )
        if batch.registrations > 0:
            csvWriter.writerow(
                [
                    currAppendix,
                    toDanishDateFormat(batch.bankTransferDate),
                    "Tilmeldingsgebyr",
                    Account.SALG,
                    "-" + toDecimalNumber(batch.registrationFees),
                    None,
                ]
            )
        csvWriter.writerow(
            [
                currAppendix,
                toDanishDateFormat(batch.bankTransferDate),
                "MP-gebyr",
                Account.GEBYRER,
                toDecimalNumber(batch.mpFees),
                None,
            ]
        )

        currAppendix += 1


def handlePdfFilename(directory, initFilename):
    """Appends letter to new filename if file already exists (e.g. 01-11-2018a.pdf)."""

    i = "a"
    outName = directory + "/" + initFilename + ".pdf"
    while Path(outName).is_file():
        outName = "{}/{}{}.pdf".format(directory, initFilename, i)
        i = chr(ord(i) + 1)

    return outName


def writePdf(transactionsBatch, directory):
    """Writes information from a day's worth of MP transactions to a PDF."""

    transferDateString = transactionsBatch[0][1]
    toBankDate = nextBusinessDay(dt.datetime.strptime(transferDateString, "%d-%m-%Y"))

    pdf = FPDF()
    pdf.add_page()

    pdf.set_font("Arial", "B", 16.0)
    pdf.ln(5)
    pdf.cell(157, 25.0, "Indbetalinger til Stregsystemet via MobilePay")
    pdf.image("images/f-klubben.jpg", w=30)
    pdf.ln(1)

    pdf.set_font("Arial", "", 10.0)
    pdf.cell(0, -10, "Dato: " + toBankDate)
    pdf.ln(1.5 * pdf.font_size)

    pdf.cell(0, -10, "Overførsler fra " + transferDateString)
    pdf.ln(4 * pdf.font_size)

    header = [
        ("Kl.", "R"),
        ("Besked", "L"),
        ("Tilm.gebyr, kr.", "R"),
        ("Overf., kr.", "R"),
        ("MP-gebyr, kr.", "R"),
        ("Gavekort, kr.", "R"),
    ]
    colWidths = [11, 82, 25, 20, 26, 25]  # Seems to work well with A4

    for i, col in enumerate(header):
        pdf.cell(colWidths[i], 1.5 * pdf.font_size, col[0], border="B", align=col[1])

    pdf.ln(2 * pdf.font_size)

    for transaction in transactionsBatch:
        pdf.cell(colWidths[0], 2 * pdf.font_size, str(transaction[4]), align="R")
        pdf.cell(colWidths[1], 2 * pdf.font_size, transaction[2][:49], align="L")
        pdf.cell(colWidths[2], 2 * pdf.font_size, "", align="R")
        pdf.cell(
            colWidths[3],
            2 * pdf.font_size,
            toDecimalNumber(transaction[0]),
            align="R",
        )
        pdf.cell(
            colWidths[4],
            2 * pdf.font_size,
            toDecimalNumber(transaction[3]),
            align="R",
        )
        pdf.cell(colWidths[5], 2 * pdf.font_size, "", align="R")
        pdf.ln(2 * pdf.font_size)

    pdf.output(handlePdfFilename(directory, toBankDate))


def main():
    """Reads a CSV by MP and writes a CSV recognizable by Dinero."""

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    args = parseArgs()
    writePath = handleOutFile(args)

    try:
        transactionBatches = readTransactionsFromFile(args.infile)
        print()
        for x in transactionBatches:
            print(x)
            print()
            for y in x.transactions:
                print(y)
            print()
    except ValueError as e:
        logging.error(e)
        sys.exit(1)

    writeCsv(writePath, args.appendix_start, transactionBatches)
    # logging.info("Done writing CSV to " + writePath)

    # if not args.no_pdf:
    #     outdir = "pdfs"  # This is just temporary
    #     Path(outdir).mkdir(parents=True, exist_ok=True)

    #     for batch in transactionBatches:
    #         writePdf(batch, outdir)

    #     logging.info("Done writing PDFs to " + outdir + "/")


if __name__ == "__main__":
    main()
