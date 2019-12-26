#!/usr/bin/env python3

import argparse
import csv
import datetime as dt
import logging
import re
from pathlib import Path

import dateutil.parser
import holidays
import Levenshtein
from dateutil.easter import easter
from fpdf import FPDF

import config


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


class RegistrationHandler:
    """A handler for everything registration.

    Needs to be instantiated to check for registration.
    """

    registrationKeywords = [
        "tilmeld",
        "tilmelding",
        "tilmeldelse",
        "indmeld",
        "indmelding",
        "indmeldelse",
    ]
    maxLevenDist = config.stregsystem.getint("max_edit_distance")

    def __init__(self, amount, date, comment):
        self.amount = amount
        self.date = date
        self.comment = comment

    def isIntendedRegistration(self):
        """Checks if the comment indicates that the transfer is part of registration.
        
        Utilizes the Levenshtein distance to check, since misspellings of the
        registration keywords are common.
        """

        commentSplit = re.split("\W+", self.comment)

        if len(commentSplit) >= 2:  # At least username and keyword
            for keyword in self.registrationKeywords:
                for commentWord in commentSplit:
                    if (
                        Levenshtein.distance(commentWord.lower(), keyword)
                        <= self.maxLevenDist
                    ):
                        return True

        return False

    def isWrongRegistrationAmount(self):
        """Checks if the person has sent enough money for registration."""

        return self.amount < config.stregsystem.getint("registration_fee")

    def warnAboutWrongAmount(self):
        """Shows warning if registration transfer includes enough money."""

        logging.warning(
            f"For transaction {self.date}, DKK {toDecimalNumber(self.amount, grouping=True)} - '{self.comment}':\n"
            "  - Not enough money transferred for registration.\n"
            "Still treated as registration, edit infile and run again if not."
        )


class Transaction:
    """A transaction with relevant information."""

    SALG = "Payment"
    REFUNDERING = "Refund"

    def setattrs(self, **kwargs):
        """Sets multiple attributes at once."""

        for key, value in kwargs.items():
            setattr(self, key, value)

    def isDone(self):
        """Checks if all important attributes have been set."""

        return all(
            hasattr(self, attr)
            for attr in [
                "event",
                "amount",
                "dateAndTime",
                "customerName",
                "comment",
                "mpFee",
            ]
        )

    def checkAndCommit(self):
        """Checks if important attrs have been set, and sets others.

        If the import transaction attributes have been set, then set others based
        on these, e.g. date and time from dateAndTime. Also performs type conversion
        on e.g. amount (with removed punctuation), since we want money as integers
        instead of strings. Lastly, performs registration checks using
        self.checkAndEnterRegistration.
        """

        if self.isDone():
            self.amount = int(self.amount.replace(",", "").replace(".", ""))
            self.mpFee = int(
                self.mpFee.replace("-", "").replace(",", "").replace(".", "")
            )

            parsedDateAndTime = dateutil.parser.parse(self.dateAndTime)
            self.date = parsedDateAndTime.date()
            self.time = parsedDateAndTime.time()

            self.checkAndEnterRegistration()
        else:
            raise UserWarning("Transaction is not done yet.")

    def checkAndEnterRegistration(self):
        """Checks if the current transaction is a registration.

        Creates a RegistrationHandler to check if the amount transferred
        is enough, and if the words in the comment matches a registration
        keyword.
        """

        regHandler = RegistrationHandler(self.amount, self.date, self.comment)

        if regHandler.isIntendedRegistration():
            self.isRegistration = True
            self.voucherAmount = self.amount - config.stregsystem.getint(
                "registration_fee"
            )
            if regHandler.isWrongRegistrationAmount():
                regHandler.warnAboutWrongAmount()
        else:
            self.isRegistration = False
            self.voucherAmount = self.amount


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
        """Adds a transaction, and updates attributes accordingly."""

        self.transactions.append(transaction)
        self.totalAmount += transaction.amount
        self.voucherAmount += transaction.voucherAmount
        self.mpFees += transaction.mpFee

        if transaction.isRegistration:
            self.registrations += 1
            self.registrationFees += config.stregsystem.getint("registration_fee")

    def isActive(self):
        """Does the batch currently have any transactions?"""

        return len(self.transactions) > 0

    def commit(self):
        """Sets the relevant dates, calculates the amount of money for the bank."""

        self.transferDate = self.transactions[0].date
        self.bankTransferDate = nextBusinessDay(self.transferDate)
        self.toBank = self.totalAmount - self.mpFees
        self.isCommitted = True

    def getTransactionsByType(self, event):
        """Returns all transactions of specific type.

        Type is either Transaction.SALG or Transaction.REFUNDERING.
        """

        if not self.isCommitted:
            raise UserWarning("Transaction batch is not committed yet.")

        return [t for t in self.transactions if t.event == event]


class PDF(FPDF):
    """ Class whose purpose is to redefine existing header and footer from FPDF."""

    def header(self):
        if self.page_no() != 1:  # Header is different for first page
            if config.stregsystem.get("mp_number") == "90601":
                tableHeader = [
                    ("Kl.", "R"),
                    ("Besked", "L"),
                    ("Tilm.gebyr, kr.", "R"),
                    ("Indb., kr.", "R"),
                    ("MP-gebyr, kr.", "R"),
                    ("Gavekort, kr.", "R"),
                ]
                colWidths = [11, 82, 25, 20, 26, 25]  # Seems to work well with A4
            else:  # Sales layout
                tableHeader = [
                    ("Kl.", "R"),
                    ("Navn", "L"),
                    ("Indb., kr.", "R"),
                    ("Moms, kr.", "R"),
                    ("MP-gebyr, kr.", "R"),
                ]
                colWidths = [11, 101, 26, 23, 28]

            for i, col in enumerate(tableHeader):
                self.cell(
                    colWidths[i], 1.5 * self.font_size, col[0], border="B", align=col[1]
                )
            self.ln(2 * self.font_size)

    def footer(self):
        self.alias_nb_pages()
        self.set_y(-15)
        self.set_font("Arial", "", 8)
        self.cell(0, 10, str(self.page_no()) + "/{nb}", align="C")


class Layout:
    @staticmethod
    def setFklubInfo(pdf):
        """Three lines of text with F-klubben's actual name, CVR, and website."""

        pdf.set_font("Arial", "", 7)
        pdf.multi_cell(
            0, 3.5, "F-Klubben-Institut for Datalogi\nCVR: 16427888\nhttp://fklub.dk/"
        )

    @staticmethod
    def salesLayout(pdf, transBatch, title):
        setNormalFont = lambda: pdf.set_font("Arial", "", 10.0)

        # Header
        pdf.ln(5)
        pdf.set_font("Arial", "B", 16.0)
        pdf.cell(157, 25.0, title)
        pdf.image("images/f-klubben.png", w=30)
        pdf.ln(0.1)

        setNormalFont()
        pdf.cell(
            155, -10, "Bilagsdato: " + toDanishDateFormat(transBatch.bankTransferDate)
        )
        Layout.setFklubInfo(pdf)

        pdf.ln(-1 * pdf.font_size)

        # High-level information about a transaction batch.
        setNormalFont()
        infoLabelWidth = 60
        infoValueWidth = 20
        infoSpace = 1.5 * pdf.font_size

        pdf.set_font("Arial", "B", 10.0)
        pdf.cell(0, 0, "Oplysninger")
        pdf.ln(infoSpace)

        setNormalFont()
        pdf.cell(infoLabelWidth, 0, "Dato for indbetalinger:")
        pdf.cell(
            infoValueWidth, 0, toDanishDateFormat(transBatch.transferDate), align="R"
        )
        pdf.ln(infoSpace)

        pdf.cell(infoLabelWidth, 0, "Antal indbetalinger:")
        pdf.cell(
            infoValueWidth,
            0,
            str(len(transBatch.getTransactionsByType(Transaction.SALG))),
            align="R",
        )
        pdf.ln(infoSpace)

        pdf.cell(infoLabelWidth, 0, "MobilePay-gebyr, kr.:")
        pdf.cell(
            infoValueWidth,
            0,
            toDecimalNumber(transBatch.mpFees, grouping=True),
            align="R",
        )
        pdf.ln(infoSpace)

        pdf.cell(infoLabelWidth, 0, "Indbetalt inkl. moms, kr.:")
        pdf.cell(
            infoValueWidth,
            0,
            toDecimalNumber(transBatch.totalAmount, grouping=True),
            align="R",
        )
        pdf.ln(infoSpace)

        pdf.cell(infoLabelWidth, 0, "Moms, kr.:")
        pdf.cell(
            infoValueWidth,
            0,
            toDecimalNumber(transBatch.totalAmount * 0.2, grouping=True),
            align="R",
        )
        pdf.ln(infoSpace)

        pdf.cell(infoLabelWidth, 0, "Til banken, kr.:")
        pdf.cell(
            infoValueWidth,
            0,
            toDecimalNumber(transBatch.toBank, grouping=True),
            align="R",
        )
        pdf.ln(3 * pdf.font_size)

        setNormalFont()

        header = [
            ("Kl.", "R"),
            ("Navn", "L"),
            ("Indb., kr.", "R"),
            ("Moms, kr.", "R"),
            ("MP-gebyr, kr.", "R"),
        ]
        colWidths = [11, 101, 26, 23, 28]  # Seems to work well with A4

        for i, col in enumerate(header):
            pdf.cell(
                colWidths[i], 1.5 * pdf.font_size, col[0], border="B", align=col[1]
            )

        pdf.ln(2 * pdf.font_size)

        # Table of information about each transaction. Numbers are right-aligned.
        for transaction in transBatch.transactions:
            if transaction.event == Transaction.SALG:
                pdf.set_text_color(0, 0, 0)
            else:
                pdf.set_text_color(220, 0, 0)

            pdf.cell(
                colWidths[0],
                2 * pdf.font_size,
                str(transaction.time.strftime("%H:%M")),
                align="R",
            )
            pdf.cell(
                colWidths[1],
                2 * pdf.font_size,
                transaction.customerName[:49],
                align="L",
            )
            pdf.cell(
                colWidths[2],
                2 * pdf.font_size,
                toDecimalNumber(transaction.amount, grouping=True),
                align="R",
            )
            pdf.cell(
                colWidths[3],
                2 * pdf.font_size,
                toDecimalNumber(transaction.amount * 0.2),
                align="R",
            ),
            pdf.cell(
                colWidths[4],
                2 * pdf.font_size,
                toDecimalNumber(transaction.mpFee, grouping=True),
                align="R",
            )
            pdf.ln(2 * pdf.font_size)

    @staticmethod
    def stregsystemLayout(pdf, transBatch, title):
        setNormalFont = lambda: pdf.set_font("Arial", "", 10.0)

        # Header
        pdf.ln(5)
        pdf.set_font("Arial", "B", 16.0)
        pdf.cell(157, 25.0, title)
        pdf.image("images/f-klubben.png", w=30)
        pdf.ln(0.1)

        setNormalFont()
        pdf.cell(
            155, -10, "Bilagsdato: " + toDanishDateFormat(transBatch.bankTransferDate)
        )
        Layout.setFklubInfo(pdf)

        pdf.ln(-1 * pdf.font_size)

        # High-level information about a transaction batch.
        setNormalFont()
        infoLabelWidth = 60
        infoValueWidth = 20
        infoSpace = 1.5 * pdf.font_size

        pdf.set_font("Arial", "B", 10.0)
        pdf.cell(0, 0, "Oplysninger")
        pdf.ln(infoSpace)

        setNormalFont()
        pdf.cell(infoLabelWidth, 0, "Dato for indbetalinger:")
        pdf.cell(
            infoValueWidth, 0, toDanishDateFormat(transBatch.transferDate), align="R"
        )
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
            infoValueWidth,
            0,
            toDecimalNumber(transBatch.mpFees, grouping=True),
            align="R",
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
            infoValueWidth,
            0,
            toDecimalNumber(transBatch.toBank, grouping=True),
            align="R",
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
            toDecimalNumber(transBatch.registrationFees * 0.2, grouping=True),
            align="R",
        )
        pdf.ln(3 * pdf.font_size)

        transBatch.getTransactionsByType(Transaction.REFUNDERING)

        setNormalFont()

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
            pdf.cell(
                colWidths[i], 1.5 * pdf.font_size, col[0], border="B", align=col[1]
            )

        pdf.ln(2 * pdf.font_size)

        # Table of information about each transaction. Numbers are right-aligned.
        for transaction in transBatch.transactions:
            if transaction.event == Transaction.SALG:
                pdf.set_text_color(0, 0, 0)
            else:
                pdf.set_text_color(220, 0, 0)

            pdf.cell(
                colWidths[0],
                2 * pdf.font_size,
                str(transaction.time.strftime("%H:%M")),  # TODO
                align="R",
            )
            if transaction.comment:
                pdf.cell(
                    colWidths[1], 2 * pdf.font_size, transaction.comment[:49], align="L"
                )
            else:
                pdf.set_font("Arial", "I", 10.0)
                pdf.cell(
                    colWidths[1],
                    2 * pdf.font_size,
                    transaction.customerName[:49],
                    align="L",
                )
                setNormalFont()

            pdf.cell(
                colWidths[2],
                2 * pdf.font_size,
                toDecimalNumber(
                    config.stregsystem.getint("registration_fee"), grouping=True
                )
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


DANISH_BANK_HOLIDAYS = DanishBankHolidays()


def toDecimalNumber(number, grouping=False):
    """Formats an amount of øre to kroner.

    Trying to avoid locale stuff, since the user might not have da_DK installed.
    If thounsands grouping is checked, we need a third intermediate symbol for the
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
        "appendix_start", type=int, help="the appendix number to start from in Dinero"
    )
    parser.add_argument(
        "-n",
        "--mp_number",
        help="the MyShop-number whose transactions are parsed. Overrides mp_number in config.ini",
    )
    return parser.parse_args()


def readTransactionsFromFile(filePath, mpNumber):
    """Returns transactions in batches read from the CSV file exported by MP.

    The parameter "mpNumber" is the number that members of F-klubben
    send money to using MP for the Stregsystem. Is read from a config file.
    
    Returns a list of lists of user transactions bundled in transaction
    batches before bank transfer. Amount is in øre (1/100th of a krone).
    """

    file = open(filePath, "r", newline="")
    reader = csv.DictReader(file, delimiter=";")

    transactionBatches = []
    currentBatch = TransactionBatch()

    transferAmount = 0  # to mpNumber
    otherPlacesAmount = 0

    newTrans = Transaction()
    for index, row in reversed(list(enumerate(reader))):
        if row["MyShop-Number"] == mpNumber:
            if row["Event"] == Transaction.SALG:
                newTrans.setattrs(
                    event=row["Event"],
                    amount=row["Amount"],
                    dateAndTime=row["Date and time"],
                    customerName=row["Customer name"],
                    comment=row["Comment"],
                )

                newTrans.checkAndCommit()
                currentBatch.add_transaction(newTrans)
                newTrans = Transaction()

                transferAmount += 1

            elif row["Event"] == "Retainable":
                newTrans.mpFee = row["Amount"]
                # if newTrans.event != None and newTrans.mpFee != None:
                if hasattr(newTrans, "event") and hasattr(newTrans, "mpFee"):
                    newTrans.checkAndCommit()
                    currentBatch.add_transaction(newTrans)
                    newTrans = Transaction()

            elif row["Event"] == Transaction.REFUNDERING:
                refund = Transaction()
                refund.setattrs(
                    event=row["Event"],
                    amount=row["Amount"],
                    dateAndTime=row["Date and time"],
                    customerName=row["Customer name"],
                    comment="",
                    mpFee="0",
                )
                refund.checkAndCommit()
                currentBatch.add_transaction(refund)
                transferAmount += 1

            elif row["Event"] == "Transfer":
                if currentBatch.isActive():
                    currentBatch.commit()
                    transactionBatches.append(currentBatch)
                    currentBatch = TransactionBatch()

            elif row["Event"] == "ServiceFee":
                serviceFee = Transaction()
                serviceFee.setattrs(
                    event=row["Event"],
                    amount="0",
                    dateAndTime=row["Date and time"],
                    customerName="",
                    comment=row["Comment"],
                    mpFee=row["Amount"],
                )
                serviceFee.checkAndCommit()
                currentBatch.add_transaction(serviceFee)
                transferAmount += 1
            else:
                raise ValueError(
                    f"Line {str(index + 2)} in infile:\nUnknown transaction type '{row['Event']}'."
                )
        else:
            otherPlacesAmount += 1

    if transferAmount > 0:
        logging.info(
            f"Handled {transferAmount} transfer{'s' if transferAmount > 1 else ''} for {mpNumber}."
        )

    if otherPlacesAmount > 0:
        logging.info(
            f"Skipped {otherPlacesAmount} transfer{'s' if otherPlacesAmount > 1 else ''} not for {mpNumber}."
        )

    # The imported CSV possibly ends with a batch of sales with no "Overførsel"
    # due to next day bank transfer being next month
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
    
    The resulting CSV file is recognized by Dinero's journal entry CSV import.
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
        if config.stregsystem.get("mp_number") == "90601":
            csvWriter.writerow(
                [
                    currAppendix,
                    toDanishDateFormat(batch.bankTransferDate),
                    "MP fra " + batch.transferDate.strftime("%d-%m"),
                    config.dinero.get("bank"),
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
                        config.dinero.get("gavekort"),
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
                        config.dinero.get("salg"),
                        "-" + toDecimalNumber(batch.registrationFees),
                        None,
                    ]
                )
            csvWriter.writerow(
                [
                    currAppendix,
                    toDanishDateFormat(batch.bankTransferDate),
                    "MP-gebyr",
                    config.dinero.get("gebyrer"),
                    toDecimalNumber(batch.mpFees),
                    None,
                ]
            )
        else:
            csvWriter.writerow(
                [
                    currAppendix,
                    toDanishDateFormat(batch.bankTransferDate),
                    "Salg via MP fra " + batch.transferDate.strftime("%d-%m"),
                    config.dinero.get("bank"),
                    toDecimalNumber(batch.toBank),
                    None,
                ]
            )
            csvWriter.writerow(
                [
                    currAppendix,
                    toDanishDateFormat(batch.bankTransferDate),
                    "Salg",
                    config.dinero.get("salg"),
                    "-" + toDecimalNumber(batch.totalAmount),
                    None,
                ]
            )
            csvWriter.writerow(
                [
                    currAppendix,
                    toDanishDateFormat(batch.bankTransferDate),
                    "MP-gebyr",
                    config.dinero.get("gebyrer"),
                    toDecimalNumber(batch.mpFees),
                    None,
                ]
            )

        currAppendix += 1

    file.close()


def makePdfFilename(directory, appendixNumber):
    """Creates a filename for the new PDF."""

    return f"{directory}/{str(appendixNumber)}.pdf"


def writePdf(transBatch, directory, appendixNumber, layout, title):
    """Writes information from a day's worth of MP transactions to a PDF.

    Each piece of information is a cell with borders instead of the whole thing being
    a table.
    """

    pdf = PDF()
    pdf.set_auto_page_break(1, margin=13)
    pdf.add_page()

    layout(pdf, transBatch, title)

    pdf.output(makePdfFilename(directory, appendixNumber))


def makeAppendixRange(appendixStart, appendixAmount):
    """Creates the name for the PDF directory and CSV file based on appendix amount.
    
    For the example file in examples/mpExample.csv, this would be 123-148."""

    appendixEnd = appendixStart + appendixAmount - 1

    return f"{appendixStart}-{appendixEnd}"


def handlePdfCreation(appendixStart, transactionBatches):
    """Creates a PDF directory, and calls function that creates PDFs. Returns outdir."""

    appendixNumber = appendixStart
    outdir = makeAppendixRange(appendixStart, len(transactionBatches))
    Path(outdir).mkdir(parents=True, exist_ok=True)

    if config.stregsystem.get("mp_number") == "90601":
        for batch in transactionBatches:
            writePdf(
                batch,
                outdir,
                appendixNumber,
                Layout.stregsystemLayout,
                config.stregsystem.get("stregsystem_title"),
            )
            appendixNumber += 1
    else:
        for batch in transactionBatches:
            writePdf(
                batch,
                outdir,
                appendixNumber,
                Layout.salesLayout,
                config.stregsystem.get("sales_title"),
            )
            appendixNumber += 1

    return outdir


def main():
    """Reads a CSV by MP and writes a CSV recognizable by Dinero as well as PDFs."""

    logging.basicConfig(level=logging.DEBUG, format="%(levelname)s:\n%(comment)s\n")

    args = parseArgs()

    try:
        transactionBatches = readTransactionsFromFile(
            args.infile,
            config.stregsystem.get("mp_number")
            if not args.mp_number
            else args.mp_number,
        )
    except ValueError as e:
        logging.error(e)
        return

    batchAmount = len(transactionBatches)

    if batchAmount == 0:
        logging.warning("No valid transactions, nothing to be done.")
        return

    csvName = makeAppendixRange(args.appendix_start, batchAmount) + ".csv"
    writeCsv(csvName, args.appendix_start, transactionBatches)
    logging.info(f"Done writing {csvName}")

    pdfDir = handlePdfCreation(args.appendix_start, transactionBatches)

    logging.info(
        f"Done creating {batchAmount} PDF{'s' if batchAmount > 1 else ''} in {pdfDir}/"
    )


if __name__ == "__main__":
    main()
