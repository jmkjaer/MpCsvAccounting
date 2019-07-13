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


class Transaction:
    """A transaction with relevant information."""

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

        if not self.isRegistration:
            self.voucherAmount = self.amount
        else:
            self.voucherAmount = self.amount - Transaction.REGISTRATION_FEE

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
                        toDecimalNumber(self.amount, grouping=True),
                        self.message,
                        wrongFormatMsg,
                        wrongAmountMsg,
                    )
                )

        return isRegistration


class TransactionBatch:
    """A day's worth of transactions."""

    def __init__(self):
        self.transactions = []
        self.totalAmount = 0
        self.transferDate = None
        self.mpFees = 0
        self.registrationFees = 0
        self.registrations = 0
        self.voucherAmount = 0
        self.toBank = 0
        self.bankTransferDate = None
        self.isCommitted = False

    def add_transaction(self, transaction):
        """Adds a transaction, and updates instance variables accordingly."""

        self.transactions.append(transaction)
        self.totalAmount += transaction.amount
        self.voucherAmount += transaction.voucherAmount
        self.mpFees += transaction.mpFee

        if transaction.isRegistration:
            transaction.registrationFee = Transaction.REGISTRATION_FEE
            self.registrations += 1
            self.registrationFees += transaction.registrationFee

    def isActive(self):
        """Does the batch currently have any transactions?"""

        return len(self.transactions) > 0

    def commit(self):
        """Sets the relevant dates, calculates the amount of money for the bank."""

        self.transferDate = self.transactions[0].date
        self.bankTransferDate = nextBusinessDay(self.transferDate)
        self.toBank = self.totalAmount - self.mpFees
        self.isCommitted = True

    def getTransactionsByType(self, type):
        """Returns all transactions of specific type.

        Type is either Transaction.SALG or Transaction.REFUNDERING.
        """

        if not self.isCommitted:
            raise UserWarning("Transaction batch is not committed yet.")

        return [t for t in self.transactions if t.type == type]


class Account:
    """String constants for Dinero's accounts."""

    BANK = "55000"
    GAVEKORT = "63080"
    GEBYRER = "7220"
    SALG = "1000"


DANISH_BANK_HOLIDAYS = DanishBankHolidays()


def toDecimalNumber(number, grouping=False):
    """Formats an amount of øre to kroner.

    Trying to avoid locale stuff, since the user might not have da_DK installed.
    If thounsands grouping is checked, we need a third intermediate symbol for the \
    swapping of thousands separator and decimal separator. I've chosen the tilde.

    For the CSV, Dinero accepts no grouping, while it's nice to have in the PDFs.
    """

    if grouping:
        return (
            "{:,.2f}".format(number / 100)
            .replace(".", "~")
            .replace(",", ".")
            .replace("~", ",")
        )
    else:
        return "{:.2f}".format(number / 100).replace(".", ",")


def nextBusinessDay(date):
    """Returns the next business day for bank transfer in dd-mm-yyyy format."""

    nextDay = date + dt.timedelta(days=1)
    while nextDay.weekday() in holidays.WEEKEND or nextDay in DANISH_BANK_HOLIDAYS:
        nextDay += dt.timedelta(days=1)

    return nextDay


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


def readTransactionsFromFile(filePath):
    """Returns transactions in batches read from the CSV file exported by MP.
    
    Returns a list of lists of user transactions bundled in transaction \
    batches before bank transfer. Amount is in øre (1/100th of a krone).
    """

    # Encoding is UTF-16, little-endian, due to MP using MS SQL Server
    file = open(filePath, "r", newline="", encoding="utf-16-le")
    next(file)
    next(file)
    reader = csv.reader(file, delimiter=";")

    transactionBatches = []
    currentBatch = TransactionBatch()

    for index, row in enumerate(reader):
        if row[0] == Transaction.SALG or row[0] == Transaction.REFUNDERING:
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

    file.close()

    return transactionBatches


def toDanishDateFormat(date):
    """Converts a yyyy-MM-dd date to dd-MM-yyyy as a string."""
    return date.strftime("%d-%m-%Y")


def writeCsv(filePath, appendixStart, transactionsByBatch):
    """Writes the information gathered throughout the script to a CSV file.
    
    The resulting CSV file is recognized by Dinero's journal entry CSV import. \
    The written information is in Danish.
    """

    file = open(filePath, "w", newline="")
    csvWriter = csv.writer(file, delimiter=";")

    currAppendix = appendixStart

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
                "MP fra " + batch.transferDate.strftime("%d-%m"),
                Account.BANK,
                toDecimalNumber(batch.toBank),
                None,
            ]
        )
        if batch.voucherAmount > 0:
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

    file.close()


def handlePdfFilename(directory, initFilename):
    """Appends letter to new filename if file already exists (e.g. 01-11-2018a.pdf)."""

    i = "a"
    outName = directory + "/" + initFilename + ".pdf"
    while Path(outName).is_file():
        outName = "{}/{}{}.pdf".format(directory, initFilename, i)
        i = chr(ord(i) + 1)

    return outName


def writePdf(transBatch, directory):
    """Writes information from a day's worth of MP transactions to a PDF.

    Each piece of information is a cell with borders instead of the whole thing being
    a table.
    """

    pdf = FPDF()
    pdf.add_page()

    pdf.ln(5)
    pdf.set_font("Arial", "B", 16.0)
    pdf.cell(157, 25.0, "Indbetalinger til Stregsystemet via MobilePay")
    pdf.image("images/f-klubben.jpg", w=30)
    pdf.ln(0.1)

    pdf.set_font("Arial", "", 10.0)
    pdf.cell(0, -10, "Bilagsdato: " + toDanishDateFormat(transBatch.bankTransferDate))
    pdf.ln(2 * pdf.font_size)

    # High-level information about a transaction batch.
    infoLabelWidth = 60
    infoValueWidth = 20
    infoSpace = 1.5 * pdf.font_size

    pdf.set_font("Arial", "B", 10.0)
    pdf.cell(0, 0, "Oplysninger")
    pdf.ln(infoSpace)

    pdf.set_font("Arial", "", 10.0)
    pdf.cell(infoLabelWidth, 0, "Dato for indbetalinger:")
    pdf.cell(infoValueWidth, 0, toDanishDateFormat(transBatch.transferDate), align="R")
    pdf.ln(infoSpace)

    pdf.cell(infoLabelWidth, 0, "Antal indbetalinger:")
    pdf.cell(
        infoValueWidth,
        0,
        str(len(transBatch.getTransactionsByType(Transaction.SALG))),
        align="R",
    )
    pdf.ln(infoSpace)

    pdf.cell(infoLabelWidth, 0, "Antal tilmeldinger:")
    pdf.cell(infoValueWidth, 0, str(transBatch.registrations), align="R")
    pdf.ln(infoSpace)

    pdf.cell(infoLabelWidth, 0, "MobilePay-gebyr, kr.:")
    pdf.cell(
        infoValueWidth, 0, toDecimalNumber(transBatch.mpFees, grouping=True), align="R"
    )
    pdf.ln(infoSpace)

    pdf.cell(infoLabelWidth, 0, "Indbetalt, kr.:")
    pdf.cell(
        infoValueWidth,
        0,
        toDecimalNumber(transBatch.totalAmount, grouping=True),
        align="R",
    )
    pdf.ln(infoSpace)

    pdf.cell(infoLabelWidth, 0, "Til banken, kr.:")
    pdf.cell(
        infoValueWidth, 0, toDecimalNumber(transBatch.toBank, grouping=True), align="R"
    )
    pdf.ln(infoSpace)

    pdf.cell(infoLabelWidth, 0, "Gavekort, kr.:")
    pdf.cell(
        infoValueWidth,
        0,
        toDecimalNumber(transBatch.voucherAmount, grouping=True),
        align="R",
    )
    pdf.ln(infoSpace)

    pdf.cell(infoLabelWidth, 0, "Tilmeldingsgebyr inkl. moms, kr.:")
    pdf.cell(
        infoValueWidth,
        0,
        toDecimalNumber(transBatch.registrationFees, grouping=True),
        align="R",
    )
    pdf.ln(infoSpace)

    pdf.cell(infoLabelWidth, 0, "Moms, kr.:")
    pdf.cell(
        infoValueWidth,
        0,
        toDecimalNumber(transBatch.registrationFees * 0.25, grouping=True),
        align="R",
    )
    pdf.ln(3 * pdf.font_size)

    transBatch.getTransactionsByType(Transaction.REFUNDERING)

    pdf.set_font("Arial", "", 10.0)

    header = [
        ("Kl.", "R"),
        ("Besked", "L"),
        ("Tilm.gebyr, kr.", "R"),
        ("Indb., kr.", "R"),
        ("MP-gebyr, kr.", "R"),
        ("Gavekort, kr.", "R"),
    ]
    colWidths = [11, 82, 25, 20, 26, 25]  # Seems to work well with A4

    for i, col in enumerate(header):
        pdf.cell(colWidths[i], 1.5 * pdf.font_size, col[0], border="B", align=col[1])

    pdf.ln(2 * pdf.font_size)

    # Table of information about each transaction. Numbers are right-aligned.
    for transaction in transBatch.transactions:
        if transaction.type == Transaction.SALG:
            pdf.set_text_color(0, 0, 0)
        else:
            pdf.set_text_color(220, 0, 0)

        pdf.cell(
            colWidths[0],
            2 * pdf.font_size,
            str(transaction.time.strftime("%H:%M")),
            align="R",
        )
        pdf.cell(colWidths[1], 2 * pdf.font_size, transaction.message[:49], align="L")
        pdf.cell(
            colWidths[2],
            2 * pdf.font_size,
            toDecimalNumber(Transaction.REGISTRATION_FEE, grouping=True)
            if transaction.isRegistration
            else "",
            align="R",
        )
        pdf.cell(
            colWidths[3],
            2 * pdf.font_size,
            toDecimalNumber(transaction.amount, grouping=True),
            align="R",
        )
        pdf.cell(
            colWidths[4],
            2 * pdf.font_size,
            toDecimalNumber(transaction.mpFee, grouping=True),
            align="R",
        )
        pdf.cell(
            colWidths[5],
            2 * pdf.font_size,
            toDecimalNumber(transaction.voucherAmount, grouping=True),
            align="R",
        )
        pdf.ln(2 * pdf.font_size)

    pdf.output(handlePdfFilename(directory, str(transBatch.bankTransferDate)))


def main():
    """Reads a CSV by MP and writes a CSV recognizable by Dinero."""

    logging.basicConfig(level=logging.DEBUG, format="%(levelname)s: %(message)s")

    args = parseArgs()
    writePath = handleOutFile(args)

    try:
        transactionBatches = readTransactionsFromFile(args.infile)
    except ValueError as e:
        logging.error(e)
        sys.exit(1)

    writeCsv(writePath, args.appendix_start, transactionBatches)
    logging.info("Done writing CSV to " + writePath)

    if not args.no_pdf:
        outdir = "pdf"  # This is just temporary
        Path(outdir).mkdir(parents=True, exist_ok=True)

        for batch in transactionBatches:
            writePdf(batch, outdir)

        logging.info("Done writing PDFs to " + outdir + "/")


if __name__ == "__main__":
    main()
